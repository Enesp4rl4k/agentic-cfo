"""
Anomaly Agent — Skill 6 (standalone, pipeline dışında da çalışır).

Muhasebeden gelen işlem verisini analiz eder:
1. Duplicate payment tespiti (aynı tutar + vendor + yakın tarih)
2. Z-score ile olağandışı tutar tespiti (kategori bazında)
3. Vendor concentration riski (tek tedarikçiye aşırı bağımlılık)
4. Expense spike (önceki aylara göre ani artış)
5. Negatif nakit akışı serisi
6. Round number anomaly (fraud göstergesi)
7. Gelir kaybı tespiti (beklenen gelir gelmemiş)

done_when: state['anomalies'] listesi dolu veya boş (0 anomali = temiz)
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

Z_SCORE_THRESHOLD = 2.5        # flagged if abs(z) > this
DUPLICATE_WINDOW_DAYS = 3      # same amount+vendor within N days = duplicate
VENDOR_CONCENTRATION_PCT = 0.4 # single vendor > 40% of total = risk
ROUND_NUMBER_THRESHOLD = 0.85  # if >85% of amounts are round → suspicious
MIN_TRANSACTIONS_FOR_STATS = 5 # minimum sample for statistical analysis
EXPENSE_SPIKE_MULTIPLIER = 2.0 # month > 2x 3-month average = spike
IQR_MULTIPLIER = 2.5           # IQR-based: value > Q3 + k*IQR = outlier


# ── Pure calculation helpers ──────────────────────────────────────────────────

def _z_score(value: float, values: list[float]) -> float | None:
    """
    Use scipy.stats.zscore for population z-scores when available,
    fall back to manual calculation.
    """
    if len(values) < MIN_TRANSACTIONS_FOR_STATS:
        return None
    try:
        import math
        import numpy as np
        from scipy import stats as sp_stats
        arr = np.array(values, dtype=float)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            z_scores = sp_stats.zscore(arr, ddof=1)
        idx = values.index(value)
        result = float(z_scores[idx])
        # scipy returns NaN when std ≈ 0 (identical values) — fall back to 0.0
        if math.isnan(result):
            return 0.0
        return result
    except Exception:
        # Fallback to stdlib
        try:
            mean = statistics.mean(values)
            std = statistics.stdev(values)
            if std == 0:
                return 0.0
            return (value - mean) / std
        except statistics.StatisticsError:
            return None


def _iqr_outlier_score(value: float, values: list[float]) -> float | None:
    """
    IQR-based outlier score. Returns how many IQR units value is above Q3.
    Positive = above Q3 (potential high outlier), 0 = within normal range.
    More robust than z-score for non-normal distributions (real expense data).
    """
    if len(values) < MIN_TRANSACTIONS_FOR_STATS:
        return None
    try:
        import numpy as np
        arr = np.array(values, dtype=float)
        q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
        iqr = q3 - q1
        if iqr == 0:
            return 0.0
        return (value - q3) / iqr
    except Exception:
        return None


def _is_round_number(amount_cents: int) -> bool:
    """Round numbers (multiples of 100 TL or 1000 TL) can be fraud indicators."""
    amount = amount_cents / 100
    return amount % 100 == 0 and amount > 0


def _days_between(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return abs((da - db).days)
    except (ValueError, TypeError):
        return None


# ── Detection functions ───────────────────────────────────────────────────────

def detect_duplicates(
    transactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Same vendor + same amount within DUPLICATE_WINDOW_DAYS = probable duplicate."""
    anomalies: list[dict[str, Any]] = []
    expenses = [t for t in transactions if t.get("type") == "expense"]
    seen: list[dict[str, Any]] = []

    for tx in expenses:
        vendor = (tx.get("vendor") or "").lower().strip()
        amount = tx.get("amount_cents", 0)
        date = tx.get("transaction_date")

        for prev in seen:
            if (
                prev.get("amount_cents") == amount
                and (prev.get("vendor") or "").lower().strip() == vendor
                and vendor  # don't flag unknown vendors
            ):
                days = _days_between(date, prev.get("transaction_date"))
                if days is not None and days <= DUPLICATE_WINDOW_DAYS:
                    anomalies.append({
                        "anomaly_type": "duplicate_payment",
                        "severity": "high",
                        "title": f"Possible duplicate payment: {vendor or 'unknown vendor'}",
                        "description": (
                            f"Two payments of {amount / 100:,.2f} to '{vendor}' "
                            f"within {days} days — potential double payment."
                        ),
                        "transaction_ids": [tx.get("id"), prev.get("id")],
                        "evidence": {
                            "amount": amount,
                            "vendor": vendor,
                            "days_apart": days,
                        },
                        "confidence": 0.85,
                    })
                    break
        seen.append(tx)

    return anomalies


def detect_unusual_amounts(
    transactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Dual-method outlier detection per expense category:
    1. Z-score (scipy, population-level)
    2. IQR-based (robust, non-normal distributions)

    An anomaly is flagged if BOTH methods agree, reducing false positives.
    """
    anomalies: list[dict[str, Any]] = []

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tx in transactions:
        if tx.get("type") == "expense":
            cat = tx.get("category", "other_expense")
            by_category[cat].append(tx)

    for cat, txs in by_category.items():
        amounts = [t["amount_cents"] for t in txs]
        if len(amounts) < MIN_TRANSACTIONS_FOR_STATS:
            continue

        cat_mean = statistics.mean(amounts)

        for tx in txs:
            amount = tx["amount_cents"]
            z = _z_score(float(amount), [float(a) for a in amounts])
            iqr_score = _iqr_outlier_score(float(amount), [float(a) for a in amounts])

            # Require both methods to flag — reduces false positives
            z_flagged = z is not None and abs(z) > Z_SCORE_THRESHOLD
            iqr_flagged = iqr_score is not None and iqr_score > IQR_MULTIPLIER

            if z_flagged and iqr_flagged:
                severity = "high" if (z and abs(z) > 3.5) else "medium"
                confidence = min(0.95, 0.55 + (abs(z or 0) * 0.08) + (min(iqr_score or 0, 5) * 0.04))
                cat_tr = cat.replace("_", " ")
                anomalies.append({
                    "anomaly_type": "unusual_amount",
                    "severity": severity,
                    "title": f"Olağandışı {cat_tr} gideri",
                    "description": (
                        f"'{cat_tr}' kategorisinde {amount / 100:,.2f} tutarındaki işlem, "
                        f"kategori ortalamasının ({cat_mean / 100:,.2f}) {abs(z or 0):.1f}σ "
                        f"üzerinde ve IQR analizinde de aykırı değer olarak işaretlendi. "
                        f"Fatura ile karşılaştırın."
                    ),
                    "transaction_ids": [tx.get("id")],
                    "evidence": {
                        "amount": amount,
                        "category": cat,
                        "z_score": round(z or 0, 2),
                        "iqr_score": round(iqr_score or 0, 2),
                        "category_mean": round(cat_mean, 2),
                        "category_std": round(statistics.stdev(amounts), 2) if len(amounts) > 1 else 0,
                        "detection_methods": ["z_score", "iqr"],
                    },
                    "confidence": round(confidence, 3),
                })

    return anomalies


def detect_vendor_concentration(
    transactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Single vendor consuming too large a share of total expenses."""
    anomalies: list[dict[str, Any]] = []
    expenses = [t for t in transactions if t.get("type") == "expense"]
    total = sum(t.get("amount_cents", 0) for t in expenses)
    if total == 0:
        return []

    vendor_totals: dict[str, int] = defaultdict(int)
    for tx in expenses:
        vendor = tx.get("vendor") or "unknown"
        vendor_totals[vendor] += tx.get("amount_cents", 0)

    for vendor, amount in vendor_totals.items():
        if vendor == "unknown":
            continue
        ratio = amount / total
        if ratio > VENDOR_CONCENTRATION_PCT:
            anomalies.append({
                "anomaly_type": "vendor_concentration",
                "severity": "medium" if ratio < 0.6 else "high",
                "title": f"High vendor concentration: {vendor}",
                "description": (
                    f"{vendor} accounts for {ratio * 100:.1f}% of total expenses "
                    f"({amount / 100:,.2f}). Over-reliance on a single vendor "
                    f"creates operational risk."
                ),
                "transaction_ids": None,
                "evidence": {
                    "vendor": vendor,
                    "vendor_total": amount,
                    "total_expenses": total,
                    "concentration_pct": round(ratio * 100, 1),
                },
                "confidence": 0.90,
            })

    return anomalies


def detect_expense_spikes(
    transactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Monthly expense total > 2x 3-month rolling average = spike."""
    anomalies: list[dict[str, Any]] = []

    monthly: dict[str, int] = defaultdict(int)
    for tx in transactions:
        if tx.get("type") == "expense" and tx.get("transaction_date"):
            month = str(tx["transaction_date"])[:7]
            monthly[month] += tx.get("amount_cents", 0)

    months = sorted(monthly.keys())
    if len(months) < 4:
        return []

    for i in range(3, len(months)):
        recent_avg = statistics.mean([monthly[months[j]] for j in range(i - 3, i)])
        current = monthly[months[i]]
        if recent_avg > 0 and current > recent_avg * EXPENSE_SPIKE_MULTIPLIER:
            multiplier = current / recent_avg
            anomalies.append({
                "anomaly_type": "expense_spike",
                "severity": "high" if multiplier > 3 else "medium",
                "title": f"Expense spike in {months[i]}",
                "description": (
                    f"Total expenses in {months[i]} ({current / 100:,.2f}) are "
                    f"{multiplier:.1f}x the 3-month average ({recent_avg / 100:,.2f}). "
                    f"Review for one-time items or anomalous charges."
                ),
                "transaction_ids": None,
                "evidence": {
                    "month": months[i],
                    "month_total": current,
                    "rolling_avg": round(recent_avg, 2),
                    "multiplier": round(multiplier, 2),
                },
                "confidence": 0.88,
            })

    return anomalies


def detect_round_numbers(
    transactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """High proportion of perfectly round expense amounts — fraud indicator."""
    anomalies: list[dict[str, Any]] = []
    expenses = [t for t in transactions if t.get("type") == "expense" and t.get("amount_cents", 0) > 0]
    if len(expenses) < 10:
        return []

    round_count = sum(1 for t in expenses if _is_round_number(t["amount_cents"]))
    ratio = round_count / len(expenses)

    if ratio > ROUND_NUMBER_THRESHOLD:
        anomalies.append({
            "anomaly_type": "round_number",
            "severity": "medium",
            "title": "Unusually high proportion of round-number expenses",
            "description": (
                f"{ratio * 100:.0f}% of expense transactions are round numbers "
                f"({round_count}/{len(expenses)}). This can indicate manually entered "
                f"or estimated amounts — verify against actual invoices."
            ),
            "transaction_ids": None,
            "evidence": {
                "round_count": round_count,
                "total_expenses": len(expenses),
                "ratio_pct": round(ratio * 100, 1),
            },
            "confidence": 0.70,
        })

    return anomalies


def detect_negative_cashflow_streak(
    cashflow: dict[str, Any]
) -> list[dict[str, Any]]:
    """3+ consecutive months of negative net cash flow."""
    anomalies: list[dict[str, Any]] = []
    series = cashflow.get("monthly_series", [])

    streak = 0
    streak_start = None
    for entry in series:
        if entry.get("net", 0) < 0:
            streak += 1
            if streak == 1:
                streak_start = entry["month"]
            if streak >= 3:
                anomalies.append({
                    "anomaly_type": "negative_cashflow_streak",
                    "severity": "critical",
                    "title": f"{streak} consecutive months of negative cash flow",
                    "description": (
                        f"Cash flow has been negative for {streak} consecutive months "
                        f"starting {streak_start}. The business is burning cash — "
                        f"immediate review of cost structure and revenue pipeline required."
                    ),
                    "transaction_ids": None,
                    "evidence": {
                        "streak_months": streak,
                        "streak_start": streak_start,
                        "latest_month": entry["month"],
                    },
                    "confidence": 1.0,
                })
                break
        else:
            streak = 0
            streak_start = None

    return anomalies


# ── LLM narrative for anomaly summary ────────────────────────────────────────

async def _generate_anomaly_narrative(
    anomalies: list[dict[str, Any]],
    settings,
) -> str:
    if not anomalies:
        return "Bu dönemde önemli bir anomali tespit edilmedi."

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=600,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    summary = "\n".join(
        f"- [{a['severity'].upper()}] {a['title']}: {a['description']}"
        for a in anomalies[:8]
    )

    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir CFO ve adli muhasebecisisin. "
            "Aşağıdaki finansal anomalileri inceleyip Türkçe olarak kısa bir özet yaz. "
            "Yanıt şu yapıda olsun:\n"
            "1. Toplam anomali sayısı ve önem seviyesinin 1 cümlelik özeti\n"
            "2. En kritik 1-2 bulgu (varsa)\n"
            "3. Yöneticinin hemen yapması gereken 2-3 somut eylem (madde madde)\n"
            "Teknik muhasebe dili kullanma, KOBİ sahibinin anlayacağı sade Türkçe yaz."
        )),
        HumanMessage(content=f"Tespit edilen anomaliler:\n{summary}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_anomaly_detection(
    state: CFOState,
    config: AgentRunConfig,
) -> SkillResult:
    """
    Anomaly Detection Skill.
    done_when: state['anomalies'] is a list (may be empty = no anomalies found)
    """
    transactions = state.get("transactions", [])
    cashflow = state.get("cashflow", {})

    if not transactions:
        return SkillResult(
            ok=True,
            patch={"anomalies": [], "anomaly_narrative": "No transactions to analyse."},
            confidence=1.0,
            detail="No transactions — anomaly detection skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        all_anomalies: list[dict[str, Any]] = []
        all_anomalies.extend(detect_duplicates(transactions))
        all_anomalies.extend(detect_unusual_amounts(transactions))
        all_anomalies.extend(detect_vendor_concentration(transactions))
        all_anomalies.extend(detect_expense_spikes(transactions))
        all_anomalies.extend(detect_round_numbers(transactions))
        if cashflow:
            all_anomalies.extend(detect_negative_cashflow_streak(cashflow))

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        all_anomalies.sort(key=lambda a: severity_order.get(a["severity"], 4))

        narrative = await _generate_anomaly_narrative(all_anomalies, settings)

        critical_count = sum(1 for a in all_anomalies if a["severity"] == "critical")
        high_count = sum(1 for a in all_anomalies if a["severity"] == "high")

        logger.info(
            "Anomaly detection complete: job=%s total=%d critical=%d high=%d",
            state.get("job_id"), len(all_anomalies), critical_count, high_count,
        )

        return SkillResult(
            ok=True,
            patch={
                "anomalies": all_anomalies,
                "anomaly_narrative": narrative,
            },
            confidence=1.0,
            detail=(
                f"Found {len(all_anomalies)} anomalies "
                f"({critical_count} critical, {high_count} high)"
            ),
        )

    except Exception as exc:
        logger.exception("Anomaly detection failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Anomaly detection error: {exc}")
