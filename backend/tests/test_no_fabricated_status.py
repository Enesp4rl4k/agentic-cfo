"""Endpoints that used to claim a state nobody measured.

ISO 27001 controls were all "implemented", the compliance dashboard scored ISO at a fixed 85, a failed
anomaly lookup read as "no anomalies", and constant "healthy" health-checks answered for services
nobody checked. Missing evidence is shown as missing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from tests.api_helpers import bellek_istemcisi, kullanici

P = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


@pytest.mark.asyncio
async def test_iso27001_controls_claim_nothing_implemented(client):
    headers, _, _ = await kullanici(client, "iso@example.com")
    r = await client.get(f"{P}/compliance/iso27001/controls", headers=headers)
    assert r.status_code == 200
    items = r.json()["data"]["controls"]
    assert items and {c["status"] for c in items} == {"not_assessed"}


@pytest.mark.asyncio
async def test_dashboard_has_no_invented_iso_score_and_unreadable_data_is_unknown(client, monkeypatch):
    from app.api import compliance_extended as ce

    headers, org_id, _ = await kullanici(client, "dash@example.com")
    r = await client.get(f"{P}/compliance/dashboard/{org_id}", headers=headers)
    iso = r.json()["data"]["frameworks"]["iso27001"]
    assert iso == {"score": None, "status": "not_assessed"}

    async def unreadable(org_id, db):
        return {"critical_unacked": None, "medium_count": None, "low_count": None}

    monkeypatch.setattr(ce, "_get_anomalies_for_sox", unreadable)
    data = (await client.get(f"{P}/compliance/dashboard/{org_id}", headers=headers)).json()["data"]
    assert data["frameworks"]["sox"] == {"score": None, "status": "unknown"}
    sox = (await client.get(f"{P}/compliance/sox/status", headers=headers)).json()["data"]
    assert sox["section_404"]["status"] == "unknown" and sox["sox_score"] is None
    assert sox["section_409"]["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/audit/health-check", "/chro/health-check", "/risk/health-check"])
async def test_constant_health_checks_are_gone(client, path):
    headers, _, _ = await kullanici(client, "hc@example.com")
    assert (await client.get(f"{P}{path}", headers=headers)).status_code in (404, 405)


def test_pdf_runway_unknown_is_not_stable():
    from app.services import board_deck_pdf, executive_report_pdf

    for mod in (board_deck_pdf, executive_report_pdf):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "Stabil" not in src, mod.__name__
