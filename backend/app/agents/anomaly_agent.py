"""
Anomaly Detection Agent — Skill 7 of 8.

Responsibility: Detect suspicious or unusual transactions using statistical
and rule-based methods. Flags potential fraud, duplicate payments, unusually
large transactions, and irregular patterns.

Detection methods:
  1. Z-score outlier detection (amount > 3σ from category mean)
  2. Duplicate detection (same vendor + amount + date ±3 days)
  3. Round-number detection (suspiciously round large amounts)
  4. Weekend/holiday transactions for B2B categories
  5. Frequency anomaly (same vendor charged multiple times in short window)
  6. GPT-4o narrative — strategic assessment of the anomaly set

done_when: state['anomalies'] contains anomaly_list and risk_score.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)

# Thresholds
ZSCORE_THRESHOLD = 2.5        # flag if amount > mean + 2.5σ per category
MIN_SAMPLES_FOR_ZSCORE = 4    # need at least N samples to compute meaningful σ
ROUND_NUMBER_THRESHOLD = 100000  # amounts >= ₺1000 that are multiples of ₺100
DUPLICATE_WINDOW_DAYS = 3     # days to look for near-duplicate transactions
FREQUENCY_WINDOW_DAYS = 7     # days to check for same-vendor frequency spike
FREQUENCY_MAX_PER_WINDOW = 5  # more than N from same vendor in window = flag


def _parse_date(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        if isinstance(raw, datetime):
            return raw
        s = str(raw)[:19]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:len(fmt)], fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _zscore_outliers(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag transactions whose amount is > ZSCORE_THRESHOLD σ above category mean."""
    by_category: dict[str, list[dict]] = defaultdict(list)
    for tx in transactions:
        by_category[tx.get("category", "other_expense")].append(tx)

    flagged: list[dict[str, Any]] = []
    for category, txs in by_category.items():
        amounts = [t["amount_cents"] for t in txs if t.get("amount_cents", 0) > 0]
        if len(amounts) < MIN_SAMPLES_FOR_ZSCORE:
            continue
        mean = statistics.mean(amounts)
        stdev = statistics.stdev(amounts)
        if stdev == 0:
            continue
        for tx in txs:
            amt = tx.get("amount_cents", 0)
            z = (amt - mean) / stdev
            if z > ZSCORE_THRESHOLD:
                flagged.append({
                    "type": "outlier_amount",
                    "severity": "high" if z > 4 else "medium",
                    "transaction": tx,
                    "detail": (
                        f"Kategori '{category}' ortalamasından {z:.1f}σ yüksek "
                        f"(ortalama: ₺{mean/100:,.0f}, bu işlem: ₺{amt/100:,.0f})"
                    ),
                    "z_score": round(z, 2),
                })
    return flagged


def _duplicate_detection(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag near-duplicate transactions (same vendor+amount within ±3 days)."""
    flagged: list[dict[str, Any]] = []
    seen: list[dict] = []

    for tx in transactions:
        vendor = (tx.get("vendor") or "").strip().lower()
        amount = tx.get("amount_cents", 0)
        tx_date = _parse_date(tx.get("transaction_date"))

        if not vendor or not tx_date or amount == 0:
            continue

        for prev in seen:
            prev_vendor = (prev.get("vendor") or "").strip().lower()
            prev_amount = prev.get("amount_cents", 0)
            prev_date = _parse_date(prev.get("transaction_date"))

            if (
                vendor == prev_vendor
                and amount == prev_amount
                and prev_date
                and abs((tx_date - prev_date).days) <= DUPLICATE_WINDOW_DAYS
            ):
                flagged.append({
                    "type": "potential_duplicate",
                    "severity": "high",
                    "transaction": tx,
                    "detail": (
                        f"Muhtemel mükerrer ödeme: '{tx.get('vendor')}' — "
                        f"₺{amount/100:,.0f} ({DUPLICATE_WINDOW_DAYS} gün içinde)"
                    ),
                    "duplicate_of": prev,
                })
                break

        seen.append(tx)
    return flagged


def _round_number_detection(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag suspiciously round, large expense amounts."""
    flagged: list[dict[str, Any]] = []
    for tx in transactions:
        if tx.get("type") != "expense":
            continue
        amount = tx.get("amount_cents", 0)
        # Convert to full currency units for check
        amount_full = amount // 100
        if amount_full >= (ROUND_NUMBER_THRESHOLD // 100) and amount_full % 1000 == 0:
            flagged.append({
                "type": "round_number",
                "severity": "low",
                "transaction": tx,
                "detail": (
                    f"Yuvarlak büyük tutar: ₺{amount_full:,} — "
                    f"fatura veya belge kontrolü önerilir."
                ),
            })
    return flagged


def _frequency_anomaly(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag vendors who appear more than FREQUENCY_MAX_PER_WINDOW times in 7 days."""
    flagged: list[dict[str, Any]] = []
    by_vendor: dict[str, list[dict]] = defaultdict(list)

    for tx in transactions:
        vendor = (tx.get("vendor") or "").strip().lower()
        if vendor and tx.get("transaction_date"):
            by_vendor[vendor].append(tx)

    for vendor, txs in by_vendor.items():
        dates = [_parse_date(t["transaction_date"]) for t in txs]
        dates = [d for d in dates if d is not None]
        dates.sort()

        # Sliding window check
        for i, start in enumerate(dates):
            window = [d for d in dates if 0 <= (d - start).days <= FREQUENCY_WINDOW_DAYS]
            if len(window) > FREQUENCY_MAX_PER_WINDOW:
                flagged.append({
                    "type": "frequency_spike",
                    "severity": "medium",
                    "transaction": txs[i],
                    "detail": (
                        f"'{vendor}' satıcısından {len(window)} işlem "
                        f"{FREQUENCY_WINDOW_DAYS} gün içinde — alışılmadık sıklık."
                    ),
                    "vendor": vendor,
                    "count_in_window": len(window),
                })
                break  # one flag per vendor

    return flagged


def _compute_risk_score(anomalies: list[dict[str, Any]]) -> float:
    """Compute an overall risk score 0–1 based on severity distribution."""
    if not anomalies:
        return 0.0
    weights = {"high": 1.0, "medium": 0.5, "low": 0.2}
    total = sum(weights.get(a.get("severity", "low"), 0.2) for a in anomalies)
    # Normalize: 5 high-severity anomalies = risk score 1.0
    return min(1.0, round(total / 5.0, 3))


async def _generate_anomaly_narrative(
    anomalies: list[dict[str, Any]],
    risk_score: float,
    settings,
) -> str:
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=600,
        api_key=settings.openai_api_key,
    )
    if not anomalies:
        return "Anlamlı bir anomali tespit edilmedi. İşlemler normal görünüyor."

    summary_lines = [
        f"- [{a['severity'].upper()}] {a['type']}: {a['detail']}"
        for a in anomalies[:10]  # top 10
    ]
    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir iç denetçi ve CFO'sun. "
            "Aşağıdaki finansal anomali listesini incele ve "
            "yöneticiye kısa, net bir özet sun (3-5 cümle). "
            "En kritik riskleri önce belirt ve ne yapılması gerektiğini söyle. "
            "Türkçe yanıt ver."
        )),
        HumanMessage(content=(
            f"Risk Skoru: {risk_score:.0%}\n"
            f"Toplam Anomali: {len(anomalies)}\n\n"
            f"Tespitler:\n" + "\n".join(summary_lines)
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_anomaly_detection(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """
    Anomaly Detection Skill.
    done_when: state['anomalies']['risk_score'] is a float 0–1.
    """
    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(
            ok=True,
            patch={"anomalies": {"anomaly_list": [], "risk_score": 0.0, "summary": "İşlem verisi yok."}},
            confidence=1.0,
            detail="İşlem verisi yok — anomali tespiti atlandı.",
        )

    try:
        settings = get_settings()

        all_anomalies: list[dict[str, Any]] = []
        all_anomalies.extend(_zscore_outliers(transactions))
        all_anomalies.extend(_duplicate_detection(transactions))
        all_anomalies.extend(_round_number_detection(transactions))
        all_anomalies.extend(_frequency_anomaly(transactions))

        # Deduplicate by transaction id reference
        seen_ids: set[int] = set()
        unique_anomalies: list[dict[str, Any]] = []
        for a in all_anomalies:
            tx_id = id(a.get("transaction"))
            anom_type = a.get("type")
            key = (tx_id, anom_type)
            if key not in seen_ids:
                seen_ids.add(key)  # type: ignore[arg-type]
                unique_anomalies.append(a)

        risk_score = _compute_risk_score(unique_anomalies)
        narrative = await _generate_anomaly_narrative(unique_anomalies, risk_score, settings)

        high_count = sum(1 for a in unique_anomalies if a.get("severity") == "high")
        needs_review = high_count >= 2 or risk_score >= 0.6

        # Serialise anomalies (remove Python object references for JSON)
        serialised: list[dict[str, Any]] = []
        for a in unique_anomalies:
            tx = a.get("transaction", {})
            entry: dict[str, Any] = {
                "type": a.get("type"),
                "severity": a.get("severity"),
                "detail": a.get("detail"),
                "transaction_date": tx.get("transaction_date"),
                "amount_cents": tx.get("amount_cents"),
                "vendor": tx.get("vendor"),
                "category": tx.get("category"),
                "description": tx.get("description"),
            }
            if "z_score" in a:
                entry["z_score"] = a["z_score"]
            if "count_in_window" in a:
                entry["count_in_window"] = a["count_in_window"]
            serialised.append(entry)

        anomaly_result = {
            "anomaly_list": serialised,
            "anomaly_count": len(serialised),
            "high_severity_count": high_count,
            "risk_score": risk_score,
            "narrative": narrative,
        }

        confidence = 0.90 if not needs_review else 0.75

        return SkillResult(
            ok=True,
            patch={"anomalies": anomaly_result},
            confidence=confidence,
            needs_review=needs_review,
            detail=(
                f"Anomali tespiti: {len(serialised)} anomali "
                f"({high_count} yüksek), risk skoru={risk_score:.0%}"
            ),
        )
    except Exception as exc:
        logger.exception("Anomaly detection failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Anomali tespiti hatası: {exc}")
