"""Runway readers that sat on the allowlist (PR #133 follow-up): the CFO summary other agents read carries a runway
only when it is KNOWN, and the stress card never says CRITICAL on a runway that is not proven."""
from __future__ import annotations

from typing import Any

from app.services.macro_stress import ShockInputs, StressBaseline, baseline_from_cfo, simulate
from app.services.semantic.projectors import project_from_cfo

KNOWN = {"status": "computed", "basis": "known", "balance_basis": "known", "as_of": "2026-03-31", "message": "m"}
ASSUMED = {**KNOWN, "balance_basis": "assumed"}


def _cfo(runway: dict[str, Any] | None, months: float = 2.0) -> dict[str, Any]:
    forecast: dict[str, Any] = {"scenarios": {"base": {"runway_months": months}}}
    if runway is not None:
        forecast["runway"] = runway
    return {
        "dashboard": {
            "pnl": {"revenue": 1_200_000, "net_income": -120_000, "total_expenses": 1_320_000, "net_margin": -0.1,
                    "opex_breakdown": {"rent": 1_320_000}},
            "cashflow": {"monthly_series": [{"month": f"2026-0{i}"} for i in range(1, 4)]},
            "forecast": forecast,
        }
    }


def _runway_points(cfo: dict[str, Any]) -> list[Any]:
    return [p for p in project_from_cfo(cfo, currency="TRY", job_id="j") if p.metric_id == "finance.runway_months"]


def test_the_cfo_summary_carries_a_runway_only_when_it_is_known() -> None:
    (known,) = _runway_points(_cfo(KNOWN))
    assert known.value == 2.0
    assert _runway_points(_cfo(ASSUMED)) == []
    assert _runway_points(_cfo(None)) == []                       # a bare number with no block: unverified
    assert _runway_points(_cfo({"status": "no_balance", "message": "bilinmiyor"})) == []


def test_the_stress_card_caps_critical_for_a_runway_that_is_not_proven() -> None:
    shock = ShockInputs(30, 30, 0, 0)
    for runway, level in ((KNOWN, "CRITICAL"), (ASSUMED, "HIGH"), (None, "HIGH")):
        base = baseline_from_cfo(_cfo(runway, 2.0)["dashboard"] | {"pnl": {"revenue": 1_200_000.0, "total_opex": 600_000.0, "net_income": -120_000.0}})
        assert base is not None
        base = StressBaseline(**{**base.__dict__, "monthly_opex_kurus": 5_000_000})
        out = simulate(shock, base)
        assert out["baseline_runway_basis"] == base.runway_basis
        assert out["risk_level"] == level, (runway, out)
