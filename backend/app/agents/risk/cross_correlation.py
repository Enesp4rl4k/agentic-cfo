"""
Risk Cross-KRI Correlation Engine

Answers: "When KRI X deteriorates, which other KRIs tend to move together?"

This upgrades the Risk agent from isolated threshold monitoring to
predictive, interconnected risk intelligence.

Methods:
  1. Pearson correlation matrix across KRI values
  2. Granger-like lag correlation (does KRI A predict KRI B with delay?)
  3. Risk contagion scoring (how many other KRIs does this KRI affect?)
  4. Leading indicator detection (which KRIs change BEFORE others breach?)
  5. Risk cluster analysis (groups of correlated KRIs — one cluster = systemic risk)

Business value:
  "Cash runway (financial KRI) is strongly correlated with SLA breach rate
   (operational KRI) with a 2-month lag — operational degradation predicts
   financial stress 2 months later."

Usage:
    from app.agents.risk.cross_correlation import CrossKRIAnalyzer
    analyzer = CrossKRIAnalyzer(kri_time_series)
    result = analyzer.compute_cross_correlations()
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Minimum time series length for meaningful correlation
MIN_SERIES_LENGTH = 6


class CrossKRIAnalyzer:
    """
    Analyzes correlations and causal relationships between KRIs.

    Input: list of KRI records with time-series history.
    Each KRI should have: name, category, current_value, history (list of values)
    """

    def __init__(self, kris: list[dict[str, Any]]) -> None:
        self.kris = kris
        # Filter KRIs that have time-series history
        self.kris_with_history = [
            k for k in kris
            if len(k.get("history") or k.get("values") or []) >= MIN_SERIES_LENGTH
        ]

    def _get_series(self, kri: dict[str, Any]) -> list[float]:
        """Extract numeric time series from a KRI record."""
        hist = kri.get("history") or kri.get("values") or []
        result = []
        for v in hist:
            try:
                result.append(float(v))
            except (TypeError, ValueError):
                pass
        return result

    def correlation_matrix(self) -> dict[str, Any]:
        """
        Compute pairwise Pearson correlations between all KRI time series.

        Returns matrix and top correlated pairs.
        """
        if len(self.kris_with_history) < 2:
            return {
                "matrix": {},
                "top_pairs": [],
                "note": "Korelasyon için en az 2 KRI'nın zaman serisi gerekiyor.",
            }

        names = [k.get("name") or k.get("kri", f"KRI-{i}") for i, k in enumerate(self.kris_with_history)]
        series = [self._get_series(k) for k in self.kris_with_history]

        # Align lengths (use minimum)
        min_len = min(len(s) for s in series)
        if min_len < MIN_SERIES_LENGTH:
            return {"matrix": {}, "top_pairs": [], "note": "Yetersiz veri."}

        series = [s[-min_len:] for s in series]

        n = len(names)
        matrix: dict[str, dict[str, float]] = {}
        pairs: list[dict[str, Any]] = []

        for i in range(n):
            matrix[names[i]] = {}
            for j in range(n):
                if i == j:
                    matrix[names[i]][names[j]] = 1.0
                    continue
                try:
                    r = float(np.corrcoef(series[i], series[j])[0, 1])
                    if np.isnan(r):
                        r = 0.0
                    matrix[names[i]][names[j]] = round(r, 3)

                    if i < j and abs(r) >= 0.5:
                        pairs.append({
                            "kri_a":     names[i],
                            "kri_b":     names[j],
                            "pearson_r": round(r, 3),
                            "strength":  "güçlü" if abs(r) > 0.7 else "orta",
                            "direction": "birlikte hareket" if r > 0 else "ters yönde hareket",
                        })
                except Exception:
                    matrix[names[i]][names[j]] = 0.0

        pairs.sort(key=lambda x: -abs(x["pearson_r"]))

        return {
            "matrix":    matrix,
            "top_pairs": pairs[:10],
            "n_kris":    n,
        }

    def lag_correlation_analysis(self, max_lag: int = 3) -> list[dict[str, Any]]:
        """
        Find leading KRI indicators: does KRI A predict KRI B with a lag?

        "Cash runway (A) predicts SLA breach rate (B) with lag=2 months"
        means: when cash runway deteriorates, SLA breaches increase 2 months later.
        """
        if len(self.kris_with_history) < 2:
            return []

        names  = [k.get("name") or k.get("kri", f"KRI-{i}") for i, k in enumerate(self.kris_with_history)]
        series = [self._get_series(k) for k in self.kris_with_history]
        n      = len(names)

        leading_indicators: list[dict[str, Any]] = []

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                x = series[i]
                y = series[j]
                min_len = min(len(x), len(y))
                if min_len - max_lag < 4:
                    continue

                best_lag, best_r = 0, 0.0
                for lag in range(1, max_lag + 1):
                    x_lag = x[:min_len - lag]
                    y_fut = y[lag:min_len]
                    try:
                        r = float(np.corrcoef(x_lag, y_fut)[0, 1])
                        if not np.isnan(r) and abs(r) > abs(best_r):
                            best_lag, best_r = lag, r
                    except Exception:
                        continue

                if abs(best_r) >= 0.5:
                    leading_indicators.append({
                        "leading_kri":  names[i],
                        "lagging_kri":  names[j],
                        "lag_periods":  best_lag,
                        "correlation":  round(best_r, 3),
                        "direction":    "birlikte" if best_r > 0 else "ters",
                        "interpretation": (
                            f"'{names[i]}' kötüleşince, '{names[j]}' "
                            f"{best_lag} dönem sonra "
                            f"{'de kötüleşiyor' if best_r > 0 else 'iyileşiyor'} "
                            f"(korelasyon: {best_r:.2f})."
                        ),
                    })

        leading_indicators.sort(key=lambda x: -abs(x["correlation"]))
        return leading_indicators[:10]

    def contagion_scores(self, corr_threshold: float = 0.5) -> list[dict[str, Any]]:
        """
        Compute risk contagion score for each KRI:
        how many other KRIs does it significantly affect?

        High contagion score = systemic risk — this KRI's breach cascades broadly.
        """
        matrix_result = self.correlation_matrix()
        matrix = matrix_result.get("matrix", {})
        if not matrix:
            return []

        scores: list[dict[str, Any]] = []
        for kri_name, row in matrix.items():
            # Count correlations above threshold (excluding self)
            high_corr = [
                (other, r) for other, r in row.items()
                if other != kri_name and abs(r) >= corr_threshold
            ]
            contagion_score = len(high_corr)
            avg_corr = statistics.mean([abs(r) for _, r in high_corr]) if high_corr else 0.0

            scores.append({
                "kri":              kri_name,
                "contagion_score":  contagion_score,
                "avg_correlation":  round(avg_corr, 3),
                "affects_kris":     [other for other, _ in sorted(high_corr, key=lambda x: -abs(x[1]))[:5]],
                "risk_tier":        (
                    "sistemik" if contagion_score >= 4 else
                    "yüksek"   if contagion_score >= 2 else
                    "izole"
                ),
            })

        scores.sort(key=lambda x: -x["contagion_score"])
        return scores

    def breach_cascade_simulation(
        self,
        breached_kri: str,
        corr_threshold: float = 0.6,
    ) -> dict[str, Any]:
        """
        Simulate: if KRI X breaches, which other KRIs are likely to follow?

        Uses correlation matrix to identify cascade path.
        """
        matrix_result = self.correlation_matrix()
        matrix = matrix_result.get("matrix", {})
        if breached_kri not in matrix:
            return {"error": f"'{breached_kri}' bulunamadı."}

        # Direct cascade (1 hop)
        direct = [
            {"kri": other, "correlation": r}
            for other, r in matrix[breached_kri].items()
            if other != breached_kri and abs(r) >= corr_threshold
        ]
        direct.sort(key=lambda x: -abs(x["correlation"]))

        # Indirect cascade (2 hops)
        indirect: list[dict[str, Any]] = []
        direct_names = {d["kri"] for d in direct}
        for d in direct:
            for other, r in matrix.get(d["kri"], {}).items():
                if other != breached_kri and other not in direct_names and abs(r) >= corr_threshold:
                    indirect.append({
                        "kri":        other,
                        "via":        d["kri"],
                        "correlation": round(abs(r), 3),
                    })

        return {
            "breached_kri":    breached_kri,
            "direct_cascade":  direct[:5],
            "indirect_cascade": indirect[:5],
            "total_affected":  len(direct) + len(indirect),
            "interpretation":  (
                f"'{breached_kri}' ihlali {len(direct)} KRI'yı doğrudan "
                f"ve {len(indirect)} KRI'yı dolaylı olarak etkileyebilir."
                if direct else
                f"'{breached_kri}' diğer KRI'larla güçlü korelasyon göstermiyor."
            ),
        }

    def compute_cross_correlations(self) -> dict[str, Any]:
        """
        Full cross-KRI analysis suite.

        Returns:
            {
              "correlation_matrix": {...},
              "leading_indicators": [...],
              "contagion_scores":   [...],
              "systemic_risks":     [...],  # KRIs with high contagion
              "summary":            str,
            }
        """
        corr_matrix  = self.correlation_matrix()
        leading      = self.lag_correlation_analysis()
        contagion    = self.contagion_scores()
        systemic     = [c for c in contagion if c["risk_tier"] == "sistemik"]

        # Build Turkish summary
        summary_parts: list[str] = []

        if len(self.kris_with_history) < 2:
            summary_parts.append("Cross-KRI korelasyonu için yeterli zaman serisi verisi yok.")
        else:
            top_pairs = corr_matrix.get("top_pairs") or []
            if top_pairs:
                p = top_pairs[0]
                summary_parts.append(
                    f"En güçlü KRI bağlantısı: '{p['kri_a']}' ↔ '{p['kri_b']}' "
                    f"(r={p['pearson_r']}, {p['direction']})."
                )

            if leading:
                l = leading[0]
                summary_parts.append(l["interpretation"])

            if systemic:
                names_str = ", ".join(f"'{s['kri']}'" for s in systemic[:3])
                summary_parts.append(
                    f"Sistemik risk KRI'ları (yüksek bulaşıcılık): {names_str}. "
                    "Bu KRI'ların ihlali zincirleme etki yaratabilir."
                )

        return {
            "correlation_matrix": corr_matrix,
            "leading_indicators": leading,
            "contagion_scores":   contagion,
            "systemic_risks":     systemic,
            "kris_analyzed":      len(self.kris_with_history),
            "summary":            " ".join(summary_parts) or "Yeterli KRI zaman serisi verisi yok.",
        }
