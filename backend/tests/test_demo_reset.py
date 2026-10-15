"""
D4 — Reset + hijyen kapıları (DEMO_PLAN §D4).

1. DELETE /demo/reset        → 401 authsuz · 403 demo_mode kapalıyken
2. reset                     → klonun simetriği: konuk demo job + report/tx/
   anomaly + context + semantic silinir; GOLDEN sağ salim; idempotent
3. golden koruma              → demo-golden org'undan reset = 409
4. seed günlük limit          → kullanıcı başına günde 5 istek, 6. = 429
   (middleware route limiti; idempotent tekrarlar da sayılır — bilinçli)
5. TTL cron çekirdeği         → süresi dolan KONUK org purge; golden + gerçek
   org (eski olsa bile) + taze konuk dokunulmaz
6. dosya hijyeni              → paylaşılan dosya purge edilen job'ın kendisi
   silinmedikçe kalmaz; tek başına kullanılan dosya unlink edilir
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.org import _regional_defaults
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.company_context import CompanyContextSnapshot
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.organization import Organization
from app.models.report import Report, ReportFormat
from app.models.user import User, UserRole
from app.scheduler import _purge_expired_guests
from app.services.auth import create_access_token
from app.services.company_context import (
    CompanyContext,
    save_company_context,
)
from app.services.demo_template import (
    DEMO_FILENAME,
    GOLDEN_SLUG,
    GUEST_DESCRIPTION,
    purge_demo_workspace,
)


@pytest_asyncio.fixture
async def test_client(monkeypatch):
    """In-memory DB dependency override + demo_mode on (test_demo_clone kalıbı)."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "demo_mode", True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._test_sessionmaker = TestSessionLocal  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _seed_golden(sessionmaker) -> str:
    """Golden org + tamamlanmış demo job + report + context (clone kalıbı)."""
    async with sessionmaker() as db:
        org = Organization(
            name="TechNova Yazılım A.Ş.",
            slug=GOLDEN_SLUG,
            **_regional_defaults("TR"),
        )
        db.add(org)
        await db.flush()

        job = AnalysisJob(
            status=JobStatus.COMPLETED,
            filename=DEMO_FILENAME,
            file_path="golden_demo.csv",
            file_type="csv",
            org_id=str(org.id),
            user_id=None,
        )
        db.add(job)
        await db.flush()

        db.add(
            Report(
                job_id=str(job.id),
                report_type="full",
                report_format=ReportFormat.JSON,
                data={"job_id": str(job.id), "net": 12345},
            )
        )

        ctx = CompanyContext(org_id=str(org.id), company_name="TechNova Yazılım A.Ş.")
        ctx.update_agent_result(
            "cfo", {"job_id": str(job.id), "dashboard": {"net": 12345}}
        )
        ctx.set_active_job("cfo", str(job.id))
        await save_company_context(ctx, db)

        db.add(
            CompanySemanticSnapshotRow(
                org_id=str(org.id),
                period_key="2024",
                metrics_json="[]",
                drivers_json="[]",
                evidence_json="[]",
                source_job_ids=json.dumps([str(job.id)]),
            )
        )
        await db.commit()
        return str(job.id)


async def _guest(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/demo/guest")
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _auth(data: dict) -> dict:
    return {"Authorization": f"Bearer {data['access_token']}"}


async def _count(sessionmaker, model, **filters) -> int:
    async with sessionmaker() as db:
        rows = (await db.execute(select(model).filter_by(**filters))).scalars().all()
        return len(rows)


async def _org_id_by_slug(sessionmaker, slug: str) -> str:
    async with sessionmaker() as db:
        return str(
            (
                await db.execute(
                    select(Organization.id).where(Organization.slug == slug)
                )
            ).scalar_one()
        )


# ── 1–3. Reset kapıları ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_requires_auth(test_client):
    """Auth wall: token'sız reset = 401."""
    resp = await test_client.delete("/api/v1/demo/reset")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reset_disabled_without_demo_mode(test_client, monkeypatch):
    """Secure default: demo_mode off → reset 403 (guest minting gibi)."""
    data = await _guest(test_client)
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    resp = await test_client.delete("/api/v1/demo/reset", headers=_auth(data))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reset_clears_guest_workspace_and_keeps_golden(test_client):
    """Reset, clone'ın tersi: konuk tamamen boşalır, golden'e dokunulmaz,
    ikinci çağrı idempotent (sıfır sayaçlar)."""
    golden_job_id = await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)
    org_id = data["user"]["org_id"]
    sm = test_client._test_sessionmaker
    golden_org_id = await _org_id_by_slug(sm, GOLDEN_SLUG)

    # Klon geldi: demo job + context + semantic dolu
    assert await _count(sm, AnalysisJob, org_id=org_id, filename=DEMO_FILENAME) == 1
    assert await _count(sm, CompanyContextSnapshot, org_id=org_id) == 1
    assert await _count(sm, CompanySemanticSnapshotRow, org_id=org_id) == 1

    resp = await test_client.delete("/api/v1/demo/reset", headers=_auth(data))
    assert resp.status_code == 200, resp.text
    counts = resp.json()["data"]["counts"]
    assert counts["jobs"] == 1
    assert counts["reports"] >= 1
    assert counts["context"] == 1
    assert counts["semantic"] == 1

    # Konuk boş: demo job/context/semantic + klonlanmış raporlar gitti
    assert await _count(sm, AnalysisJob, org_id=org_id, filename=DEMO_FILENAME) == 0
    assert await _count(sm, CompanyContextSnapshot, org_id=org_id) == 0
    assert await _count(sm, CompanySemanticSnapshotRow, org_id=org_id) == 0

    # Golden sağ salim (job + report + context) ve toplam rapor = golden'ınki
    assert await _count(sm, AnalysisJob, id=golden_job_id) == 1
    assert await _count(sm, Report, job_id=golden_job_id) == 1
    assert await _count(sm, CompanyContextSnapshot, org_id=golden_org_id) == 1
    assert await _count(sm, Report) == 1

    # İkinci reset idempotent
    again = await test_client.delete("/api/v1/demo/reset", headers=_auth(data))
    assert again.status_code == 200
    assert all(v == 0 for v in again.json()["data"]["counts"].values())


@pytest.mark.asyncio
async def test_reset_refuses_golden_org(test_client):
    """demo-golden reset'lenemez: her klonu o besler → 409."""
    await _seed_golden(test_client._test_sessionmaker)
    sm = test_client._test_sessionmaker
    golden_org_id = await _org_id_by_slug(sm, GOLDEN_SLUG)

    async with sm() as db:
        user = User(
            email="golden-owner@example.com",
            hashed_password="not-a-real-login-hash",
            full_name="Golden Owner",
            role=UserRole.OWNER,
            org_id=golden_org_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, user.email, user.role)

    resp = await test_client.delete(
        "/api/v1/demo/reset", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 409
    # Golden job yerinde:
    assert await _count(sm, AnalysisJob, org_id=golden_org_id, filename=DEMO_FILENAME) == 1


# ── 4. Seed günlük limiti ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_daily_limit_returns_429(test_client, tmp_path, monkeypatch):
    """Kullanıcı başına günde 5 seed isteği; 6. = 429 + Retry-After."""
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    data = await _guest(test_client)
    headers = _auth(data)

    for i in range(5):
        resp = await test_client.post("/api/v1/demo/seed", headers=headers)
        assert resp.status_code == 200, f"istek {i + 1}: {resp.text}"

    blocked = await test_client.post("/api/v1/demo/seed", headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


# ── 5. TTL cron çekirdeği ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ttl_purge_only_expired_guests(test_client):
    """Süresi dolan konuk purge; golden + eski gerçek org + taze konuk korunur."""
    sm = test_client._test_sessionmaker
    golden_job_id = await _seed_golden(sm)

    async with sm() as db:
        # (a) süresi dolmuş konuk — 48 saat önce doğdu, tam iş verisiyle
        expired_guest = Organization(
            name="TechNova Yazılım A.Ş.",
            slug="demo-0123456789ab",
            description=GUEST_DESCRIPTION,
            created_at=datetime.now(UTC) - timedelta(hours=48),
            **_regional_defaults("TR"),
        )
        db.add(expired_guest)
        await db.flush()
        db.add(
            AnalysisJob(
                status=JobStatus.COMPLETED,
                filename=DEMO_FILENAME,
                file_path="expired_guest.csv",
                file_type="csv",
                org_id=str(expired_guest.id),
                user_id=None,
            )
        )
        await save_company_context(
            CompanyContext(org_id=str(expired_guest.id), company_name="Eski Konuk"), db
        )
        db.add(
            CompanySemanticSnapshotRow(
                org_id=str(expired_guest.id),
                period_key="2024",
                metrics_json="[]",
                drivers_json="[]",
                evidence_json="[]",
                source_job_ids="[]",
            )
        )

        # (b) süresi dolmuş GERÇEK org — demo job'ı olsa bile dokunulmaz
        real_org = Organization(
            name="Gerçek Şirket A.Ş.",
            slug="gercek-sirket",
            description="Kendi verisini yükleyen kayıtlı org.",
            created_at=datetime.now(UTC) - timedelta(hours=48),
            **_regional_defaults("TR"),
        )
        db.add(real_org)
        await db.flush()
        db.add(
            AnalysisJob(
                status=JobStatus.COMPLETED,
                filename=DEMO_FILENAME,
                file_path="real_demo.csv",
                file_type="csv",
                org_id=str(real_org.id),
                user_id=None,
            )
        )

        # (c) taze konuk — TTL henüz dolmadı
        fresh_guest = Organization(
            name="TechNova Yazılım A.Ş.",
            slug="demo-fedcba987654",
            description=GUEST_DESCRIPTION,
            **_regional_defaults("TR"),
        )
        db.add(fresh_guest)
        await db.flush()
        db.add(
            AnalysisJob(
                status=JobStatus.COMPLETED,
                filename=DEMO_FILENAME,
                file_path="fresh_guest.csv",
                file_type="csv",
                org_id=str(fresh_guest.id),
                user_id=None,
            )
        )
        await db.commit()

        expired_guest_id = str(expired_guest.id)
        real_org_id = str(real_org.id)
        fresh_guest_id = str(fresh_guest.id)

    async with sm() as db:
        purged = await _purge_expired_guests(db, ttl_hours=24)

    assert purged == 1, "yalnızca süresi dolan konuk purge edilmeli"
    assert await _count(sm, AnalysisJob, org_id=expired_guest_id) == 0
    assert await _count(sm, CompanyContextSnapshot, org_id=expired_guest_id) == 0
    assert await _count(sm, CompanySemanticSnapshotRow, org_id=expired_guest_id) == 0
    # Korunanlar:
    assert await _count(sm, AnalysisJob, org_id=real_org_id, filename=DEMO_FILENAME) == 1
    assert await _count(sm, AnalysisJob, org_id=fresh_guest_id, filename=DEMO_FILENAME) == 1
    assert await _count(sm, AnalysisJob, id=golden_job_id) == 1


# ── 6. Dosya hijyeni ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_purge_unlinks_only_unshared_files(test_client, tmp_path):
    """Tek başına kullanılan demo dosyası silinir; paylaşılan dosya purge edilen
    job'ın kendisi olmadığı sürece referans sayesinde kalır (golden kuralı)."""
    sm = test_client._test_sessionmaker
    shared = tmp_path / "shared.csv"
    unique = tmp_path / "unique.csv"
    shared.write_text("tarih,tutar\n", encoding="utf-8")
    unique.write_text("tarih,tutar\n", encoding="utf-8")

    async with sm() as db:
        holder = Organization(
            name="Paylaşan Org", slug="paylasan-org", **_regional_defaults("TR")
        )
        db.add(holder)
        await db.flush()
        # Holder + "golden" (B) AYNI dosyayı referanslar — clone dosyayı
        # golden'dan paylaşır; C'nin kendi tek başına kullandığı dosyası ayrı.
        db.add(
            AnalysisJob(
                status=JobStatus.COMPLETED,
                filename=DEMO_FILENAME,
                file_path=str(shared),
                file_type="csv",
                org_id=str(holder.id),
                user_id=None,
            )
        )
        golden_like = Organization(
            name="Golden-Benzeri Org", slug="golden-benzeri", **_regional_defaults("TR")
        )
        db.add(golden_like)
        await db.flush()
        db.add(
            AnalysisJob(
                status=JobStatus.COMPLETED,
                filename=DEMO_FILENAME,
                file_path=str(shared),
                file_type="csv",
                org_id=str(golden_like.id),
                user_id=None,
            )
        )
        solo = Organization(
            name="Tek Kullanım Org", slug="tek-kullanim", **_regional_defaults("TR")
        )
        db.add(solo)
        await db.flush()
        db.add(
            AnalysisJob(
                status=JobStatus.COMPLETED,
                filename=DEMO_FILENAME,
                file_path=str(unique),
                file_type="csv",
                org_id=str(solo.id),
                user_id=None,
            )
        )
        await db.commit()
        holder_id = str(holder.id)
        solo_id = str(solo.id)
        golden_like_id = str(golden_like.id)

    # Holder purge → shared hâlâ golden-benzeri job'ı referanslıyor: KALIR
    async with sm() as db:
        await purge_demo_workspace(db, holder_id)
    assert shared.exists(), "başkasının (golden benzeri) paylaşılan dosyası kalmalı"
    assert unique.exists()

    # Solo purge → unique için referans kalmadı → unlink; shared'a dokunulmaz
    async with sm() as db:
        await purge_demo_workspace(db, solo_id)
    assert not unique.exists(), "tek başına kullanılan demo dosyası silinmeli"
    assert shared.exists(), "yabancının dosyası asla silinmez"
    # Golden-benzeri org hâlâ iş başında:
    assert await _count(
        sm, AnalysisJob, org_id=golden_like_id, filename=DEMO_FILENAME
    ) == 1
