"""Karar Defteri — karar bir kez yazılır, sonuç dürüst ölçülür. (P2)

The closed loop, pinned:

  1. `POST /decisions` snapshots the PACKET'S numbers into `expected` —
     server-side, regardless of whatever the caller tries to send;
  2. `POST /decisions/{id}/outcome` measures what happened AFTER the
     decision (business dates > decided_at, newest finished analysis)
     and closes the row — a second measurement is refused (409);
  3. the packet's "Geçmişte ne oldu?" now leads with the ledger.

Contract edges: mid-run → 409, no report → 422, unknown option → 422,
other tenants → 404, no measurable data yet → 409.

No LLM and no API key is needed anywhere in this file.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    """In-memory FastAPI client + clean schema (mirrors test_decision_packet)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _user(client, email: str) -> tuple[dict[str, str], str, str]:
    """Register → attach a fresh org (mirrors test_decision_packet)."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "T"},
    )
    async with client._maker() as db:  # type: ignore[attr-defined]
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        org = Organization(name=email, slug=email.split("@")[0])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        await db.commit()
        org_id, user_id = org.id, user.id
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123!"},
        )
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


async def _seed_job(
    client,
    org_id: str,
    *,
    status: str = "awaiting_review",
    runway: float = 9.5,
    with_report: bool = True,
    txn_days: tuple[tuple[int, str, int], ...] = (),
):
    """Job + (optional) full report + back-dated transactions.

    `txn_days` entries are (days_ago, type, amount_kurus).
    """
    from datetime import UTC, datetime, timedelta

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat, ReportType
    from app.models.transaction import Transaction

    awaiting = status == "awaiting_review"
    async with client._maker() as db:  # type: ignore[attr-defined]
        job = AnalysisJob(
            filename="m.csv",
            file_path="/m.csv",
            file_type="csv",
            org_id=org_id,
            status=JobStatus(status),
            awaiting_review=awaiting,
            min_confidence=0.6 if awaiting else None,
        )
        db.add(job)
        await db.flush()

        if with_report:
            db.add(
                Report(
                    job_id=job.id,
                    report_type=ReportType.FULL,
                    report_format=ReportFormat.JSON,
                    data={
                        "pnl": {
                            "revenue": 12_000_000_00,
                            "total_opex": 8_000_000_00,
                            "net_margin": 0.2,
                            "opex": {"salary": 4_000_000_00, "rent": 1_000_000_00},
                        },
                        "cashflow": {"net_change": 500_000_00},
                        "forecast": {
                            "scenarios": {
                                "base": {
                                    "runway_months": runway,
                                    "twelve_month_net": 3_000_000_00,
                                }
                            }
                        },
                    },
                )
            )
        for days_ago, tx_type, amount in txn_days:
            db.add(
                Transaction(
                    job_id=job.id,
                    amount_kurus=amount,
                    currency="TRY",
                    type=tx_type,
                    category="rent" if tx_type == "expense" else "revenue",
                    description="seed",
                    transaction_date=datetime.now(UTC) - timedelta(days=days_ago),
                )
            )
        await db.commit()
        return job.id


async def _record(client, headers, job_id: str, **overrides) -> dict:
    body = {"job_id": job_id, "option_id": "baseline"}
    body.update(overrides)
    r = await client.post("/api/v1/decisions", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── 1. Beklenti sunucu tarafında paketten dolar ──────────────────────────────

async def test_record_snapshots_packet_numbers_server_side(client):
    headers, org_id, user_id = await _user(client, "kayit@example.com")
    job_id = await _seed_job(client, org_id)

    packet = (
        await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    ).json()["data"]
    preset = next(o for o in packet["options"] if not o["baseline"])

    r = await client.post(
        "/api/v1/decisions",
        json={
            "job_id": job_id,
            "option_id": preset["id"],
            "topic": "Bütçe kesintisi",
            "rationale": "Nakit ömrü kısalıyor",
            # Even a smuggled "expected" must not win over the packet's.
            "expected": {"runway_months": 999},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]

    assert d["status"] == "open"
    assert d["topic"] == "Bütçe kesintisi"
    assert d["rationale"] == "Nakit ömrü kısalıyor"
    assert d["created_by"] == user_id
    assert d["actual"] is None and d["variance"] is None

    exp = d["expected"]
    assert exp["runway_months"] == 9.5          # packet's number, NOT 999
    assert exp["forecast_12m_net"] == 3_000_000_00
    assert exp["revenue_12m"] == 12_000_000_00
    assert exp["option_id"] == preset["id"]
    assert exp["option_label"] == preset["label"]
    assert exp["option_net_impact"] == preset["base_net_impact"]
    assert exp["generated_at"]


async def test_record_defaults_topic_to_the_option(client):
    headers, org_id, _ = await _user(client, "konu@example.com")
    job_id = await _seed_job(client, org_id)
    d = await _record(client, headers, job_id)
    assert d["topic"].startswith("Karar:")
    assert d["rationale"] is None


# ── Sözleşme kenarları ───────────────────────────────────────────────────────

async def test_record_running_job_is_409(client):
    headers, org_id, _ = await _user(client, "calisiyor@example.com")
    job_id = await _seed_job(client, org_id, status="analyzing")
    r = await client.post(
        "/api/v1/decisions",
        json={"job_id": job_id, "option_id": "baseline"},
        headers=headers,
    )
    assert r.status_code == 409


async def test_record_other_tenants_job_is_404(client):
    _h_a, org_a, _ = await _user(client, "sahip@example.com")
    headers_b, _org_b, _ = await _user(client, "yabanci@example.com")
    job_id = await _seed_job(client, org_a)
    r = await client.post(
        "/api/v1/decisions",
        json={"job_id": job_id, "option_id": "baseline"},
        headers=headers_b,
    )
    assert r.status_code == 404


async def test_record_without_report_is_422(client):
    headers, org_id, _ = await _user(client, "raporsuz@example.com")
    job_id = await _seed_job(client, org_id, with_report=False)
    r = await client.post(
        "/api/v1/decisions",
        json={"job_id": job_id, "option_id": "baseline"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "rapor" in r.json()["error"]


async def test_record_unknown_option_is_422(client):
    headers, org_id, _ = await _user(client, "yoksecenek@example.com")
    job_id = await _seed_job(client, org_id)
    r = await client.post(
        "/api/v1/decisions",
        json={"job_id": job_id, "option_id": "preset_99"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "seçenek" in r.json()["error"]


# ── 2. Defter: liste tenant'ına göre ─────────────────────────────────────────

async def test_list_is_tenant_scoped_and_filterable(client):
    headers_a, org_a, _ = await _user(client, "defter-a@example.com")
    headers_b, _org_b, _ = await _user(client, "defter-b@example.com")
    job_a1 = await _seed_job(client, org_a)
    job_a2 = await _seed_job(client, org_a, status="completed")

    open_d = await _record(client, headers_a, job_a1)
    closed_d = await _record(client, headers_a, job_a2)
    r = await client.post(
        f"/api/v1/decisions/{closed_d['id']}/outcome", json={}, headers=headers_a
    )
    assert r.status_code == 200, r.text

    # Own org, newest first: the just-closed row leads.
    mine = (await client.get("/api/v1/decisions", headers=headers_a)).json()["data"]
    assert [d["id"] for d in mine] == [closed_d["id"], open_d["id"]]

    only_open = (
        await client.get("/api/v1/decisions", params={"status": "open"},
                         headers=headers_a)
    ).json()["data"]
    assert [d["id"] for d in only_open] == [open_d["id"]]

    by_job = (
        await client.get("/api/v1/decisions", params={"job_id": job_a1},
                         headers=headers_a)
    ).json()["data"]
    assert [d["id"] for d in by_job] == [open_d["id"]]

    # Another organisation sees nothing of this ledger.
    theirs = (await client.get("/api/v1/decisions", headers=headers_b)).json()["data"]
    assert theirs == []


# ── 3. Sonuç döngüsü: karardan sonra gelen veri ölçülür ──────────────────────

async def test_outcome_measures_only_what_happened_after_the_decision(client):
    from datetime import UTC, datetime, timedelta

    from app.models.decision_log import DecisionLog

    headers, org_id, _ = await _user(client, "sonuc@example.com")
    job1 = await _seed_job(client, org_id)              # decision job: runway 9.5
    decision = await _record(client, headers, job1, option_id="baseline")

    # Newer finished analysis arrives with fresh numbers: runway 11,
    # income 500k TL + expense 200k TL in the last day (both after the
    # decision), plus a 5-days-old income that must NOT count.
    job2 = await _seed_job(
        client,
        org_id,
        status="completed",
        runway=11.0,
        txn_days=(
            (1, "income", 500_000_00),
            (1, "expense", 200_000_00),
            (5, "income", 1_000_000_00),
        ),
    )
    assert job2 != job1

    # Backdate the decision to two days ago so "after" has a boundary.
    async with client._maker() as db:  # type: ignore[attr-defined]
        row = await db.get(DecisionLog, decision["id"])
        row.created_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()

    r = await client.post(
        f"/api/v1/decisions/{decision['id']}/outcome",
        json={"note": "İlk ay sonucu"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]

    assert d["status"] == "closed"
    assert d["measured_at"] is not None
    assert d["outcome_note"] == "İlk ay sonucu"

    actual = d["actual"]
    assert actual["realized_net_kurus"] == 300_000_00   # +500k −200k TL
    assert actual["transactions_since"] == 2            # 5-day-old row excluded
    assert actual["runway_months_latest"] == 11.0
    assert actual["data_job_id"] == job2                # newest finished analysis

    variance = d["variance"]
    assert variance["realized_net_kurus"] == 300_000_00
    assert variance["runway_delta"] == 1.5              # 11 − 9.5


async def test_outcome_twice_is_409(client):
    headers, org_id, _ = await _user(client, "tekrar@example.com")
    job_id = await _seed_job(client, org_id)
    decision = await _record(client, headers, job_id)

    first = await client.post(
        f"/api/v1/decisions/{decision['id']}/outcome", json={}, headers=headers
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/decisions/{decision['id']}/outcome", json={}, headers=headers
    )
    assert second.status_code == 409
    assert "ölçülmüş" in second.json()["error"]

    # The first reading stands — unchanged by the refused second call.
    after = (
        await client.get(f"/api/v1/decisions/{decision['id']}", headers=headers)
    ).json()["data"]
    assert after["actual"] == first.json()["data"]["actual"]


async def test_outcome_other_tenant_is_404(client):
    headers_a, org_a, _ = await _user(client, "onayli-a@example.com")
    headers_b, _org_b, _ = await _user(client, "onayli-b@example.com")
    job_id = await _seed_job(client, org_a)
    decision = await _record(client, headers_a, job_id)

    r = await client.post(
        f"/api/v1/decisions/{decision['id']}/outcome", json={}, headers=headers_b
    )
    assert r.status_code == 404
    r2 = await client.get(
        f"/api/v1/decisions/{decision['id']}", headers=headers_b
    )
    assert r2.status_code == 404


async def test_outcome_without_measurable_data_is_409(client):
    """Honest refusal: nothing finished to measure against yet."""
    from app.models.analysis_job import AnalysisJob, JobStatus

    headers, org_id, _ = await _user(client, "veriyok@example.com")
    job_id = await _seed_job(client, org_id)
    decision = await _record(client, headers, job_id)

    # The analysis fails after the decision — no finished job remains.
    async with client._maker() as db:  # type: ignore[attr-defined]
        job = await db.get(AnalysisJob, job_id)
        job.status = JobStatus.FAILED
        await db.commit()

    r = await client.post(
        f"/api/v1/decisions/{decision['id']}/outcome", json={}, headers=headers
    )
    assert r.status_code == 409
    assert "tamamlanmış analiz" in r.json()["error"]


# ── 4. Paket emsali artık defteri başında taşır ──────────────────────────────

async def test_packet_precedent_leads_with_the_ledger(client):
    headers, org_id, _ = await _user(client, "emsal@example.com")
    job_id = await _seed_job(client, org_id)
    packet_before = (
        await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    ).json()["data"]
    assert packet_before["precedent"]["decisions"] == []

    preset = next(o for o in packet_before["options"] if not o["baseline"])
    decision = await _record(client, headers, job_id, option_id=preset["id"])
    await client.post(
        f"/api/v1/decisions/{decision['id']}/outcome", json={}, headers=headers
    )

    packet_after = (
        await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    ).json()["data"]
    decisions = packet_after["precedent"]["decisions"]
    assert len(decisions) == 1
    lead = decisions[0]
    assert lead["id"] == decision["id"]
    assert lead["topic"] == decision["topic"]
    assert lead["final_decision"] == preset["label"]
    assert lead["resolution_status"] == "closed"
    assert lead["confidence_score"] is None   # the ledger never computed one
    assert lead["created_at"]
