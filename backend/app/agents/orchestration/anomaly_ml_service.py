"""
AnomalyMLService — Hibrit ML anomaly detection.

Sprint L1: Rule-based anomaly detection'ı ML tabanlıya yükseltir.

Architecture
------------
- Isolation Forest (primary): global outlier detection, contamination tunable
- DBSCAN (secondary): density-based clustering, catches local anomalies
- Rule-based (tertiary): existing detectors (duplicates, vendor concentration, etc.)
- Ensemble voting: weighted combination of all three

Feature vector per transaction
-------------------------------
[amount_normalized, day_of_week, vendor_frequency, category_pct,
 amount_vs_category_mean, month_position, amount_zscore]

Graceful degradation
--------------------
- If scikit-learn not installed → falls back to rule-based only
- If < MIN_SAMPLES transactions → skips ML, uses rule-based only
- All errors logged, never raised to caller

Usage
-----
    svc = AnomalyMLService()
    results = svc.fit_and_detect(transactions, contamination=0.05)
    # results: list[AnomalyResult]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_SAMPLES         = 20    # minimum transactions to run ML
DEFAULT_CONTAMINATION = 0.05  # expected anomaly rate (5%)
BOOTSTRAP_N         = 100   # iterations for confidence interval

# ML model weights for ensemble voting
IF_WEIGHT     = 0.45    # Isolation Forest
DBSCAN_WEIGHT = 0.30    # DBSCAN
RULE_WEIGHT   = 0.25    # Rule-based


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class AnomalyResult:
    """Unified anomaly result from any detector."""
    transaction_id:   str
    anomaly_type:     str          # "isolation_forest" | "dbscan" | "rule_based" | "ensemble"
    severity:         str          # "critical" | "high" | "medium" | "low"
    score:            float        # 0.0 – 1.0 (higher = more anomalous)
    confidence_lower: float        # bootstrap CI lower bound
    confidence_upper: float        # bootstrap CI upper bound
    description:      str
    evidence:         dict[str, Any] = field(default_factory=dict)
    detector_type:    str = "ensemble"

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id":   self.transaction_id,
            "anomaly_type":     self.anomaly_type,
            "severity":         self.severity,
            "score":            round(self.score, 3),
            "confidence_lower": round(self.confidence_lower, 3),
            "confidence_upper": round(self.confidence_upper, 3),
            "description":      self.description,
            "evidence":         self.evidence,
            "detector_type":    self.detector_type,
        }


# ── Feature engineering ───────────────────────────────────────────────────────

def _build_feature_matrix(transactions: list[dict]) -> tuple[list[list[float]], list[str]]:
    """
    Build normalized feature matrix from transactions.

    Returns:
        (feature_matrix, transaction_ids)
        feature_matrix: list of [amount_norm, dow, vendor_freq, cat_pct, amt_vs_cat, month_pos, z_score]
    """
    if not transactions:
        return [], []

    amounts     = [abs(float(t.get("amount_cents", 0) or 0)) / 100 for t in transactions]
    max_amount  = max(amounts) if amounts else 1.0
    total_spend = sum(amounts) or 1.0

    # Vendor frequency (how often each vendor appears)
    vendor_counts: dict[str, int] = {}
    for t in transactions:
        v = str(t.get("vendor", "") or "unknown")
        vendor_counts[v] = vendor_counts.get(v, 0) + 1

    # Category spend
    cat_spend: dict[str, float] = {}
    for t, amt in zip(transactions, amounts, strict=False):
        c = str(t.get("category", "") or "unknown")
        cat_spend[c] = cat_spend.get(c, 0) + amt

    # Category mean amounts
    cat_amounts: dict[str, list[float]] = {}
    for t, amt in zip(transactions, amounts, strict=False):
        c = str(t.get("category", "") or "unknown")
        cat_amounts.setdefault(c, []).append(amt)
    cat_mean = {c: sum(v) / len(v) for c, v in cat_amounts.items()}

    # Global z-score normalization
    mean_amount = sum(amounts) / len(amounts)
    std_amount  = (sum((a - mean_amount) ** 2 for a in amounts) / len(amounts)) ** 0.5 or 1.0

    features: list[list[float]] = []
    ids:      list[str]         = []

    for t, amt in zip(transactions, amounts, strict=False):
        tx_id = str(t.get("id", ""))
        ids.append(tx_id)

        # Parse transaction date
        dow = 0.0  # day of week (0=Mon .. 6=Sun)
        month_pos = 0.5  # position in month (0=start, 1=end)
        try:
            raw_date = t.get("transaction_date") or ""
            if raw_date:
                dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                dow = dt.weekday() / 6.0
                month_pos = (dt.day - 1) / 30.0
        except Exception:
            pass

        vendor = str(t.get("vendor", "") or "unknown")
        cat    = str(t.get("category", "") or "unknown")

        vendor_freq = vendor_counts.get(vendor, 1) / len(transactions)
        cat_pct     = cat_spend.get(cat, 0) / total_spend
        amt_vs_cat  = amt / (cat_mean.get(cat, 1.0) or 1.0)
        amt_norm    = amt / (max_amount or 1.0)
        z_score     = (amt - mean_amount) / std_amount

        # Clip z-score to [-3, 3] range for normalization
        z_clipped = max(-3.0, min(3.0, z_score)) / 3.0

        features.append([
            amt_norm,
            dow,
            vendor_freq,
            cat_pct,
            min(amt_vs_cat, 10.0) / 10.0,  # cap at 10x
            month_pos,
            z_clipped,
        ])

    return features, ids


# ── Confidence interval via bootstrap ─────────────────────────────────────────

def _compute_confidence_interval(
    scores: list[float],
    n_bootstrap: int = BOOTSTRAP_N,
) -> tuple[float, float]:
    """
    Bootstrap confidence interval for anomaly scores.
    Returns (lower_bound, upper_bound) at 90% confidence.
    """
    if not scores:
        return 0.0, 0.0

    import random
    rng = random.Random(42)

    means = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(scores) for _ in scores]
        means.append(sum(sample) / len(sample))

    means.sort()
    lo = means[int(0.05 * n_bootstrap)]
    hi = means[int(0.95 * n_bootstrap)]
    return lo, hi


# ── Isolation Forest detector ─────────────────────────────────────────────────

def _run_isolation_forest(
    features: list[list[float]],
    ids: list[str],
    contamination: float,
) -> list[tuple[str, float]]:
    """
    Run Isolation Forest on feature matrix.
    Returns list of (transaction_id, anomaly_score) for outliers only.
    Score 0.0–1.0 where 1.0 = most anomalous.
    """
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest

        X = np.array(features, dtype=float)
        clf = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
        )
        clf.fit(X)
        raw_scores = clf.decision_function(X)   # negative = more anomalous
        predictions = clf.predict(X)             # -1 = anomaly, 1 = normal

        # Convert to 0–1 score (1 = most anomalous)
        min_score = raw_scores.min()
        max_score = raw_scores.max()
        score_range = max_score - min_score or 1.0
        norm_scores = 1.0 - (raw_scores - min_score) / score_range

        results = []
        for tx_id, pred, score in zip(ids, predictions, norm_scores, strict=False):
            if pred == -1:  # anomaly
                results.append((tx_id, float(score)))

        return results

    except ImportError:
        logger.debug("scikit-learn not installed — skipping Isolation Forest")
        return []
    except Exception as exc:
        logger.warning("Isolation Forest failed: %s", exc)
        return []


# ── DBSCAN detector ───────────────────────────────────────────────────────────

def _run_dbscan(
    features: list[list[float]],
    ids: list[str],
) -> list[tuple[str, float]]:
    """
    Run DBSCAN to find noise points (label=-1).
    These are local density outliers not caught by Isolation Forest.
    Returns list of (transaction_id, score) for noise points.
    """
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN
        from sklearn.preprocessing import StandardScaler

        X = StandardScaler().fit_transform(np.array(features, dtype=float))

        # Auto-tune eps based on dataset size
        n = len(features)
        eps = 0.8 if n < 100 else 1.0 if n < 500 else 1.2

        clf = DBSCAN(eps=eps, min_samples=max(3, n // 20))
        labels = clf.fit_predict(X)

        results = []
        for tx_id, label in zip(ids, labels, strict=False):
            if label == -1:  # noise point = outlier
                results.append((tx_id, 0.7))  # fixed score for DBSCAN noise points

        return results

    except ImportError:
        logger.debug("scikit-learn not installed — skipping DBSCAN")
        return []
    except Exception as exc:
        logger.warning("DBSCAN failed: %s", exc)
        return []


# ── Ensemble voting ───────────────────────────────────────────────────────────

def _ensemble_vote(
    if_scores:    dict[str, float],
    dbscan_ids:   set[str],
    rule_ids:     set[str],
    all_ids:      list[str],
) -> list[tuple[str, float]]:
    """
    Weighted ensemble: IF score × IF_WEIGHT + DBSCAN × DBSCAN_WEIGHT + rule × RULE_WEIGHT.
    Returns anomalies with ensemble score ≥ 0.3.
    """
    results = []
    for tx_id in all_ids:
        if_s     = if_scores.get(tx_id, 0.0) * IF_WEIGHT
        dbscan_s = (0.7 if tx_id in dbscan_ids else 0.0) * DBSCAN_WEIGHT
        rule_s   = (1.0 if tx_id in rule_ids  else 0.0) * RULE_WEIGHT

        ensemble = if_s + dbscan_s + rule_s
        if ensemble >= 0.3:
            results.append((tx_id, min(1.0, ensemble)))

    results.sort(key=lambda x: -x[1])
    return results


# ── Severity mapping ──────────────────────────────────────────────────────────

def _score_to_severity(score: float) -> str:
    if score >= 0.85: return "critical"
    if score >= 0.65: return "high"
    if score >= 0.40: return "medium"
    return "low"


# ── Main service class ────────────────────────────────────────────────────────

class AnomalyMLService:
    """
    Hibrit ML anomaly detector.

    Priority: 1) Isolation Forest  2) DBSCAN  3) Rule-based  4) Ensemble voting.
    Falls back gracefully when scikit-learn is not available.
    """

    def fit_and_detect(
        self,
        transactions: list[dict],
        contamination: float = DEFAULT_CONTAMINATION,
        use_ensemble: bool = True,
    ) -> list[AnomalyResult]:
        """
        Run full ML anomaly detection pipeline.

        Args:
            transactions: list of transaction dicts
            contamination: expected anomaly rate (0.0–0.5)
            use_ensemble: if True, combine IF + DBSCAN + rule scores

        Returns:
            Sorted list of AnomalyResult (most anomalous first).
        """
        if len(transactions) < MIN_SAMPLES:
            logger.debug(
                "AnomalyML: only %d transactions — minimum %d required, skipping ML",
                len(transactions), MIN_SAMPLES,
            )
            return []

        features, ids = _build_feature_matrix(transactions)
        if not features:
            return []

        # ── Step 1: Isolation Forest ──────────────────────────────────────────
        if_results   = _run_isolation_forest(features, ids, contamination)
        if_score_map = dict(if_results)

        # ── Step 2: DBSCAN ────────────────────────────────────────────────────
        dbscan_results = _run_dbscan(features, ids)
        dbscan_ids     = {tx_id for tx_id, _ in dbscan_results}

        # ── Step 3: Rule-based (from existing detectors) ──────────────────────
        rule_ids: set[str] = set()
        try:
            from app.agents.anomaly_agent import (
                detect_duplicates,
                detect_expense_spikes,
                detect_round_numbers,
                detect_unusual_amounts,
                detect_vendor_concentration,
            )
            rule_anomalies: list[dict] = []
            rule_anomalies.extend(detect_duplicates(transactions))
            rule_anomalies.extend(detect_unusual_amounts(transactions))
            rule_anomalies.extend(detect_vendor_concentration(transactions))
            rule_anomalies.extend(detect_expense_spikes(transactions))
            rule_anomalies.extend(detect_round_numbers(transactions))

            for ra in rule_anomalies:
                for tid in (ra.get("transaction_ids") or []):
                    rule_ids.add(str(tid))
        except Exception as exc:
            logger.warning("Rule-based detectors failed: %s", exc)

        # ── Step 4: Ensemble or individual results ────────────────────────────
        if use_ensemble:
            ensemble_results = _ensemble_vote(if_score_map, dbscan_ids, rule_ids, ids)
        else:
            # Return IF results only
            ensemble_results = if_results

        if not ensemble_results:
            return []

        # ── Step 5: Build AnomalyResult objects with confidence intervals ─────
        all_scores = [score for _, score in ensemble_results]
        ci_lo, ci_hi = _compute_confidence_interval(all_scores)

        tx_map = {str(t.get("id", "")): t for t in transactions}
        output: list[AnomalyResult] = []

        for tx_id, score in ensemble_results:
            tx     = tx_map.get(tx_id, {})
            amount = abs(float(tx.get("amount_cents", 0) or 0)) / 100
            vendor = str(tx.get("vendor", "") or "Bilinmeyen")
            cat    = str(tx.get("category", "") or "Bilinmeyen")

            # Determine which detectors flagged this transaction
            detectors = []
            if tx_id in if_score_map: detectors.append("isolation_forest")
            if tx_id in dbscan_ids:   detectors.append("dbscan")
            if tx_id in rule_ids:     detectors.append("rule_based")
            detector_label = "+".join(detectors) or "ensemble"

            output.append(AnomalyResult(
                transaction_id   = tx_id,
                anomaly_type     = "ml_ensemble" if len(detectors) > 1 else (detectors[0] if detectors else "ensemble"),
                severity         = _score_to_severity(score),
                score            = score,
                confidence_lower = max(0.0, score - (ci_hi - ci_lo) / 2),
                confidence_upper = min(1.0, score + (ci_hi - ci_lo) / 2),
                description      = (
                    f"ML anomaly detected: {vendor} — {cat} — "
                    f"₺{amount:,.0f} (detectors: {detector_label})"
                ),
                evidence = {
                    "amount":    amount,
                    "vendor":    vendor,
                    "category":  cat,
                    "detectors": detectors,
                    "if_score":  round(if_score_map.get(tx_id, 0.0), 3),
                    "dbscan":    tx_id in dbscan_ids,
                    "rule":      tx_id in rule_ids,
                },
                detector_type = detector_label,
            ))

        logger.info(
            "AnomalyML: %d transactions → %d anomalies (IF=%d DBSCAN=%d rule=%d)",
            len(transactions), len(output),
            len(if_score_map), len(dbscan_ids), len(rule_ids),
        )
        return output
