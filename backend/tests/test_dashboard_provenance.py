"""1.3 / U7: the dashboard endpoint labels how each section was produced.

`GET /dashboard/{job_id}` stamps a `provenance` map (real / rule_based /
manual / estimated) so the pnl / tax / budget / forecast metric cards can
badge themselves as "Gerçek" vs "Tahmin" (DESIGN.md: "distinguish real,
estimated and benchmark data close to the metric"). The stamp is applied at
read time, so stored reports — golden demo replays included — are labelled
without a data migration.

Harness mirrors test_demo_clone: demo guest is the lightest proven path
through `load_owned_job` (no password auth needed).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from tests.db_helpers import gecici_motor
from tests.golden_seed import _auth, _guest, _seed_golden


@pytest_asyncio.fixture
async def test_client(monkeypatch):
    """In-memory DB dependency override + demo_mode on."""
    test_engine = gecici_motor(echo=False)
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


@pytest.mark.asyncio
async def test_dashboard_labels_section_provenance(test_client):
    """pnl / tax / budget / forecast carry their production basis on the wire."""
    await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)

    ctx = await test_client.get("/api/v1/context/me", headers=_auth(data))
    assert ctx.status_code == 200, ctx.text
    job_id = ctx.json()["data"]["active_cfo_job_id"]
    assert job_id

    dash = await test_client.get(
        f"/api/v1/dashboard/{job_id}", headers=_auth(data)
    )
    assert dash.status_code == 200, dash.text
    prov = dash.json()["data"]["provenance"]

    # Measured from the parsed file / pasted transactions → "Gerçek" class.
    assert prov["pnl"]["data_source"] == "real"
    assert prov["pnl"]["synthetic"] is False
    assert prov["kpis"]["data_source"] == "real"

    # Deterministic rules over real data → still non-synthetic, basis says so.
    assert prov["tax"]["data_source"] == "rule_based"
    assert prov["tax"]["synthetic"] is False
    assert "rule" in prov["tax"]["basis"]

    # The budget plan is user-entered → non-synthetic, honestly labelled.
    assert prov["budget"]["data_source"] == "manual"
    assert prov["budget"]["synthetic"] is False

    # Extrapolation is the one synthetic class — the UI must not call it real.
    assert prov["forecast"]["data_source"] == "estimated"
    assert prov["forecast"]["synthetic"] is True

    # Every explanation is reachable, never empty (DESIGN.md).
    for block in prov.values():
        assert block["basis"]
