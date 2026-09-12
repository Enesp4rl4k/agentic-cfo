"""Her rota ya kimlik ister ya da neden istemediğini söyler.

Before `app/api/access.py`, 62 routes took no user and 50 more loaded objects by
id without asking whose they were — report downloads, transaction detail, the
SMMM approve/correct/reject writes, the morning brief built from every
organisation's jobs, a CEO route that read any file path from its body. None
of it was visible to a test, because no test asked the question of *every*
route. This one does.

Two layers:

1. Structural, over the registry: every route authenticates or is in
   `PUBLIC_ROUTES` with a reason; every route that takes a `{job_id}` resolves
   it through `owned_job` (or a signed stream ticket); every route that takes
   another object id is either checked through the access module or listed in
   `SCOPED_IN_HANDLER` below with the reason it is safe. A new route that does
   none of these fails here, naming itself.

2. Behavioural, over HTTP: two organisations, and the second one's requests for
   the first one's objects come back 404 — reads and writes both.
"""
from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.access import PUBLIC_ROUTES
from app.database import Base, get_db
from app.main import app

AUTH_DEPENDENCIES = {"get_current_user", "require_tr_pack", "stream_ticket_user"}
JOB_DEPENDENCIES = {"owned_job", "stream_ticket_user"}
BODY_CHECKS = ("load_owned_job(", "_edefter_context(", "_edefter_build(", "_check_job_access(")
ID_CHECKS = (*BODY_CHECKS, "ensure_tenant(", "can_access(", "current_user_org_matches(", "_load_owned(", "_resolve_org_id(")

# Routes that take an id and scope it inside the handler without this module.
# Each was read; the reason is what makes it safe. Adding a line here is a
# review decision, not a way to make the test pass.
SCOPED_IN_HANDLER: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/auth/sso/{provider}/login"): "provider is a name from a fixed list, not an object",
    ("GET", "/api/v1/auth/sso/{provider}/callback"): "provider name; the callback verifies OAuth state",
    ("POST", "/api/v1/open-banking/connect/{bank_id}"): "bank id is a key into a static table",
    ("POST", "/api/v1/open-banking/connections/{connection_id}/sync"): "id unused; the new job is created in the caller's org",
    ("GET", "/api/v1/efatura/invoices/{direction}"): "inbound|outbound, not an object",
    ("GET", "/api/v1/efatura/tax-calendar/{period}"): "a YYYY-MM period, not an object",
    ("GET", "/api/v1/billing/check-limit/{resource}"): "resource name; usage read for the caller's org",
    ("GET", "/api/v1/temporal/history/{agent}"): "agent name; history read for the caller's org (400 without one)",
    ("POST", "/api/v1/connectors/{name}/connect"): "connector type; the connection row is the caller's org",
    ("POST", "/api/v1/connectors/{name}/sync"): "connector type; synced for the caller's org",
    ("GET", "/api/v1/connectors/{name}/status"): "connector type; queried by the caller's org",
    ("DELETE", "/api/v1/connectors/{name}"): "connector type; queried by the caller's org",
    ("POST", "/api/v1/agent-jobs/{agent_type}"): "agent type; the job is created in the caller's org",
    ("GET", "/api/v1/agent-jobs/list/{agent_type}"): "agent type; listed by the caller's org",
    ("GET", "/api/v1/agent-jobs/{job_id}"): "an AgentJob, not an AnalysisJob; 404 unless job.org_id == caller's (org required)",
    ("DELETE", "/api/v1/agent-jobs/{job_id}"): "an AgentJob; 404 unless job.org_id == caller's (org required)",
    ("PATCH", "/api/v1/notifications/{notification_id}/read"): "404 unless notif.org_id == caller's (org required)",
    ("DELETE", "/api/v1/notifications/{notification_id}"): "404 unless notif.org_id == caller's (org required)",
    ("PATCH", "/api/v1/related-parties/{party_id}"): "404 unless party.org_id == caller's manager org",
    ("DELETE", "/api/v1/related-parties/{party_id}"): "404 unless party.org_id == caller's manager org",
    ("GET", "/api/v1/erp/integrations/{integration_id}"): "selected WHERE id AND org_id == caller's",
    ("DELETE", "/api/v1/erp/integrations/{integration_id}"): "selected WHERE id AND org_id == caller's",
    ("PUT", "/api/v1/smmm/clients/{client_id}"): "selected WHERE id AND muhasebeci == caller's SMMM record",
    ("DELETE", "/api/v1/smmm/clients/{client_id}"): "selected WHERE id AND muhasebeci == caller's SMMM record",
    ("DELETE", "/api/v1/chat/sessions/{session_id}"): "session store is keyed by the caller's user id",
    ("GET", "/api/v1/chat/sessions/{session_id}/history"): "session store is keyed by the caller's user id",
    ("DELETE", "/api/v1/pilot/invite/{invite_id}"): "admin-only; pilot invites are platform-wide, not tenant data",
    ("POST", "/api/v1/alerts/acknowledge/{job_id}/{alert_fingerprint}"): "job resolved by owned_job; fingerprint is a hash",
    ("GET", "/api/v1/benchmark/{job_id}/metric/{metric}"): "job resolved by owned_job; metric is a name",
    ("POST", "/api/v1/datasource/{job_id}/{domain}/{source_type}"): "job resolved by owned_job; domain/type are names",
    ("DELETE", "/api/v1/datasource/{job_id}/{source_id}"): "job resolved by owned_job; source selected WHERE job_id",
    ("GET", "/api/v1/context/{org_id}/agent/{agent}"): "org resolved by _resolve_org_id; agent is a name",
    ("GET", "/api/v1/dashboard/{job_id}"): "job checked by load_owned_job in the handler",
    ("GET", "/api/v1/ceo/status/{job_id}"): "a Redis CEO job id; refused unless its recorded owner passes can_access",
    ("GET", "/api/v1/agent-graph/job/{job_id}"): "job loaded, then treated as missing unless can_access",
    ("DELETE", "/api/v1/org/members/{user_id}"): "admin of the caller's org; 404 unless target.org_id == that org",
    ("DELETE", "/api/v1/org/invites/{invite_id}"): "admin; selected WHERE id AND org_id == caller's org",
    ("PUT", "/api/v1/sync/schedules/{schedule_id}"): "404 unless row.org_id == caller's org (or user id)",
    ("DELETE", "/api/v1/sync/schedules/{schedule_id}"): "404 unless row.org_id == caller's org (or user id)",
    ("POST", "/api/v1/sync/schedules/{schedule_id}/run"): "404 unless row.org_id == caller's org (or user id)",
}


def _flat(routes):
    """Every endpoint route, across FastAPI versions (0.141 wraps included routers)."""
    for r in routes:
        if hasattr(r, "effective_candidates"):
            yield from _flat(r.effective_candidates())
        elif hasattr(r, "endpoint") and hasattr(r, "methods") and getattr(r, "path", ""):
            yield r


def _deps(route) -> set[str]:
    dependant = getattr(route, "dependant", None) or getattr(
        getattr(route, "original_route", None), "dependant", None
    )
    out: set[str] = set()

    def walk(d):
        for sub in d.dependencies:
            out.add(getattr(sub.call, "__name__", ""))
            walk(sub)

    if dependant is not None:
        walk(dependant)
    return out


def _source(route) -> str:
    try:
        return inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return ""


def _routes():
    seen = set()
    for r in _flat(app.routes):
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            key = (method, r.path)
            if key not in seen:
                seen.add(key)
                yield key, r


ROUTES = list(_routes())


def test_the_registry_is_actually_walked() -> None:
    """If the walk silently finds nothing, every assertion below passes."""
    assert len(ROUTES) > 300


def test_every_route_authenticates_or_says_why_not() -> None:
    offenders = [
        f"{m} {p}" for (m, p), r in ROUTES
        if (m, p) not in PUBLIC_ROUTES and not (_deps(r) & AUTH_DEPENDENCIES)
        and "require_role" not in _source(r)
    ]
    assert not offenders, (
        "kimlik doğrulamasız rota — ya Depends(get_current_user) ekleyin ya da "
        "app/api/access.py PUBLIC_ROUTES'a gerekçesiyle yazın:\n  " + "\n  ".join(offenders)
    )


def test_public_routes_all_exist() -> None:
    """A stale allow-list entry is a hole waiting for a route to fill it."""
    keys = {k for k, _ in ROUTES}
    assert not [k for k in PUBLIC_ROUTES if k not in keys]


def test_every_job_route_resolves_ownership() -> None:
    offenders = []
    for (m, p), r in ROUTES:
        if "{job_id}" not in p or (m, p) in SCOPED_IN_HANDLER:
            continue
        if _deps(r) & JOB_DEPENDENCIES:
            continue
        if any(c in _source(r) for c in BODY_CHECKS):
            continue
        offenders.append(f"{m} {p}")
    assert not offenders, (
        "{job_id} alan rota işin sahibini sormuyor — job: AnalysisJob = "
        "Depends(owned_job) kullanın:\n  " + "\n  ".join(offenders)
    )


def test_every_other_object_id_is_scoped() -> None:
    offenders = []
    for (m, p), r in ROUTES:
        params = set(re.findall(r"\{(\w+)\}", p)) - {"job_id"}
        if not params or (m, p) in SCOPED_IN_HANDLER or (m, p) in PUBLIC_ROUTES:
            continue
        if any(c in _source(r) for c in ID_CHECKS) or (_deps(r) & JOB_DEPENDENCIES and params <= set()):
            continue
        offenders.append(f"{m} {p}")
    assert not offenders, (
        "nesne kimliği alan rota erişim modülünden geçmiyor — ensure_tenant / "
        "current_user_org_matches kullanın ya da SCOPED_IN_HANDLER'a gerekçesiyle "
        "ekleyin:\n  " + "\n  ".join(offenders)
    )


def test_scoped_in_handler_entries_all_exist() -> None:
    keys = {k for k, _ in ROUTES}
    assert not [k for k in SCOPED_IN_HANDLER if k not in keys]


def test_no_route_trusts_a_role_across_organisations() -> None:
    """`owner` and `admin` are roles inside one organisation."""
    import pathlib

    api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    hits = [
        f.name for f in api.glob("*.py")
        if re.search(r"org_id\s*!=.*\n?.*role not in \(\s*\"admin\",\s*\"owner\"\s*\)", f.read_text(encoding="utf-8"))
    ]
    assert not hits


# ── Behaviour, over HTTP ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c._maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _member(client, email: str, *, org: bool = True):
    from app.models.organization import Organization
    from app.models.user import User

    pw = "StrongPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pw, "full_name": "T"})
    org_id = None
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        if org:
            o = Organization(name=email, slug=email.split("@")[0], regional_packs=["tr"])
            db.add(o)
            await db.flush()
            user.org_id = o.id
            org_id = o.id
        user.role = "owner"
        await db.commit()
        user_id = user.id
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": pw})).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


async def _seed(client, org_id: str, user_id: str) -> dict[str, str]:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.anomaly import Anomaly
    from app.models.report import Report, ReportFormat
    from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
    from app.models.transaction import Transaction

    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org_id, user_id=user_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        tx = Transaction(job_id=job.id, amount_kurus=1000, currency="TRY", type="expense",
                         category="rent", description="kira",
                         transaction_date=datetime(2024, 1, 5, tzinfo=UTC))
        rep = Report(job_id=job.id, report_type="dashboard", report_format=ReportFormat.JSON,
                     data={"pnl": {"revenue": 100}})
        onay = SMMMOnayKaydi(job_id=job.id, org_id=org_id, kayit_id="k1", orijinal_kayit={"satirlar": []},
                             durum=OnayDurumu.BEKLIYOR)
        anomaly = Anomaly(job_id=job.id, anomaly_type="spike", severity="high",
                          title="t", description="d")
        db.add_all([tx, rep, onay, anomaly])
        await db.commit()
        return {"job": job.id, "tx": tx.id, "report": rep.id, "onay": onay.id, "anomaly": anomaly.id}


@pytest.mark.asyncio
async def test_another_organisation_gets_404_for_reads_and_writes(client) -> None:
    _owner_h, org_a, user_a = await _member(client, "a@example.com")
    ids = await _seed(client, org_a, user_a)
    stranger, _org_b, _ = await _member(client, "b@example.com")

    attempts = [
        ("GET", f"/api/v1/analysis/{ids['job']}", None),
        ("GET", f"/api/v1/analysis/{ids['job']}/transactions", None),
        ("GET", f"/api/v1/dashboard/{ids['job']}", None),
        ("GET", f"/api/v1/reports/{ids['job']}", None),
        ("GET", f"/api/v1/transactions/{ids['tx']}", None),
        ("PATCH", f"/api/v1/transactions/{ids['tx']}/category", {"category": "salary"}),
        ("PATCH", f"/api/v1/anomalies/{ids['anomaly']}/acknowledge", {"acknowledged": True}),
        ("GET", f"/api/v1/muhasebe/mizan/{ids['job']}", None),
        ("GET", f"/api/v1/smmm/onay/queue/{ids['job']}", None),
        ("POST", f"/api/v1/smmm/onay/{ids['onay']}/onayla", {}),
        ("POST", f"/api/v1/smmm/onay/{ids['onay']}/reddet", {"neden": "x"}),
        ("POST", f"/api/v1/muhasebe/onayla/{ids['onay']}", {}),
        ("POST", f"/api/v1/stream/{ids['job']}/ticket", None),
        ("POST", "/api/v1/query", {"query": "nakit", "job_id": ids["job"]}),
    ]
    wrong = []
    for method, url, body in attempts:
        resp = await client.request(method, url, headers=stranger, json=body)
        if resp.status_code != 404:
            wrong.append(f"{method} {url} -> {resp.status_code}")
    assert not wrong, "başka organizasyonun nesnesine erişilebildi:\n  " + "\n  ".join(wrong)

    # And the writes did not land.
    from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
    from app.models.transaction import Transaction

    async with client._maker() as db:
        assert (await db.get(SMMMOnayKaydi, ids["onay"])).durum == OnayDurumu.BEKLIYOR
        assert (await db.get(Transaction, ids["tx"])).category == "rent"


@pytest.mark.asyncio
async def test_the_owner_still_gets_in(client) -> None:
    owner, org_a, user_a = await _member(client, "own@example.com")
    ids = await _seed(client, org_a, user_a)
    for url in (f"/api/v1/analysis/{ids['job']}", f"/api/v1/transactions/{ids['tx']}",
                f"/api/v1/muhasebe/mizan/{ids['job']}", f"/api/v1/smmm/onay/queue/{ids['job']}"):
        resp = await client.get(url, headers=owner)
        assert resp.status_code == 200, f"{url}: {resp.status_code} {resp.text[:200]}"


@pytest.mark.asyncio
async def test_a_user_without_an_organisation_reaches_nothing_of_anyone_elses(client) -> None:
    """The old checks skipped themselves when the caller had no organisation."""
    _h, org_a, user_a = await _member(client, "orgd@example.com")
    ids = await _seed(client, org_a, user_a)
    loner, _, _ = await _member(client, "loner@example.com", org=False)

    assert (await client.get(f"/api/v1/analysis/{ids['job']}", headers=loner)).status_code == 404
    listed = (await client.get("/api/v1/jobs", headers=loner)).json()["data"]
    assert ids["job"] not in [j["job_id"] for j in listed]


@pytest.mark.asyncio
async def test_unauthenticated_callers_are_refused(client) -> None:
    for method, url in (
        ("GET", "/api/v1/brief/morning"),
        ("POST", "/api/v1/brief/morning/generate"),
        ("GET", "/api/v1/reports/x/download"),
        ("GET", "/api/v1/system/ops"),
        ("GET", "/api/v1/system/llm-costs"),
        ("POST", "/api/v1/email/ingest"),
        ("GET", "/api/v1/stream/00000000-0000-0000-0000-000000000000"),
    ):
        resp = await client.request(method, url)
        assert resp.status_code == 401, f"{method} {url}: {resp.status_code}"


@pytest.mark.asyncio
async def test_a_stream_ticket_opens_only_its_own_job(client) -> None:
    owner, org_a, user_a = await _member(client, "st@example.com")
    ids = await _seed(client, org_a, user_a)
    other = await _seed(client, org_a, user_a)

    ticket = (await client.post(f"/api/v1/stream/{ids['job']}/ticket", headers=owner)).json()["data"]["ticket"]
    ok = await client.get(f"/api/v1/stream/{ids['job']}", params={"ticket": ticket})
    assert ok.status_code == 200
    reused = await client.get(f"/api/v1/stream/{other['job']}", params={"ticket": ticket})
    assert reused.status_code == 401, "bilet başka bir işe açılmamalı"
    forged = await client.get(f"/api/v1/stream/{ids['job']}", params={"ticket": ticket[:-4] + "0000"})
    assert forged.status_code == 401


@pytest.mark.asyncio
async def test_ceo_analysis_refuses_a_server_file_path(client) -> None:
    owner, _org, _ = await _member(client, "ceo@example.com")
    resp = await client.post("/api/v1/ceo/analyze", headers=owner,
                             json={"cfo_file_path": "/etc/passwd", "cfo_file_type": "csv"})
    assert resp.status_code == 422
    assert "analyze-from-job" in resp.text


@pytest.mark.asyncio
async def test_email_ingest_ignores_an_org_header(client) -> None:
    """The organisation came from `X-Org-Id`; a caller could name any."""
    h, _org, _ = await _member(client, "mail@example.com")
    raw = b"From: a@b.c\r\nTo: x@y.z\r\nSubject: s\r\n\r\nno attachments"
    resp = await client.post("/api/v1/email/ingest", headers={**h, "X-Org-Id": "someone-else"}, content=raw)
    assert resp.status_code == 200
    # No attachment, no job — the point is it authenticated and did not 401/500.
