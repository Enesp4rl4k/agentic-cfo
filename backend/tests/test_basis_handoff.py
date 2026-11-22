"""A basis tag is not dropped at a hand-off, and no text claims more than the basis says.

The runway block says whether its balance is `known` or `assumed`, its date, its months, the assumption sentence
and whether two statements may be one account. Everything built on its figures carries that and says no more:
"kanıtlı" appears only for a known basis, and only a proven basis may raise a critical alert.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agents.orchestration.proactive_alerts import AlertEvent, ProactiveAlertOrchestrator
from app.agents.risk.gercek_kri import cfo_kri
from app.models.proactive_alert import ProactiveAlert
from app.services import cascade_inputs
from app.services.cascade_inputs import RunwayBasis, baseline_from
from app.services.decision_packet import build_situation
from tests.db_helpers import gecici_oturum

KNOWN_MSG = "12 Mart 2026 ekstresindeki bakiyeye göre kasa 200.000 ₺."
ASSUMED_MSG = (
    "12 Mart 2026 ekstresindeki bakiyeye göre kasa 200.000 ₺. "
    "Bakiye zayıf kanıta dayanıyor (yalnızca 2 bakiye adımıyla doğrulandı), varsayım olarak alındı."
)
IDENTITY_MSG = (
    "12 Mart 2026 ekstresindeki bakiyeye göre kasa 200.000 ₺. 2 ekstrenin aynı hesaba ait olduğu bilinmiyor."
)


def block(kind: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "computed", "opening_cash_cents": 200_000_00, "as_of": "2026-03-12", "months_used": 3,
        "avg_monthly_net_cents": -50_000_00, "runway_months": 2.0, "assumptions": [],
        "basis": "known", "balance_basis": "known", "identity_uncertain": False, "identity_note": None,
        "message": KNOWN_MSG, "level": "critical",
    }
    if kind == "assumed":
        base.update(basis="assumed", balance_basis="assumed", message=ASSUMED_MSG)
    if kind == "identity":
        base.update(identity_uncertain=True, identity_note="2 ekstrenin aynı hesaba ait olduğu bilinmiyor", message=IDENTITY_MSG)
    return base


# ── the basis object ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_basis_keeps_every_field_and_only_known_is_proven():
    for kind, proven in (("known", True), ("assumed", False), ("identity", False)):
        _, basis = baseline_from(block(kind))
        d = basis.to_dict()
        assert d["proven"] is proven
        assert {"basis", "balance_basis", "as_of", "months_used", "assumptions", "identity_uncertain",
                "identity_note", "message", "cash_known"} <= set(d)
        assert ("kanıtlı" in basis.sentence()) is proven, (kind, basis.sentence())
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in baseline_from(block("assumed"))[1].sentence()
    assert "aynı hesaba ait olduğu bilinmiyor" in baseline_from(block("identity"))[1].sentence()
    assert "kanıtlı" not in RunwayBasis("no_balance", None, None, None, 0).sentence()


# ── the scan end to end ──────────────────────────────────────────────────────────────────────────────────────────

class _Ctx:
    last_cfo_result = {
        "pnl": {"revenue": 12_000_000, "total_opex": 18_000_000},
        "cashflow": {"net_change": -5_000_000}, "forecast": {},
    }
    last_chro_result = last_cto_result = last_cmo_result = last_coo_result = None


@pytest_asyncio.fixture
async def db():
    import app.models  # noqa: F401

    async with gecici_oturum() as session:
        yield session


async def _scan(db, monkeypatch, runway_block: dict[str, Any]) -> list[ProactiveAlert]:
    async def ctx(org_id, session=None):
        return _Ctx()

    async def company_runway(session, org_id):
        return runway_block

    monkeypatch.setattr("app.services.company_context.get_company_context", ctx)
    monkeypatch.setattr(cascade_inputs, "company_runway", company_runway)
    orch = ProactiveAlertOrchestrator(db=db)

    async def kris(org_id: str) -> dict[str, Any]:
        return {"kris": [], "posture": {"red_kris": [], "upcoming_red": [], "cascade_ready": [
            {"name": "Nakit ömrü", "cascade_trigger": "cash_crisis", "cascade_params": {"runway_months": 0.0}}]}}

    monkeypatch.setattr(orch, "_compute_current_kris", kris)
    assert (await orch.scan_and_alert("org-1"))["alerts_created"] == 1
    return list((await db.execute(select(ProactiveAlert))).scalars())


async def test_measured_inputs_still_fire_a_critical_alert_that_says_proven(db, monkeypatch):
    (alert,) = await _scan(db, monkeypatch, block("known"))
    assert alert.severity == "critical"
    assert "kanıtlı kasa bakiyesi (2026-03-12)" in (alert.body or "")


async def test_assumed_inputs_fire_a_capped_labelled_alert_with_the_runways_own_sentence(db, monkeypatch):
    (alert,) = await _scan(db, monkeypatch, block("assumed"))
    assert alert.severity == "high"
    assert "kanıtlı" not in (alert.body or "")
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in (alert.body or "")


async def test_an_open_account_identity_question_caps_the_alert_too(db, monkeypatch):
    (alert,) = await _scan(db, monkeypatch, block("identity"))
    assert alert.severity == "high" and "kanıtlı" not in (alert.body or "")
    assert "aynı hesaba ait olduğu bilinmiyor" in (alert.body or "")


# ── the KRI path ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["known", "assumed", "identity"])
async def test_the_kri_alert_carries_the_forecasts_basis(kind, db):
    forecast = {"scenarios": {"base": {"runway_months": 2.0}}, "runway": block(kind)}
    (kri,) = [k for k in cfo_kri({}, forecast) if k["name"] == "Nakit Ömrü"]
    assert kri["basis"] == block(kind)["basis"]
    orch = ProactiveAlertOrchestrator(db=db)
    alert = await orch._create_kri_alert("org-1", kri, "critical")
    assert isinstance(alert, AlertEvent)
    if kind == "known":
        assert alert.severity == "critical" and "Dayanak sınırı" not in alert.body
    else:
        assert alert.severity == "high" and "Dayanak sınırı" in alert.body
        assert "kanıtlı" not in alert.body


# ── the other hand-offs ──────────────────────────────────────────────────────────────────────────────────────────

async def test_the_trigger_action_result_carries_the_basis(db, monkeypatch):
    from app.models.trigger import TriggerDefinitionRow  # noqa: F401
    from app.services.triggers import actions

    async def company_runway(session, org_id):
        return block("assumed")

    class Ctx(_Ctx):
        last_cfo_result: dict[str, Any] = {"pnl": {"revenue": 12_000_000, "total_opex": 18_000_000}}

    async def ctx(org_id, session=None):
        return Ctx()

    monkeypatch.setattr("app.services.company_context.get_company_context", ctx)
    monkeypatch.setattr(cascade_inputs, "company_runway", company_runway)

    class Definition:
        action_params = {"trigger": "cash_crisis", "runway_months": 0.5}

    result = await actions._cascade_simulate(db, "org-1", Definition(), {})  # type: ignore[arg-type]
    assert result["basis"]["basis"] == "assumed" and result["basis"]["proven"] is False
    assert "kanıtlı" not in str(result["basis"]["message"])


async def test_the_cascade_api_answer_carries_the_basis(monkeypatch):
    from tests.api_helpers import bellek_istemcisi, kullanici

    async def company_runway(session, org_id):
        return block("assumed")

    monkeypatch.setattr(cascade_inputs, "company_runway", company_runway)
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "basis@example.com")
        r = await client.post("/api/v1/cascade/simulate", headers=headers, json={
            "trigger": "key_person_loss", "org_id": org_id, "key_person_loss": {"role": "cto"}})
        assert r.status_code == 200, r.text
        assert r.json()["baseline_basis"]["basis"] == "assumed"


async def test_the_decision_packet_situation_keeps_the_runway_basis(db):
    class Job:
        id = "j"
        min_confidence = None

    forecast = {"scenarios": {"base": {"runway_months": 2.0}}, "runway": block("assumed")}
    situation = await build_situation(db, Job(), {}, {}, forecast)  # type: ignore[arg-type]
    assert situation["runway_basis"] == "assumed"
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in situation["runway_note"]
    known = await build_situation(db, Job(), {}, {}, {**forecast, "runway": block("known")})  # type: ignore[arg-type]
    assert known["runway_basis"] == "known" and known["runway_note"] is None


def test_no_alert_path_uses_the_role_coefficient_what_if():
    import app.agents.orchestration.proactive_alerts as alerts

    source = Path(alerts.__file__).read_text(encoding="utf-8")
    assert "multidomain_counterfactual" not in source and "analyze_headcount_change" not in source


def test_the_hire_what_if_labels_its_role_coefficient_as_an_assumption():
    from app.services.multidomain_counterfactual import MultidomainCounterfactual

    engine = MultidomainCounterfactual(
        pnl={"revenue": 12_000_000_00, "total_opex": 8_000_000_00},
        chro_data={"total_headcount": 20, "avg_monthly_salary_try": 60_000},
    )
    result = engine.analyze_headcount_change(delta=2, role_type="sales")
    assert "varsayım: bu rol için gelir etkisi %20" in str(result.to_dict())
