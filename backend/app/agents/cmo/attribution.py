"""
CMO Attribution Modeling — Multi-Touch Attribution Engine

Implements three attribution models to answer "which channel/campaign
actually drives conversions?":

1. Last-Click Attribution (default in most tools — baseline)
2. Linear Attribution (equal credit to all touchpoints)
3. Time-Decay Attribution (recent touchpoints get more credit)
4. Markov Chain Attribution (data-driven, no arbitrary rules)

Markov Chain Attribution:
  - Models customer journey as a Markov chain of channel touchpoints
  - Computes "removal effect" for each channel:
    "If we remove channel X, how much does conversion rate drop?"
  - Attribution credit = proportional to removal effect
  - Requires journey-level data (sequence of channels before conversion)

When only aggregated campaign data is available (no journey data),
falls back to Shapley value approximation using spend/conversion data.

Usage:
    from app.agents.cmo.attribution import AttributionEngine
    engine = AttributionEngine(campaigns, journeys)
    result = engine.compute_all_models()
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────

class AttributionEngine:
    """
    Multi-touch attribution engine.

    Supports both journey-level data (Markov chain) and
    aggregated campaign data (Shapley approximation).
    """

    def __init__(
        self,
        campaigns: list[dict[str, Any]],
        journeys: list[list[str]] | None = None,  # List of channel sequences
    ) -> None:
        self.campaigns = campaigns
        self.journeys  = journeys or []
        self._channels = list({c.get("channel", "unknown") for c in campaigns})

    # ── Last-click attribution ────────────────────────────────────────────────

    def last_click(self) -> dict[str, float]:
        """100% credit to the last channel in the journey."""
        if not self.journeys:
            return self._fallback_by_conversions()

        credits: dict[str, float] = defaultdict(float)
        for journey in self.journeys:
            if journey:
                credits[journey[-1]] += 1.0
        total = sum(credits.values()) or 1
        return {ch: round(v / total * 100, 2) for ch, v in credits.items()}

    # ── Linear attribution ────────────────────────────────────────────────────

    def linear(self) -> dict[str, float]:
        """Equal credit to all touchpoints in the journey."""
        if not self.journeys:
            return self._fallback_equal()

        credits: dict[str, float] = defaultdict(float)
        for journey in self.journeys:
            if not journey:
                continue
            share = 1.0 / len(journey)
            for channel in journey:
                credits[channel] += share
        total = sum(credits.values()) or 1
        return {ch: round(v / total * 100, 2) for ch, v in credits.items()}

    # ── Time-decay attribution ────────────────────────────────────────────────

    def time_decay(self, half_life: int = 7) -> dict[str, float]:
        """
        More credit to touchpoints closer to conversion.
        half_life: days until weight halves (default 7 days → weekly decay).
        """
        if not self.journeys:
            return self._fallback_by_conversions()

        credits: dict[str, float] = defaultdict(float)
        for journey in self.journeys:
            if not journey:
                continue
            n = len(journey)
            # Assign weights: last touch = 1.0, earlier touches decay exponentially
            weights = [2 ** (-(n - 1 - i) / half_life) for i in range(n)]
            total_w = sum(weights) or 1
            for ch, w in zip(journey, weights):
                credits[ch] += w / total_w
        total = sum(credits.values()) or 1
        return {ch: round(v / total * 100, 2) for ch, v in credits.items()}

    # ── Markov Chain attribution ──────────────────────────────────────────────

    def markov_chain(self) -> dict[str, Any]:
        """
        Data-driven attribution using Markov chain removal effect.

        Algorithm:
        1. Build transition matrix from channel journeys
        2. Compute baseline conversion rate from the Markov chain
        3. For each channel, compute conversion rate with that channel removed
        4. Attribution = (baseline - removal_rate) / sum(all removal effects)

        Returns:
            {
              "attribution": {channel: credit_pct},
              "removal_effects": {channel: effect},
              "transition_matrix": {from: {to: probability}},
            }
        """
        if len(self.journeys) < 10:
            logger.debug("Markov attribution: insufficient journeys (%d), using Shapley", len(self.journeys))
            shapley = self._shapley_approximation()
            return {
                "attribution":       shapley,
                "removal_effects":   {},
                "transition_matrix": {},
                "method":            "shapley_fallback",
                "note":              f"Markov için 10+ journey gerekiyor (şu an {len(self.journeys)})",
            }

        # Build transition matrix
        transitions = self._build_transition_matrix()
        channels    = set(transitions.keys()) | {
            ch for row in transitions.values() for ch in row
        }
        channels.discard("(conversion)")
        channels.discard("(null)")

        # Baseline conversion rate
        baseline = self._compute_conversion_rate(transitions)

        # Removal effects
        removal_effects: dict[str, float] = {}
        for channel in channels:
            reduced = self._remove_channel(transitions, channel)
            reduced_rate = self._compute_conversion_rate(reduced)
            removal_effects[channel] = max(0, baseline - reduced_rate)

        # Normalize to attribution credits
        total_effect = sum(removal_effects.values()) or 1
        attribution = {
            ch: round(eff / total_effect * 100, 2)
            for ch, eff in removal_effects.items()
        }

        return {
            "attribution":       attribution,
            "removal_effects":   {ch: round(v, 4) for ch, v in removal_effects.items()},
            "baseline_conv_rate": round(baseline, 4),
            "method":            "markov_chain",
        }

    def _build_transition_matrix(self) -> dict[str, dict[str, float]]:
        """Build channel-to-channel transition probability matrix."""
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for journey in self.journeys:
            if not journey:
                continue
            # Start → first channel
            counts["(start)"][journey[0]] += 1
            # Channel → channel transitions
            for i in range(len(journey) - 1):
                counts[journey[i]][journey[i + 1]] += 1
            # Last channel → conversion or null
            counts[journey[-1]]["(conversion)"] += 1

        # Normalize rows to probabilities
        probs: dict[str, dict[str, float]] = {}
        for from_ch, to_counts in counts.items():
            total = sum(to_counts.values())
            probs[from_ch] = {to: cnt / total for to, cnt in to_counts.items()}

        return probs

    def _compute_conversion_rate(
        self, transitions: dict[str, dict[str, float]]
    ) -> float:
        """
        Compute steady-state conversion rate from transition matrix.
        Uses absorption probability: P(reach conversion | start from (start)).
        """
        channels = list({
            ch for row in transitions.values() for ch in row
            if ch not in ("(conversion)", "(null)")
        } | set(transitions.keys()) - {"(conversion)", "(null)"})

        if not channels:
            return 0.0

        n = len(channels)
        idx = {ch: i for i, ch in enumerate(channels)}

        # Build absorption probability system: (I - Q) * p = R
        # Q: transitions between transient states
        # R: absorption probabilities (to conversion)
        try:
            Q = np.zeros((n, n))
            R = np.zeros(n)

            for from_ch, to_dict in transitions.items():
                if from_ch not in idx:
                    continue
                i = idx[from_ch]
                for to_ch, prob in to_dict.items():
                    if to_ch == "(conversion)":
                        R[i] += prob
                    elif to_ch in idx:
                        Q[i, idx[to_ch]] = prob

            I = np.eye(n)
            N = np.linalg.solve(I - Q + 1e-9 * I, np.ones(n))  # Fundamental matrix
            absorption_probs = N * R

            # Conversion rate = P(start → conversion)
            start_probs = transitions.get("(start)", {})
            rate = sum(
                start_probs.get(ch, 0) * absorption_probs[idx[ch]]
                for ch in channels
                if ch in start_probs
            )
            return float(rate)
        except Exception:
            # Fallback: simple conversion rate from journeys
            return len([j for j in self.journeys if j]) / max(len(self.journeys), 1)

    def _remove_channel(
        self, transitions: dict[str, dict[str, float]], remove: str
    ) -> dict[str, dict[str, float]]:
        """Return transition matrix with a channel removed (routes to null)."""
        reduced: dict[str, dict[str, float]] = {}
        for from_ch, to_dict in transitions.items():
            if from_ch == remove:
                reduced[from_ch] = {"(null)": 1.0}
                continue
            new_row: dict[str, float] = {}
            removed_prob = to_dict.get(remove, 0)
            remaining = {k: v for k, v in to_dict.items() if k != remove}
            total_remaining = sum(remaining.values()) or 1
            for to_ch, prob in remaining.items():
                new_row[to_ch] = prob + removed_prob * (prob / total_remaining)
            reduced[from_ch] = new_row
        return reduced

    # ── Shapley value approximation ───────────────────────────────────────────

    def _shapley_approximation(self) -> dict[str, float]:
        """
        Shapley value approximation using campaign metrics.
        Credit proportional to: sqrt(conversions) × roas_score.
        This is a heuristic, not true Shapley (which requires 2^n evaluations).
        """
        scores: dict[str, float] = defaultdict(float)
        for camp in self.campaigns:
            ch = camp.get("channel", "unknown")
            conv = camp.get("conversions", 0)
            roas = camp.get("roas", 1.0) or 1.0
            # Heuristic: channels that convert more AND have better ROAS get more credit
            scores[ch] += (conv ** 0.5) * min(roas, 10)  # cap ROAS at 10x
        total = sum(scores.values()) or 1
        return {ch: round(v / total * 100, 2) for ch, v in scores.items()}

    def _fallback_by_conversions(self) -> dict[str, float]:
        """Fallback: credit by conversion count."""
        conv_by_channel: dict[str, int] = defaultdict(int)
        for c in self.campaigns:
            conv_by_channel[c.get("channel", "unknown")] += c.get("conversions", 0)
        total = sum(conv_by_channel.values()) or 1
        return {ch: round(v / total * 100, 2) for ch, v in conv_by_channel.items()}

    def _fallback_equal(self) -> dict[str, float]:
        """Fallback: equal credit to all channels."""
        channels = list({c.get("channel", "unknown") for c in self.campaigns})
        n = len(channels) or 1
        return {ch: round(100 / n, 2) for ch in channels}

    # ── Compute all models ────────────────────────────────────────────────────

    def compute_all_models(self) -> dict[str, Any]:
        """
        Run all attribution models and return comparison.

        Returns:
            {
              "last_click":   {channel: pct},
              "linear":       {channel: pct},
              "time_decay":   {channel: pct},
              "markov":       {attribution: {channel: pct}, removal_effects: {}, ...},
              "recommended":  "markov" | "time_decay",
              "insight":      str,   # Turkish interpretation
            }
        """
        last_click = self.last_click()
        linear     = self.linear()
        time_decay = self.time_decay()
        markov     = self.markov_chain()

        # Which model to recommend
        recommended = "markov" if len(self.journeys) >= 10 else "time_decay"

        # Find biggest discrepancy (where last-click misleads the most)
        markov_attr = markov.get("attribution") or {}
        discrepancy = {
            ch: abs(markov_attr.get(ch, 0) - last_click.get(ch, 0))
            for ch in set(list(markov_attr) + list(last_click))
        }
        most_undervalued = max(discrepancy, key=lambda k: discrepancy[k], default=None)

        if most_undervalued and discrepancy.get(most_undervalued, 0) > 5:
            lc_pct = last_click.get(most_undervalued, 0)
            mc_pct = markov_attr.get(most_undervalued, 0)
            direction = "daha fazla" if mc_pct > lc_pct else "daha az"
            insight = (
                f"'{most_undervalued}' kanalı son-tıklama modelinde %{lc_pct:.0f} kredi alırken "
                f"Markov modelinde %{mc_pct:.0f} alıyor — aslında {direction} katkısı var. "
                f"Bütçe dağılımını buna göre gözden geçirin."
            )
        else:
            top_ch = max(markov_attr, key=lambda k: markov_attr.get(k, 0), default="")
            insight = (
                f"En yüksek katkılı kanal: '{top_ch}' (%{markov_attr.get(top_ch, 0):.0f}). "
                f"Attribution modeli {'journey verisi ile' if self.journeys else 'tahminsel yöntemle'} hesaplandı."
            )

        return {
            "last_click":  last_click,
            "linear":      linear,
            "time_decay":  time_decay,
            "markov":      markov,
            "recommended": recommended,
            "insight":     insight,
            "journey_count": len(self.journeys),
        }
