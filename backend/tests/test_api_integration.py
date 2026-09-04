"""
FastAPI API Integration Tests.

Verifies end-to-end HTTP request/response flows against the FastAPI application
using httpx.AsyncClient (ASGITransport) and in-memory test database:
1. Health check
2. Billing plans
3. API key generation, SHA-256 hashing, and API key header authentication
4. User registration and login (JWT access tokens)
5. Authenticated profile endpoint
6. Global 422 and 500 sanitized error handlers
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.services.auth import generate_api_key, hash_api_key


@pytest_asyncio.fixture
async def test_client():
    """Async test client with in-memory SQLite database dependency override."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Expose the test sessionmaker so tests can seed rows directly.
        client._test_sessionmaker = TestSessionLocal  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_health_check_endpoint(test_client):
    """Verify standard /health endpoint returns 200 OK."""
    resp = await test_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


@pytest.mark.asyncio
async def test_billing_plans_public_endpoint(test_client):
    """Verify /api/v1/billing/plans returns all subscription tiers."""
    resp = await test_client.get("/api/v1/billing/plans")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    plans = body.get("data", {}).get("plans", [])
    assert len(plans) >= 3
    plan_ids = [p["id"] for p in plans]
    assert "starter" in plan_ids
    assert "pro" in plan_ids


@pytest.mark.asyncio
async def test_api_key_hashing_and_verification():
    """Verify API keys are hashed with SHA-256."""
    raw_key = generate_api_key()
    assert raw_key.startswith("cfo_")

    hashed_1 = hash_api_key(raw_key)
    hashed_2 = hash_api_key(raw_key)
    assert hashed_1 == hashed_2
    assert len(hashed_1) == 64  # SHA-256 hex string


@pytest.mark.asyncio
async def test_user_registration_login_and_auth_flow(test_client):
    """Verify registration, login with JWT, and accessing protected /auth/me."""
    reg_resp = await test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "cfo.test@company.com",
            "password": "StrongPassword123!",
            "full_name": "Test CFO",
        },
    )
    assert reg_resp.status_code == 201
    reg_body = reg_resp.json()
    assert reg_body.get("data", {}).get("email") == "cfo.test@company.com"

    # Login
    login_resp = await test_client.post(
        "/api/v1/auth/login",
        json={
            "email": "cfo.test@company.com",
            "password": "StrongPassword123!",
        },
    )
    assert login_resp.status_code == 200
    login_body = login_resp.json()
    token = login_body.get("data", {}).get("access_token")
    assert token is not None

    # Access protected /auth/me
    me_resp = await test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    me_body = me_resp.json()
    assert me_body.get("data", {}).get("email") == "cfo.test@company.com"
    # The server assigns the role; a registrant does not get to pick one.
    assert me_body.get("data", {}).get("role") == "analyst"


@pytest.mark.asyncio
async def test_registration_cannot_self_assign_a_role(test_client):
    """`role` used to be a field on RegisterRequest with an analyst default, so
    anyone could POST {"role": "owner"} and register as an owner. The field is
    gone and extras are rejected, so the attempt fails loudly rather than being
    silently ignored."""
    resp = await test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalate@company.com",
            "password": "StrongPassword123!",
            "full_name": "Would-be owner",
            "role": "owner",
        },
    )
    assert resp.status_code == 422, resp.text

    # And the account was not created as a side effect.
    login = await test_client.post(
        "/api/v1/auth/login",
        json={"email": "escalate@company.com", "password": "StrongPassword123!"},
    )
    assert login.status_code == 401


@pytest.mark.asyncio
async def test_api_key_generation_and_authentication(test_client):
    """Verify API key creation and subsequent authentication via X-API-Key."""
    # Register & login
    await test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "api.user@company.com",
            "password": "StrongPassword123!",
            "full_name": "API User",
        },
    )
    login_resp = await test_client.post(
        "/api/v1/auth/login",
        json={"email": "api.user@company.com", "password": "StrongPassword123!"},
    )
    token = login_resp.json()["data"]["access_token"]

    # Generate API key
    key_resp = await test_client.post(
        "/api/v1/auth/api-key",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert key_resp.status_code == 200
    api_key = key_resp.json()["data"]["api_key"]
    assert api_key.startswith("cfo_")

    # Access /auth/me using X-API-Key header (no Bearer token)
    me_resp = await test_client.get(
        "/api/v1/auth/me",
        headers={"X-API-Key": api_key},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["email"] == "api.user@company.com"


@pytest.mark.asyncio
async def test_validation_error_handler_sanitized_format(test_client):
    """Verify 422 validation errors return normalized secure envelope."""
    resp = await test_client.post("/api/v1/auth/login", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body.get("data") is None
    assert "error" in body
    assert body.get("status_code") == 422


@pytest.mark.asyncio
async def test_llm_costs_endpoint_empty_ledger(test_client):
    """GET /api/v1/system/llm-costs returns a zeroed rollup on a fresh DB."""
    resp = await test_client.get("/api/v1/system/llm-costs?days=7")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["window_days"] == 7
    assert data["total_calls"] == 0
    assert data["total_cost_usd"] == 0.0
    assert data["by_model"] == []
    assert data["by_org"] == []
    assert "live_process_aggregate" in data


@pytest.mark.asyncio
async def test_llm_costs_endpoint_aggregates_rows(test_client):
    """Insert LLMCallLog rows and verify the rollup groups them."""
    from app.database import get_db
    from app.models.llm_call_log import LLMCallLog

    override = test_client._transport.app.dependency_overrides[get_db]
    agen = override()
    db = await agen.__anext__()
    try:
        db.add_all([
            LLMCallLog(org_id="org-A", task_type="short_narrative", model="gpt-4o-mini",
                       input_tokens=100, output_tokens=50, cost_usd=0.01, latency_ms=120, ok=True),
            LLMCallLog(org_id="org-A", task_type="deep_analysis", model="gpt-4o",
                       input_tokens=800, output_tokens=400, cost_usd=0.05, latency_ms=900, ok=True),
            LLMCallLog(org_id="org-B", task_type="short_narrative", model="gpt-4o-mini",
                       input_tokens=200, output_tokens=80, cost_usd=0.02, latency_ms=200, ok=False),
        ])
        await db.commit()
    finally:
        await agen.aclose()

    data = (await test_client.get("/api/v1/system/llm-costs")).json()["data"]
    assert data["total_calls"] == 3
    assert data["ok_calls"] == 2
    assert data["total_cost_usd"] == pytest.approx(0.08)
    by_org = {r["key"]: r for r in data["by_org"]}
    assert by_org["org-A"]["cost_usd"] == pytest.approx(0.06)
    assert by_org["org-A"]["calls"] == 2
    models = {r["key"] for r in data["by_model"]}
    assert {"gpt-4o", "gpt-4o-mini"} <= models


@pytest.mark.asyncio
async def test_tr_vertical_l3_endpoint_end_to_end(test_client, tmp_path, monkeypatch):
    """
    Register → give the org the TR pack → create an AnalysisJob pointing at a
    corpus CSV → POST /muhasebe/tr-vertical and verify the L3 autopilot result,
    then GET the board-deck PDF back.
    """
    from pathlib import Path

    from sqlalchemy import select

    from app.config import get_settings
    from app.models.analysis_job import AnalysisJob
    from app.models.organization import Organization
    from app.models.user import User, UserRole

    # keep the generated board-deck PDF out of the repo tree
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "smmm@buro.com", "password": "StrongPassword123!",
              "full_name": "SMMM"},
    )
    token = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "smmm@buro.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]

    csv_path = str(
        Path(__file__).parent / "fixtures" / "tr_corpus" / "technova_ocak_2024.csv"
    )

    async with test_client._test_sessionmaker() as db:
        user = (await db.execute(
            select(User).where(User.email == "smmm@buro.com")
        )).scalar_one()
        org = Organization(name="Büro A.Ş.", slug="buro-as", regional_packs=["tr"])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        user.role = UserRole.OWNER
        job = AnalysisJob(
            filename="technova_ocak_2024.csv",
            file_path=csv_path,
            file_type="csv",
            org_id=org.id,
            user_id=user.id,
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    resp = await test_client.post(
        "/api/v1/muhasebe/tr-vertical",
        json={"job_id": job_id, "company_name": "TechNova", "donem": "2024-01"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["meta"] == {"depth_level": 3, "auto_approved": False}
    data = body["data"]
    assert data["stage"] == "done"
    assert data["cfo"]["pnl"]["revenue"] == 39_200_000
    assert data["accounting"] is not None
    assert data["accounting"]["islem_sayisi"] == 12
    assert data["board_deck_pdf_size"] > 50
    assert isinstance(data["approval_required"], bool)

    # ── board-deck PDF is fetchable ─────────────────────────────────────────
    pdf_resp = await test_client.get(
        f"/api/v1/muhasebe/tr-vertical/{job_id}/board-deck.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert len(pdf_resp.content) > 50


@pytest.mark.asyncio
async def test_tr_vertical_board_deck_requires_tr_pack(test_client):
    """A GET for the board-deck PDF from an org without the TR pack is refused."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User, UserRole

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "noPack@buro.com", "password": "StrongPassword123!",
              "full_name": "No Pack"},
    )
    token = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "noPack@buro.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]

    async with test_client._test_sessionmaker() as db:
        user = (await db.execute(
            select(User).where(User.email == "noPack@buro.com")
        )).scalar_one()
        org = Organization(name="No Pack Ltd", slug="no-pack-ltd", regional_packs=[])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        user.role = UserRole.OWNER
        await db.commit()

    resp = await test_client.get(
        "/api/v1/muhasebe/tr-vertical/any-job-id/board-deck.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_connector_github_connect_sync_and_cto_flip(test_client, monkeypatch):
    """Faz 13: connect GitHub → sync → canonical rows → CTO kernel flips to `real`."""
    from datetime import UTC, datetime

    # Offline fake for the raw GitHub REST client.
    class _FakeCommit:
        def __init__(self, i: int):
            self.sha = f"sha{i:03d}"; self.message = "feat: ship"; self.author = "dev"
            self.date = datetime.now(UTC).isoformat(); self.files_changed = 3
            self.additions = 30; self.deletions = 5

    class _FakeData:
        error = None
        commits = [_FakeCommit(i) for i in range(8)]
        pull_requests = []
        issues = []

        def summary(self):
            return {"commits_fetched": len(self.commits)}

    class _FakeApi:
        def __init__(self, *a, **k): ...
        async def validate_token(self):
            return {"login": "octocat", "name": "Octo", "type": "User"}
        async def fetch(self, **k):
            return _FakeData()

    monkeypatch.setattr("app.services.github_connector.GitHubConnector", _FakeApi)

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "cto@startup.com", "password": "StrongPassword123!",
              "full_name": "CTO"},
    )
    token = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "cto@startup.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    from sqlalchemy import select as _select

    from app.models.organization import Organization
    from app.models.user import User, UserRole
    async with test_client._test_sessionmaker() as db:
        user = (await db.execute(
            _select(User).where(User.email == "cto@startup.com")
        )).scalar_one()
        org = Organization(name="Startup", slug="startup-co")
        db.add(org)
        await db.flush()
        user.org_id = org.id
        user.role = UserRole.OWNER
        await db.commit()

    # list — github present, not connected
    lst = (await test_client.get("/api/v1/connectors", headers=h)).json()["data"]["connectors"]
    gh = next(c for c in lst if c["name"] == "github")
    assert gh["connected"] is False and gh["kernel_role"] == "cto"

    # connect
    conn = await test_client.post(
        "/api/v1/connectors/github/connect", headers=h,
        json={"config": {"owner": "acme", "repo": "api"}, "secret": {"token": "ghp_x"}},
    )
    assert conn.status_code == 201, conn.text

    # sync → writes canonical rows and re-runs the CTO kernel
    sync = await test_client.post(
        "/api/v1/connectors/github/sync", headers=h, json={"run_kernel": True}
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()["data"]
    assert body["sync"]["ok"] is True
    assert body["sync"]["records_written"] == 8
    assert body["kernel"]["output"]["data_source"] == "real"
    assert body["kernel"]["provenance"]["synthetic"] is False

    # second sync is idempotent (still 8 rows)
    sync2 = await test_client.post(
        "/api/v1/connectors/github/sync", headers=h, json={"run_kernel": False}
    )
    assert sync2.json()["data"]["sync"]["ok"] is True

    from app.models.canonical_eng_signal import CanonicalEngSignal
    async with test_client._test_sessionmaker() as db:
        rows = (await db.execute(
            _select(CanonicalEngSignal).where(CanonicalEngSignal.source == "github")
        )).scalars().all()
    assert len(rows) == 8


@pytest.mark.asyncio
async def test_agent_run_ledger_records_tr_vertical_and_slo(test_client, tmp_path, monkeypatch):
    """Faz 14: running the TR vertical writes an AgentRun row surfaced by /runs + /runs/slo."""
    from pathlib import Path

    from sqlalchemy import select

    from app.config import get_settings
    from app.models.analysis_job import AnalysisJob
    from app.models.organization import Organization
    from app.models.user import User, UserRole

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "runs@buro.com", "password": "StrongPassword123!",
              "full_name": "R"},
    )
    token = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "runs@buro.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    csv_path = str(Path(__file__).parent / "fixtures" / "tr_corpus" / "technova_ocak_2024.csv")
    async with test_client._test_sessionmaker() as db:
        user = (await db.execute(
            select(User).where(User.email == "runs@buro.com")
        )).scalar_one()
        org = Organization(name="Runs Ltd", slug="runs-ltd", regional_packs=["tr"])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        user.role = UserRole.OWNER
        job = AnalysisJob(filename="a.csv", file_path=csv_path, file_type="csv",
                          org_id=org.id, user_id=user.id)
        db.add(job)
        await db.commit()
        job_id = job.id

    resp = await test_client.post(
        "/api/v1/muhasebe/tr-vertical",
        json={"job_id": job_id, "company_name": "TechNova", "donem": "2024-01"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text

    runs = (await test_client.get("/api/v1/runs", headers=h)).json()["data"]["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run["pipeline"] == "tr_vertical"
    assert run["status"] in {"completed", "awaiting_review"}
    assert run["latency_ms"] is not None
    assert "done" in (run["node_history"] or [])

    slo = (await test_client.get("/api/v1/runs/slo?days=1", headers=h)).json()["data"]
    assert slo["total_runs"] == 1
    tv = slo["by_pipeline"]["tr_vertical"]
    assert tv["runs"] == 1
    assert tv["p50_latency_ms"] is not None

    one = (await test_client.get(f"/api/v1/runs/{run['id']}", headers=h)).json()["data"]
    assert one["id"] == run["id"]


@pytest.mark.asyncio
async def test_smmm_defensibility_packet_build_and_export(test_client):
    """#4: build a defensibility packet from a persisted journal, then export it."""
    from sqlalchemy import select

    from app.models.analysis_job import AnalysisJob
    from app.models.organization import Organization
    from app.models.report import Report, ReportFormat
    from app.models.user import User, UserRole

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "smmm2@buro.com", "password": "StrongPassword123!",
              "full_name": "SM"},
    )
    token = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "smmm2@buro.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    async with test_client._test_sessionmaker() as db:
        user = (await db.execute(
            select(User).where(User.email == "smmm2@buro.com")
        )).scalar_one()
        org = Organization(name="Def Ltd", slug="def-ltd", regional_packs=["tr"])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        user.role = UserRole.OWNER
        job = AnalysisJob(filename="j.csv", file_path="/x.csv", file_type="csv",
                          org_id=org.id, user_id=user.id)
        db.add(job)
        await db.flush()
        job_id = job.id
        db.add(Report(
            job_id=job_id, report_type="tr_muhasebe_journal",
            report_format=ReportFormat.JSON,
            data={
                "dengeli": True, "denge_hatalari": [], "ortalama_confidence": 0.9,
                "thp_dagilim": {"770": 1},
                "yevmiye_kayitlari": [{
                    "kayit_id": "k1", "tarih": "2024-01-10T00:00:00+00:00",
                    "aciklama": "kira gideri", "toplam_borc": 120000, "toplam_alacak": 120000,
                    "dengeli": True, "confidence": 0.95, "onay_gerekli": False,
                    "onay_neden": "", "thp_hesap_kodu": "770", "kaynak_islem_id": "tx1",
                    "satirlar": [],
                }],
            },
        ))
        await db.commit()

    built = await test_client.post(
        f"/api/v1/smmm/defensibility/{job_id}/build?period=2024-01", headers=h
    )
    assert built.status_code == 201, built.text
    pid = built.json()["data"]["id"]
    assert built.json()["data"]["summary"]["ai_auto_posted"] == 1
    assert built.json()["data"]["summary"]["pending_review"] == 0

    full = (await test_client.get(f"/api/v1/smmm/defensibility/{pid}", headers=h)).json()["data"]
    assert full["payload"]["entries"][0]["decision_source"] == "ai_auto_posted"

    fin = await test_client.post(
        f"/api/v1/smmm/defensibility/{pid}/finalize", headers=h,
        json={"statement": "2024/01 kayıtlarını inceledim, uygundur. SM. Test"},
    )
    assert fin.status_code == 200, fin.text
    assert fin.json()["data"]["status"] == "finalized"

    exp = await test_client.get(f"/api/v1/smmm/defensibility/{pid}/export", headers=h)
    assert exp.status_code == 200
    assert exp.headers["content-type"].split(";")[0] in ("application/pdf", "text/plain")
    assert len(exp.content) > 50

    # regenerating a finalized packet is refused
    again = await test_client.post(
        f"/api/v1/smmm/defensibility/{job_id}/build?period=2024-01", headers=h
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_authority_matrix_policy_lifecycle(test_client):
    """Yetki Matrisi: default → owner edits → versioned → dry-run evaluate."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User, UserRole

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "owner@firma.com", "password": "StrongPassword123!",
              "full_name": "Patron"},
    )
    otok = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@firma.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    oh = {"Authorization": f"Bearer {otok}"}

    async with test_client._test_sessionmaker() as db:
        u = (await db.execute(select(User).where(User.email == "owner@firma.com"))).scalar_one()
        org = Organization(name="Firma", slug="firma")
        db.add(org)
        await db.flush()
        u.org_id = org.id
        u.role = UserRole.OWNER
        await db.commit()

    # default policy
    d = (await test_client.get("/api/v1/authority/policy", headers=oh)).json()["data"]
    assert d["is_default"] is True and d["version"] == 0
    assert any(r["id"] == "high_value" for r in d["rules"])

    # owner installs a custom matrix
    new_rules = [
        {"id": "small", "domain": "spending", "when": {"amount_kurus_lt": 5_000_000},
         "decision": "auto_approve", "note": "₺50k altı serbest"},
        {"id": "big", "domain": "spending", "when": {"amount_kurus_gte": 5_000_000},
         "decision": "require_approvals",
         "approvals": [{"role": "finance_manager", "count": 1}, {"role": "owner", "count": 1}],
         "note": "₺50k üzeri"},
        {"id": "catch", "domain": "*", "when": {}, "decision": "auto_approve", "note": "-"},
    ]
    put = await test_client.put("/api/v1/authority/policy", headers=oh,
                                json={"rules": new_rules, "note": "ilk sürüm"})
    assert put.status_code == 200, put.text
    assert put.json()["data"]["version"] == 1

    d2 = (await test_client.get("/api/v1/authority/policy", headers=oh)).json()["data"]
    assert d2["is_default"] is False and d2["version"] == 1

    # dry-run: ₺80k spending → needs finance + owner
    ev = (await test_client.post(
        "/api/v1/authority/evaluate", headers=oh,
        json={"domain": "spending", "amount_kurus": 8_000_000},
    )).json()["data"]
    assert ev["outcome"] == "needs_approval"
    assert [a["role"] for a in ev["required_approvals"]] == ["finance_manager", "owner"]

    # invalid policy is rejected
    bad = await test_client.put("/api/v1/authority/policy", headers=oh,
                                json={"rules": [{"id": "x", "decision": "nope", "when": {}, "domain": "*"}]})
    assert bad.status_code == 422

    vers = (await test_client.get("/api/v1/authority/policy/versions", headers=oh)).json()["data"]
    assert len(vers["versions"]) == 1 and vers["versions"][0]["active"] is True


@pytest.mark.asyncio
async def test_authority_matrix_put_requires_owner(test_client):
    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "staff@firma.com", "password": "StrongPassword123!",
              "full_name": "Personel"},
    )
    tok = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "staff@firma.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    resp = await test_client.put(
        "/api/v1/authority/policy",
        headers={"Authorization": f"Bearer {tok}"},
        json={"rules": [{"id": "c", "domain": "*", "when": {}, "decision": "auto_approve"}]},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_institutionalization_index_compute_and_history(test_client):
    """Kurumsallaşma Endeksi: compute stores a snapshot; history returns the trend."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User, UserRole

    await test_client.post(
        "/api/v1/auth/register",
        json={"email": "idx@firma.com", "password": "StrongPassword123!",
              "full_name": "Idx"},
    )
    tok = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "idx@firma.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    async with test_client._test_sessionmaker() as db:
        u = (await db.execute(select(User).where(User.email == "idx@firma.com"))).scalar_one()
        org = Organization(name="Idx Ltd", slug="idx-ltd")
        db.add(org)
        await db.flush()
        u.org_id = org.id
        u.role = UserRole.OWNER
        await db.commit()

    # GET with no prior snapshot computes one
    first = (await test_client.get("/api/v1/institutionalization", headers=h)).json()["data"]
    assert 0 <= first["overall_score"] <= 100
    assert first["grade"] in {"A", "B", "C", "D", "E"}
    assert len(first["dimensions"]) == 6
    assert "recommendations" in first

    # explicit compute stores another
    comp = await test_client.post("/api/v1/institutionalization/compute", headers=h)
    assert comp.status_code == 201

    hist = (await test_client.get("/api/v1/institutionalization/history", headers=h)).json()["data"]
    assert len(hist["points"]) >= 2
    assert all("overall_score" in p for p in hist["points"])


@pytest.mark.asyncio
async def test_system_ops_handles_naive_db_timestamps(test_client):
    """Regression: /system/ops 500'd once a pending job existed.

    SQLite returns naive datetimes for DateTime(timezone=True) columns, so
    `datetime.now(UTC) - row.updated_at` raised TypeError. It only surfaced with
    rows present, which is why an empty-DB smoke test passed. See
    app/core/timeutil.as_utc.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.analysis_job import AnalysisJob

    async with test_client._test_sessionmaker() as db:
        old = datetime.now(UTC) - timedelta(hours=6)
        db.add(AnalysisJob(
            filename="pending.csv", file_path="/x.csv", file_type="csv",
            status="pending", created_at=old, updated_at=old,
        ))
        db.add(AnalysisJob(
            filename="done.csv", file_path="/y.csv", file_type="csv",
            status="completed", created_at=old,
            completed_at=old + timedelta(minutes=3), updated_at=old,
        ))
        await db.commit()

    resp = await test_client.get("/api/v1/system/ops")
    assert resp.status_code == 200, resp.text
    sla = resp.json()["data"]["sla"]
    # the 6h-old pending job must be reported as an SLA breach, not crash
    assert any(b["status"] == "pending" for b in sla["breaches"]), sla["breaches"]
    assert sla["job_completion_p95_ms"] is not None


@pytest.mark.asyncio
async def test_api_key_survives_a_warm_user_cache(test_client):
    """Rotate the key on a *second* request, when the cached user is detached.

    `get_current_user` serves users from a 60-second cache, so the first request
    of a session gets a live ORM instance and every later one gets a detached
    copy. Endpoints that wrote to `current_user` therefore worked exactly once
    per minute and then silently stopped committing. The existing key test never
    saw it: one request per test, always a cold cache.
    """
    await test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "warm.cache@company.com",
            "password": "StrongPassword123!",
            "full_name": "Warm Cache",
        },
    )
    token = (await test_client.post(
        "/api/v1/auth/login",
        json={"email": "warm.cache@company.com", "password": "StrongPassword123!"},
    )).json()["data"]["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # First authenticated call fills the cache.
    assert (await test_client.get("/api/v1/auth/me", headers=auth)).status_code == 200

    # Second one is served from it — this is where the write used to vanish.
    key_resp = await test_client.post("/api/v1/auth/api-key", headers=auth)
    assert key_resp.status_code == 200
    api_key = key_resp.json()["data"]["api_key"]

    me = await test_client.get("/api/v1/auth/me", headers={"X-API-Key": api_key})
    assert me.status_code == 200, "the rotated key was never committed"
    assert me.json()["data"]["email"] == "warm.cache@company.com"

    # Revoking has to stick too.
    assert (await test_client.delete("/api/v1/auth/api-key", headers=auth)).status_code == 200
    revoked = await test_client.get("/api/v1/auth/me", headers={"X-API-Key": api_key})
    assert revoked.status_code == 401, "the revoked key still authenticates"
