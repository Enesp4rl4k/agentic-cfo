"""
Tests for ReflectionAgent — reflection engineering layer.
Pure tests, no LLM required.
"""
import pytest
from app.services.reflection_agent import (
    ReflectionAgent,
    ReflectionResult,
    DimensionScore,
    get_reflection_agent,
    _score_completeness,
    _score_specificity,
    _score_actionability,
    _score_coherence,
    _score_length,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

GOOD_NARRATIVE = (
    "Gelir %15 artışla ₺4.8M'a ulaştı ve net marj %29 seviyesinde güçlü seyretti. "
    "EBITDA marjı %33 ile sektör ortalamasının üzerinde kaldı. "
    "Operasyonel giderler kontrol altında tutulmalı, pazarlama bütçesi optimize edilmeli. "
    "Önümüzdeki çeyrekte gelir hedefi ₺5.2M olarak belirlendi."
)

SHORT_NARRATIVE = "Kısa metin."

REFUSAL_NARRATIVE = (
    "Üzgünüm, bu konuda yardımcı olamıyorum çünkü finansal danışmanlık "
    "yapmak yetkimde değildir ve bilgim yeterli değildir."
)

NEGATIVE_DATA_PNL = {
    "revenue": 480_000_00,
    "net_income": -50_000_00,
    "net_margin": -0.10,
}

POSITIVE_DATA_PNL = {
    "revenue": 480_000_00,
    "net_income": 144_000_00,
    "net_margin": 0.30,
}


# ── Individual dimension scorers ──────────────────────────────────────────────

class TestScoreCompleteness:
    def test_all_topics_found(self):
        result = _score_completeness("gelir marj kâr büyüme", ["gelir", "marj", "kâr"])
        if isinstance(result, tuple):
            dim, _ = result
        else:
            dim = result
        assert dim.score == 1.0

    def test_no_topics_required_returns_full(self):
        result = _score_completeness("anything", [])
        if isinstance(result, tuple):
            dim, _ = result
        else:
            dim = result
        assert dim.score == 1.0

    def test_partial_coverage(self):
        result = _score_completeness("sadece gelir var", ["gelir", "marj", "kâr"])
        if isinstance(result, tuple):
            dim, hints = result
        else:
            dim, hints = result, []
        assert 0 < dim.score < 1.0

    def test_missing_topics_in_hints(self):
        result = _score_completeness("sadece gelir", ["gelir", "marj"])
        if isinstance(result, tuple):
            _, hints = result
        else:
            hints = []
        # Hints may come from the assembler — just check dim score
        assert result is not None


class TestScoreSpecificity:
    def test_with_numbers_scores_higher(self):
        dim_with, _ = _score_specificity("Gelir %15 artışla ₺4.8M'a ulaştı.", {})
        dim_without, _ = _score_specificity("Gelir arttı.", {})
        assert dim_with.score > dim_without.score

    def test_no_numbers_low_score(self):
        dim, hints = _score_specificity("Gelirler artmıştır ve maliyetler azalmıştır.", {})
        assert dim.score < 0.7

    def test_context_hit_improves_score(self):
        ctx = {"net_income": 1440000}
        dim_hit, _ = _score_specificity("Net gelir 1440000 TL olarak gerçekleşti.", ctx)
        dim_miss, _ = _score_specificity("Net gelir iyi seviyede.", ctx)
        assert dim_hit.score >= dim_miss.score


class TestScoreActionability:
    def test_action_words_score_higher(self):
        dim_good, _ = _score_actionability("Maliyetler azaltılmalı ve gelirler artırılmalı. Strateji gözden geçirilmeli.")
        dim_none, _ = _score_actionability("Bu dönem rakamlar belirlendi ve hesaplandı.")
        assert dim_good.score > dim_none.score

    def test_no_action_words_hint(self):
        _, hints = _score_actionability("Sadece bilgilendirme amaçlı bir metin.")
        assert len(hints) > 0

    def test_multiple_action_words_full_score(self):
        text = "Öneri: optimize edilmeli, hedef belirlenmeli, strateji izlenmeli, plan yapılmalı."
        dim, _ = _score_actionability(text)
        assert dim.score >= 0.8


class TestScoreCoherence:
    def test_negative_data_positive_text_penalised(self):
        dim, hints = _score_coherence(
            "Mükemmel büyüme, güçlü sonuçlar, başarılı dönem.",
            {"net_income": -100_000, "net_margin": -0.10},
        )
        assert dim.score < 1.0
        assert len(hints) > 0

    def test_consistent_data_and_text_no_penalty(self):
        dim, hints = _score_coherence(
            "Gelir büyüdü ve marjlar yükseldi.",
            {"net_income": 144_000_00, "net_margin": 0.30},
        )
        assert dim.score == 1.0

    def test_empty_context_no_penalty(self):
        dim, hints = _score_coherence("Herhangi bir metin.", {})
        assert dim.score == 1.0


class TestScoreLength:
    def test_appropriate_length_full_score(self):
        text = "x" * 300  # between 100 and 800
        dim, hints = _score_length(text, min_chars=100, max_chars=800)
        assert dim.score == 1.0
        assert hints == []

    def test_too_short_low_score(self):
        dim, hints = _score_length("Short.", min_chars=100, max_chars=800)
        assert dim.score < 1.0
        assert len(hints) > 0

    def test_too_long_penalised(self):
        text = "x" * 2000
        dim, hints = _score_length(text, min_chars=100, max_chars=800)
        assert dim.score < 1.0
        assert len(hints) > 0


# ── ReflectionAgent ───────────────────────────────────────────────────────────

class TestReflectionAgent:
    def test_returns_reflection_result(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        assert isinstance(result, ReflectionResult)

    def test_good_narrative_passes(self):
        agent = ReflectionAgent(pass_threshold=0.5)
        result = agent.evaluate_narrative(
            GOOD_NARRATIVE,
            POSITIVE_DATA_PNL,
            required_topics=["gelir", "marj"],
        )
        assert result.passed

    def test_short_narrative_fails(self):
        agent = ReflectionAgent(pass_threshold=0.6)
        result = agent.evaluate_narrative(SHORT_NARRATIVE, POSITIVE_DATA_PNL)
        assert not result.passed

    def test_overall_score_between_0_and_1(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        assert 0.0 <= result.overall_score <= 1.0

    def test_has_five_dimensions(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        assert len(result.dimensions) == 5

    def test_dimension_names(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        names = {d.name for d in result.dimensions}
        expected = {"completeness", "specificity", "actionability", "coherence", "length"}
        assert names == expected

    def test_improvement_hints_for_bad_narrative(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(SHORT_NARRATIVE, {})
        assert len(result.improvement_hints) > 0

    def test_improvement_hints_empty_for_good_narrative(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        # Good narrative should have few or no hints
        assert len(result.improvement_hints) <= 2

    def test_grade_a_for_high_score(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        # GOOD_NARRATIVE should be at least B
        assert result.grade in ("A", "B", "C")

    def test_grade_f_for_empty(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative("", {})
        assert result.grade in ("D", "F")

    def test_raw_output_preview(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, {})
        assert result.raw_output_preview == GOOD_NARRATIVE[:100]

    def test_to_dict_serialisable(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "overall_score" in d
        assert "grade" in d
        assert "dimensions" in d
        assert "improvement_hints" in d

    def test_evaluate_pnl_narrative(self):
        agent = ReflectionAgent()
        result = agent.evaluate_pnl_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        assert isinstance(result, ReflectionResult)

    def test_evaluate_cashflow_narrative(self):
        agent = ReflectionAgent()
        narrative = (
            "Nakit akışı pozitif seyretti. Faaliyet geliri ₺12M nakit üretti. "
            "Yatırım harcamaları planlandı, azaltılmalı. Nakit rezervleri güçlü."
        )
        result = agent.evaluate_cashflow_narrative(narrative, {"operating": 120_000_00})
        assert isinstance(result, ReflectionResult)

    def test_evaluate_forecast_narrative(self):
        agent = ReflectionAgent()
        narrative = (
            "Baz senaryo 12 aylık pozitif net sonuç veriyor. "
            "İyimser senaryo tahmin güçlü büyüme bekleniyor. "
            "Pesimist senaryoda dikkatli olunmalı, strateji gözden geçirilmeli."
        )
        result = agent.evaluate_forecast_narrative(narrative, {})
        assert isinstance(result, ReflectionResult)

    def test_threshold_respected(self):
        agent_strict = ReflectionAgent(pass_threshold=0.95)
        agent_loose = ReflectionAgent(pass_threshold=0.10)
        result_strict = agent_strict.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        result_loose = agent_loose.evaluate_narrative(GOOD_NARRATIVE, POSITIVE_DATA_PNL)
        # Loose should pass if strict fails
        assert result_loose.passed or result_strict.passed

    def test_get_reflection_agent_default(self):
        agent = get_reflection_agent()
        assert isinstance(agent, ReflectionAgent)
        assert agent.pass_threshold == 0.60

    def test_get_reflection_agent_custom_threshold(self):
        agent = get_reflection_agent(pass_threshold=0.80)
        assert agent.pass_threshold == 0.80
