"""The Monte Carlo line says what the number is, and where its inputs came from.

It read "1000 Monte Carlo simülasyonu: %X olasılıkla nakit sıkıntısı riski var.
Tahminlerin güvenilirliği yüksek/orta/düşük" — the last sentence derived a
forecast's reliability from how risky the outcome was, which it does not
measure, and the first stated a probability rather than the share of
simulations that go negative. The growth and volatility behind it come from the
company's own months, or from stand-in defaults when there is too little
history; the text now says which.
"""
from __future__ import annotations

from app.agents.forecast_agent import _build_scenario_explanation


def _explain(mc: dict) -> str:
    out = _build_scenario_explanation({}, mc)
    return out["monte_carlo_summary"]


def test_it_reports_the_share_of_simulations_not_a_reliability_verdict():
    text = _explain({"runway_risk_pct": 42.0, "n_simulations": 1000, "growth_basis": "gecmis_aylar"})
    assert "1000 simülasyonun %42" in text
    assert "güvenilirliği" not in text
    assert "geçmiş aylarınızdan" in text


def test_default_growth_inputs_are_declared():
    text = _explain({"runway_risk_pct": 10.0, "n_simulations": 500, "growth_basis": "varsayilan"})
    assert "varsayılan büyüme ve oynaklık" in text
