"""The SLA ranking is a score with a stated basis, not a probability.

`_logistic_breach_risk` called itself a logistic model whose coefficients were
"learned heuristically" — they were written by hand and fitted to nothing — and
published the result as `breach_probability`, rounded to four decimals and
shown in the UI as a percentage. The ordering is worth keeping; the claim was
not.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.coo.sla_agent import _predict_breach_risk


def _ticket(ticket_id: str, *, age_hours: float, tier: str = "p1") -> dict:
    return {
        "ticket_id": ticket_id,
        "tier": tier,
        "category": "destek",
        "created_dt": datetime.now(UTC) - timedelta(hours=age_hours),
    }


def _rows(tickets):
    return _predict_breach_risk(tickets, {"destek": 0.2}, {"p1": 0.3, "p3": 0.1}, datetime.now(UTC))


def test_no_row_claims_a_probability():
    row = _rows([_ticket("T-1", age_hours=3)])[0]
    assert "breach_probability" not in row
    assert 0.0 <= row["risk_score"] <= 1.0
    assert row["risk_score"] == round(row["risk_score"], 2)  # no four-decimal precision
    assert row["risk_olcum"] == "kural"
    assert row["risk_dayanak"]


def test_the_older_ticket_ranks_first():
    rows = _rows([_ticket("yeni", age_hours=1), _ticket("eski", age_hours=20)])
    assert [r["ticket_id"] for r in rows] == ["eski", "yeni"]
    assert rows[0]["risk_score"] >= rows[1]["risk_score"]


def test_a_band_is_reported_for_each_ticket():
    rows = _rows([_ticket("T-1", age_hours=48), _ticket("T-2", age_hours=0.5, tier="p3")])
    assert {r["risk_level"] for r in rows} <= {"kritik", "yüksek", "orta", "düşük"}
    assert rows[0]["risk_level"] == "kritik"
