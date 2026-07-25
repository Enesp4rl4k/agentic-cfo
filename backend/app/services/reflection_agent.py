"""
Reflection Engineering — ReflectionAgent

Adds self-evaluation capability to the agent pipeline.
After any agent produces a narrative or analysis, the ReflectionAgent
evaluates the output quality and returns a structured quality score.

This solves the "blind trust" problem: currently the pipeline accepts
any LLM output without checking if it's actually useful or accurate.

Architecture:
  - ReflectionResult: structured quality assessment
  - ReflectionAgent: evaluates output across 5 dimensions
  - Rule-based evaluator: no LLM needed, deterministic and fast
  - Optional LLM-based evaluator: deeper quality check when budget allows

Quality dimensions:
  1. Completeness   — does it cover all required topics?
  2. Specificity    — does it mention specific numbers/metrics?
  3. Actionability  — does it suggest concrete actions?
  4. Coherence      — is it logically consistent with the data?
  5. Length         — is it an appropriate length (not too short/long)?

Usage:
    agent = ReflectionAgent()

    result = agent.evaluate_narrative(
        narrative="Gelir %15 büyüdü...",
        context={"revenue": 4800000, "net_margin": 0.30},
        required_topics=["gelir", "marj", "öneri"],
    )

    if result.score < 0.6:
        # Trigger retry with specific feedback
        correction_hint = result.improvement_hints
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    name: str
    score: float        # 0.0 – 1.0
    weight: float       # relative importance
    reason: str = ""
    passed: bool = True


@dataclass
class ReflectionResult:
    """Structured quality assessment of an agent output."""
    overall_score: float            # 0.0 – 1.0 weighted average
    dimensions: list[DimensionScore]
    passed: bool                    # overall_score >= threshold
    threshold: float
    improvement_hints: list[str]    # specific actionable feedback
    raw_output_preview: str         # first 100 chars of evaluated text

    @property
    def grade(self) -> str:
        if self.overall_score >= 0.85:
            return "A"
        if self.overall_score >= 0.70:
            return "B"
        if self.overall_score >= 0.55:
            return "C"
        if self.overall_score >= 0.40:
            return "D"
        return "F"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 3),
            "grade":         self.grade,
            "passed":        self.passed,
            "threshold":     self.threshold,
            "dimensions": [
                {
                    "name":   d.name,
                    "score":  round(d.score, 3),
                    "passed": d.passed,
                    "reason": d.reason,
                }
                for d in self.dimensions
            ],
            "improvement_hints":    self.improvement_hints,
            "raw_output_preview":   self.raw_output_preview,
        }


# ── Heuristic evaluators ──────────────────────────────────────────────────────

def _score_completeness(
    text: str,
    required_topics: list[str],
) -> DimensionScore:
    """Check if all required topics are mentioned."""
    if not required_topics:
        return DimensionScore("completeness", 1.0, 0.25, "No required topics specified.")

    text_lower = text.lower()
    found = [t for t in required_topics if t.lower() in text_lower]
    score = len(found) / len(required_topics)
    missing = [t for t in required_topics if t.lower() not in text_lower]

    reason = f"{len(found)}/{len(required_topics)} topics covered."
    hints = [f"Şu konulardan bahsedilmedi: {', '.join(missing)}"] if missing else []

    return DimensionScore(
        name="completeness",
        score=score,
        weight=0.25,
        reason=reason,
        passed=score >= 0.7,
    ), hints  # type: ignore[return-value]


def _score_specificity(text: str, context: dict[str, Any]) -> tuple[DimensionScore, list[str]]:
    """Check if the narrative references specific numbers."""
    # Count numeric references (including percentages, currency)
    numbers_in_text = re.findall(r"\d+[.,]?\d*\s*[%₺$€km]?", text)
    num_count = len(numbers_in_text)

    # Check if key context values appear in text
    context_hits = 0
    context_misses = []
    for key, val in list(context.items())[:8]:
        if isinstance(val, (int, float)) and val != 0:
            # Check if the magnitude of the value appears
            val_str = str(abs(int(val)))[:4]  # first 4 digits
            if val_str in text or val_str.replace("0", "") in text:
                context_hits += 1
            else:
                context_misses.append(key)

    # Score: 0.5 from number density + 0.5 from context reference
    density_score = min(1.0, num_count / 3)  # 3+ numbers = full score
    ref_score = (context_hits / max(1, min(8, len(context)))) if context else 1.0
    score = 0.5 * density_score + 0.5 * ref_score

    hints = []
    if num_count < 2:
        hints.append("Daha fazla sayısal veri kullanın (yüzdeler, tutarlar).")
    if context_misses:
        hints.append(f"Şu metriklerden bahsedilmedi: {', '.join(context_misses[:3])}")

    return DimensionScore(
        name="specificity",
        score=score,
        weight=0.25,
        reason=f"{num_count} sayısal referans, {context_hits} bağlam metriği.",
        passed=score >= 0.5,
    ), hints


def _score_actionability(text: str) -> tuple[DimensionScore, list[str]]:
    """Check if the narrative includes actionable recommendations."""
    action_patterns = [
        r"öneri", r"tavsiye", r"yapılmal", r"gerekli", r"artırıl", r"azaltıl",
        r"optimize", r"kontrol", r"izlen", r"hedef", r"strateji", r"plan",
        r"recommend", r"should", r"must", r"action", r"improve", r"reduce",
        r"increase", r"focus",
    ]
    text_lower = text.lower()
    hits = sum(1 for p in action_patterns if re.search(p, text_lower))

    score = min(1.0, hits / 2)  # 2+ action words = full score
    hints = []
    if hits == 0:
        hints.append("Somut aksiyon önerileri ekleyin (ör. 'X azaltılmalı', 'Y hedeflenmeli').")

    return DimensionScore(
        name="actionability",
        score=score,
        weight=0.20,
        reason=f"{hits} aksiyon ifadesi bulundu.",
        passed=score >= 0.4,
    ), hints


def _score_coherence(
    text: str,
    context: dict[str, Any],
) -> tuple[DimensionScore, list[str]]:
    """
    Check logical coherence: detect contradictions between narrative and data.
    E.g. text says "artış" (increase) but net_income is negative.
    """
    text_lower = text.lower()
    hints = []
    penalty = 0.0

    # Check for positive language vs negative metrics
    positive_words = ["artış", "büyüme", "güçlü", "başarılı", "pozitif", "iyi"]
    negative_words = ["düşüş", "azalma", "negatif", "risk", "sorun", "kritik"]

    has_positive = any(w in text_lower for w in positive_words)
    has_negative = any(w in text_lower for w in negative_words)

    net_income = context.get("net_income", 0) or 0
    net_margin = context.get("net_margin", 0) or 0

    # If data is clearly negative but text is purely positive → likely incoherent
    if net_income < 0 and has_positive and not has_negative:
        penalty += 0.4
        hints.append("Veri negatif net gelir gösteriyor ama metin sadece olumlu ifadeler içeriyor.")

    # If data is clearly positive but text is purely negative → also flagged
    if net_margin > 0.15 and net_income > 0 and has_negative and not has_positive:
        penalty += 0.2
        hints.append("Sağlıklı finansal veriye rağmen metin sadece olumsuz ifadeler içeriyor.")

    score = max(0.0, 1.0 - penalty)
    return DimensionScore(
        name="coherence",
        score=score,
        weight=0.15,
        reason="Veri-metin tutarlılık kontrolü." + (" Çelişki tespit edildi." if penalty > 0 else " Tutarlı."),
        passed=score >= 0.5,
    ), hints


def _score_length(text: str, min_chars: int = 100, max_chars: int = 800) -> tuple[DimensionScore, list[str]]:
    """Check if the text length is appropriate."""
    n = len(text.strip())
    hints = []

    if n < min_chars:
        score = n / min_chars
        hints.append(f"Çok kısa ({n} karakter). En az {min_chars} karakter olmalı.")
    elif n > max_chars:
        # Penalise for being too verbose (but less severely)
        score = max(0.5, 1.0 - (n - max_chars) / max_chars * 0.3)
        hints.append(f"Çok uzun ({n} karakter). {max_chars} karakter altında tutun.")
    else:
        score = 1.0

    return DimensionScore(
        name="length",
        score=score,
        weight=0.15,
        reason=f"{n} karakter.",
        passed=score >= 0.6,
    ), hints


# ── ReflectionAgent ───────────────────────────────────────────────────────────

class ReflectionAgent:
    """
    Rule-based self-evaluation agent.

    Evaluates any text output against 5 quality dimensions.
    No LLM required — fast, deterministic, and observable.

    Parameters
    ----------
    pass_threshold : float
        Minimum overall score to consider the output acceptable (default 0.60).
    min_chars : int
        Minimum acceptable narrative length.
    max_chars : int
        Maximum acceptable narrative length.
    """

    def __init__(
        self,
        pass_threshold: float = 0.60,
        min_chars: int = 100,
        max_chars: int = 800,
    ) -> None:
        self.pass_threshold = pass_threshold
        self.min_chars = min_chars
        self.max_chars = max_chars

    def evaluate_narrative(
        self,
        narrative: str,
        context: dict[str, Any] | None = None,
        required_topics: list[str] | None = None,
    ) -> ReflectionResult:
        """
        Evaluate a narrative text.

        Parameters
        ----------
        narrative : str
            The text to evaluate.
        context : dict, optional
            The data dict used to generate the narrative (for coherence + specificity).
        required_topics : list[str], optional
            Topics that must appear in the narrative.
        """
        ctx = context or {}
        topics = required_topics or []

        dimensions: list[DimensionScore] = []
        all_hints: list[str] = []

        # 1. Completeness
        comp_result = _score_completeness(narrative, topics)
        if isinstance(comp_result, tuple):
            dim, hints = comp_result
        else:
            dim, hints = comp_result, []
        dimensions.append(dim)
        all_hints.extend(hints)

        # 2. Specificity
        spec_dim, spec_hints = _score_specificity(narrative, ctx)
        dimensions.append(spec_dim)
        all_hints.extend(spec_hints)

        # 3. Actionability
        act_dim, act_hints = _score_actionability(narrative)
        dimensions.append(act_dim)
        all_hints.extend(act_hints)

        # 4. Coherence
        coh_dim, coh_hints = _score_coherence(narrative, ctx)
        dimensions.append(coh_dim)
        all_hints.extend(coh_hints)

        # 5. Length
        len_dim, len_hints = _score_length(narrative, self.min_chars, self.max_chars)
        dimensions.append(len_dim)
        all_hints.extend(len_hints)

        # Weighted average
        total_weight = sum(d.weight for d in dimensions)
        overall = sum(d.score * d.weight for d in dimensions) / total_weight if total_weight > 0 else 0.0

        passed = overall >= self.pass_threshold

        result = ReflectionResult(
            overall_score=overall,
            dimensions=dimensions,
            passed=passed,
            threshold=self.pass_threshold,
            improvement_hints=list(dict.fromkeys(all_hints)),  # deduplicate
            raw_output_preview=narrative[:100],
        )

        logger.debug(
            "Reflection: grade=%s score=%.2f passed=%s agent_output_len=%d",
            result.grade, overall, passed, len(narrative),
        )

        return result

    def evaluate_pnl_narrative(
        self, narrative: str, pnl: dict[str, Any]
    ) -> ReflectionResult:
        return self.evaluate_narrative(
            narrative=narrative,
            context=pnl,
            required_topics=["gelir", "marj", "kâr"],
        )

    def evaluate_cashflow_narrative(
        self, narrative: str, cashflow: dict[str, Any]
    ) -> ReflectionResult:
        return self.evaluate_narrative(
            narrative=narrative,
            context=cashflow,
            required_topics=["nakit", "akış", "faaliyet"],
        )

    def evaluate_forecast_narrative(
        self, narrative: str, forecast: dict[str, Any]
    ) -> ReflectionResult:
        return self.evaluate_narrative(
            narrative=narrative,
            context=forecast,
            required_topics=["tahmin", "senaryo", "baz"],
        )


# ── Module-level default instance ────────────────────────────────────────────

_default_agent = ReflectionAgent(pass_threshold=0.60)


def get_reflection_agent(pass_threshold: float = 0.60) -> ReflectionAgent:
    global _default_agent
    if pass_threshold != 0.60:
        return ReflectionAgent(pass_threshold=pass_threshold)
    return _default_agent
