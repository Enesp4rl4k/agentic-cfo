"""
Unit tests for OKR Tracking Agent — pure computation, no LLM calls.

Tests cover:
  - _score_kr: higher_is_better and lower_is_better modes
  - _status_from_score: threshold boundaries
  - _overall_status: aggregate scoring
  - _infer_okrs: full OKR inference from financial + tech signals
"""
from __future__ import annotations

import pytest
from app.agents.ceo.okr_agent import (
    _score_kr,
    _status_from_score,
    _overall_status,
    _infer_okrs,
)


# ── _score_kr ─────────────────────────────────────────────────────────────────

class TestScoreKr:
    def test_higher_is_better_at_target(self):
        assert _score_kr(actual=15.0, target=15.0) == 1.0

    def test_higher_is_better_above_target_clamps_to_1(self):
        assert _score_kr(actual=20.0, target=15.0) == 1.0

    def test_higher_is_better_below_target(self):
        score = _score_kr(actual=7.5, target=15.0)
        assert abs(score - 0.5) < 1e-9

    def test_higher_is_better_zero_actual(self):
        assert _score_kr(actual=0.0, target=15.0) == 0.0

    def test_higher_is_better_none_actual(self):
        assert _score_kr(actual=None, target=15.0) == 0.0

    def test_lower_is_better_at_target(self):
        assert _score_kr(actual=2.0, target=2.0, higher_is_better=False) == 1.0

    def test_lower_is_better_below_target(self):
        # actual=1h, target=2h → better than target → score > 1.0 → clamped to 1.0
        assert _score_kr(actual=1.0, target=2.0, higher_is_better=False) == 1.0

    def test_lower_is_better_above_target(self):
        # actual=4h, target=2h → score = 2/4 = 0.5
        score = _score_kr(actual=4.0, target=2.0, higher_is_better=False)
        assert abs(score - 0.5) < 1e-9

    def test_lower_is_better_zero_actual(self):
        # actual=0 with lower_is_better → perfect → score = 1.0
        assert _score_kr(actual=0.0, target=2.0, higher_is_better=False) == 1.0

    def test_target_zero_returns_zero(self):
        assert _score_kr(actual=5.0, target=0.0) == 0.0


# ── _status_from_score ────────────────────────────────────────────────────────

class TestStatusFromScore:
    def test_achieved(self):
        assert _status_from_score(1.0) == "achieved"

    def test_on_track(self):
        assert _status_from_score(0.85) == "on_track"
        assert _status_from_score(0.70) == "on_track"

    def test_at_risk(self):
        assert _status_from_score(0.69) == "at_risk"
        assert _status_from_score(0.40) == "at_risk"

    def test_off_track(self):
        assert _status_from_score(0.39) == "off_track"
        assert _status_from_score(0.0) == "off_track"


# ── _overall_status ───────────────────────────────────────────────────────────

class TestOverallStatus:
    def _make_krs(self, pcts: list[int]) -> list[dict]:
        return [{"progress_pct": p} for p in pcts]

    def test_all_achieved(self):
        status, score = _overall_status(self._make_krs([100, 100]))
        assert status == "achieved"
        assert abs(score - 1.0) < 1e-9

    def test_mixed_on_track(self):
        status, score = _overall_status(self._make_krs([80, 75]))
        assert status == "on_track"

    def test_mixed_at_risk(self):
        status, score = _overall_status(self._make_krs([50, 60]))
        assert status == "at_risk"

    def test_off_track(self):
        status, score = _overall_status(self._make_krs([20, 30]))
        assert status == "off_track"

    def test_empty_returns_off_track(self):
        status, score = _overall_status([])
        assert status == "off_track"
        assert score == 0.0


# ── _infer_okrs ───────────────────────────────────────────────────────────────

class TestInferOkrs:
    def _fin(self, net_margin=0.12, runway=8.0, revenue=1_000_000, forecast=1_100_000):
        return {
            "net_margin": net_margin,
            "cash_runway_months": runway,
            "revenue_cents": revenue,
            "forecast_base_12m_cents": forecast,
        }

    def _tech(self, health=5.0, mttr=3.0, debt=5.0, velocity=35.0,
              infra_waste=50_000, infra_cost=500_000):
        return {
            "overall_health_score": health,
            "mttr_hours": mttr,
            "debt_score": debt,
            "avg_velocity": velocity,
            "infra_waste_cents": infra_waste,
            "infra_cost_cents": infra_cost,
        }

    def test_returns_five_objectives(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], "2024-Q2")
        assert len(objs) == 5

    def test_objective_ids(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], None)
        ids = {o["id"] for o in objs}
        assert ids == {
            "fin_profitability", "fin_growth",
            "tech_reliability", "tech_efficiency", "team_velocity",
        }

    def test_each_objective_has_required_fields(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], None)
        for obj in objs:
            assert "id" in obj
            assert "title" in obj
            assert "owner" in obj
            assert "key_results" in obj
            assert "overall_status" in obj
            assert "score" in obj

    def test_each_kr_has_required_fields(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], None)
        for obj in objs:
            for kr in obj["key_results"]:
                assert "kr" in kr
                assert "target" in kr
                assert "actual" in kr
                assert "unit" in kr
                assert "status" in kr
                assert "progress_pct" in kr

    def test_healthy_fin_produces_on_track_profitability(self):
        # net_margin=0.15 meets target exactly, runway=12 meets target exactly
        fin = self._fin(net_margin=0.15, runway=12.0)
        objs = _infer_okrs(fin, self._tech(), [], None)
        prof = next(o for o in objs if o["id"] == "fin_profitability")
        assert prof["overall_status"] in ("achieved", "on_track")

    def test_poor_margin_produces_at_risk_or_off_track(self):
        fin = self._fin(net_margin=0.03, runway=3.0)
        objs = _infer_okrs(fin, self._tech(), [], None)
        prof = next(o for o in objs if o["id"] == "fin_profitability")
        assert prof["overall_status"] in ("at_risk", "off_track")

    def test_low_mttr_produces_good_reliability(self):
        # mttr=1h is better than target=2h → should be achieved or on_track
        tech = self._tech(mttr=1.0)
        objs = _infer_okrs(self._fin(), tech, [], None)
        rel = next(o for o in objs if o["id"] == "tech_reliability")
        mttr_kr = next(kr for kr in rel["key_results"] if "MTTR" in kr["kr"])
        assert mttr_kr["status"] in ("achieved", "on_track")

    def test_critical_cross_risks_affect_reliability(self):
        cross_risks = [
            {"severity": "critical", "title": "Risk A"},
            {"severity": "critical", "title": "Risk B"},
        ]
        objs = _infer_okrs(self._fin(), self._tech(), cross_risks, None)
        rel = next(o for o in objs if o["id"] == "tech_reliability")
        # KR text is in Turkish: "Sıfır kritik çapraz alan riski"
        zero_risk_kr = next(
            (kr for kr in rel["key_results"] if "sıfır" in kr["kr"].lower() or "kritik" in kr["kr"].lower()), None
        )
        assert zero_risk_kr is not None
        # 2 critical risks → off_track
        assert zero_risk_kr["status"] == "off_track"

    def test_no_critical_risks_achieves_zero_risk_kr(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], None)
        rel = next(o for o in objs if o["id"] == "tech_reliability")
        # KR text is in Turkish: "Sıfır kritik çapraz alan riski"
        zero_risk_kr = next(
            (kr for kr in rel["key_results"] if "sıfır" in kr["kr"].lower() or "kritik" in kr["kr"].lower()), None
        )
        assert zero_risk_kr is not None
        assert zero_risk_kr["status"] == "achieved"

    def test_no_data_returns_zero_progress(self):
        objs = _infer_okrs(None, None, None, None)
        for obj in objs:
            for kr in obj["key_results"]:
                if kr["actual"] is None:
                    assert kr["progress_pct"] == 0

    def test_okr_definitions_override_target(self):
        # Override net margin target to 0.05 (easier to achieve)
        # KR text must match the Turkish key used in defaults: "Net marj ≥ 15%"
        overrides = [{
            "id": "fin_profitability",
            "key_results": [{"kr": "Net marj ≥ 15%", "target": 0.05}],
        }]
        fin = self._fin(net_margin=0.06)
        objs = _infer_okrs(fin, self._tech(), [], None, okr_definitions=overrides)
        prof = next(o for o in objs if o["id"] == "fin_profitability")
        # Match by "marj" (Turkish) or "margin" (English) to be locale-agnostic
        margin_kr = next(
            kr for kr in prof["key_results"]
            if "marj" in kr["kr"].lower() or "margin" in kr["kr"].lower()
        )
        assert margin_kr["target"] == 0.05
        # 0.06 / 0.05 = 1.2 → clamped to 1.0 → achieved
        assert margin_kr["status"] == "achieved"

    def test_score_is_between_0_and_1(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], None)
        for obj in objs:
            assert 0.0 <= obj["score"] <= 1.0

    def test_progress_pct_between_0_and_100(self):
        objs = _infer_okrs(self._fin(), self._tech(), [], None)
        for obj in objs:
            for kr in obj["key_results"]:
                assert 0 <= kr["progress_pct"] <= 100
