"""
COO SLA Agent -- COO Skill 3 of 3.

Responsibility: Parse SLA/service delivery CSV and compute breach rates,
response/resolution times, NPS trends, and customer satisfaction metrics.

Enhancements:
- Logistic regression SLA breach prediction (pure numpy — no sklearn dependency)
- Risk scoring: hangi açık biletler SLA'yı ihlal edecek?
- Türkçe alerts and narrative
- LLM narrative in Turkish

Supported CSV formats (flexible column detection):
  - Zendesk/ServiceNow export: ticket_id, tier/priority, created, resolved,
    status, response_time_hours, resolution_time_hours, nps_score, issue_type
  - Generic: id, priority/tier, created_at, closed_at, status,
             response_hrs, resolution_hrs, nps, category

SLA Benchmarks (industry standard):
  - P1/Critical: response < 1h, resolution < 4h
  - P2/High: response < 4h, resolution < 24h
  - P3/Medium: response < 8h, resolution < 72h
  - P4/Low: response < 24h, resolution < 168h

done_when: state['sla']['sla_breach_rate'] is a float
"""
from __future__ import annotations

import csv
import io
import logging
import math
from collections import Counter
from datetime import datetime
from typing import Any

from app.agents.coo.state import COOState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SLA Thresholds (hours)
# ---------------------------------------------------------------------------

_SLA_THRESHOLDS: dict[str, dict[str, float]] = {
    "p1": {"response": 1.0,  "resolution": 4.0},
    "p2": {"response": 4.0,  "resolution": 24.0},
    "p3": {"response": 8.0,  "resolution": 72.0},
    "p4": {"response": 24.0, "resolution": 168.0},
    "critical": {"response": 1.0,  "resolution": 4.0},
    "high":     {"response": 4.0,  "resolution": 24.0},
    "medium":   {"response": 8.0,  "resolution": 72.0},
    "low":      {"response": 24.0, "resolution": 168.0},
}

_TIER_NORM = {
    "p1": "p1", "critical": "p1", "sev1": "p1", "1": "p1",
    "p2": "p2", "high": "p2", "sev2": "p2", "2": "p2",
    "p3": "p3", "medium": "p3", "sev3": "p3", "3": "p3", "moderate": "p3",
    "p4": "p4", "low": "p4", "sev4": "p4", "4": "p4",
}

_TIER_LABELS = {"p1": "P1-Kritik", "p2": "P2-Yüksek", "p3": "P3-Orta", "p4": "P4-Düşük"}


def _normalize_tier(raw: str) -> str:
    return _TIER_NORM.get(raw.strip().lower(), "p3")


# ---------------------------------------------------------------------------
# Logistic Regression (pure numpy / math — no sklearn)
# ---------------------------------------------------------------------------

def _sigmoid(z: float) -> float:
    """Numerically stable sigmoid."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def _logistic_breach_risk(
    tier: str,
    age_hours: float,
    category_breach_rate: float,
    tier_breach_rate: float,
) -> float:
    """
    Heuristic logistic model for SLA breach probability.
    Features:
      - tier_weight: P1=2.0, P2=1.5, P3=1.0, P4=0.5 (higher tier = stricter SLA)
      - age_ratio: hours elapsed / SLA resolution threshold (0-1+ ; >1 = already past deadline)
      - category_breach_rate: historical breach rate for this ticket category
      - tier_breach_rate: historical breach rate for this tier

    Coefficients learned heuristically from SLA dynamics.
    """
    tier_weights = {"p1": 2.0, "p2": 1.5, "p3": 1.0, "p4": 0.5}
    tier_w = tier_weights.get(tier, 1.0)
    sla_threshold = _SLA_THRESHOLDS.get(tier, _SLA_THRESHOLDS["p3"])["resolution"]
    age_ratio = age_hours / max(sla_threshold, 0.1)

    # Linear combination (intercept + weighted features)
    # Intercept -2.5 means baseline ~8% breach probability when all features are zero
    z = (
        -2.5
        + 1.8 * age_ratio          # age_ratio coefficient: most predictive feature
        + 0.6 * tier_w             # tier weight
        + 2.0 * category_breach_rate  # historical category breach rate
        + 1.5 * tier_breach_rate   # historical tier breach rate
    )
    return round(_sigmoid(z), 4)


def _predict_breach_risk(
    open_tickets: list[dict[str, Any]],
    category_breach_rates: dict[str, float],
    tier_breach_rates: dict[str, float],
    now: datetime,
) -> list[dict[str, Any]]:
    """Score open tickets by SLA breach probability."""
    at_risk: list[dict[str, Any]] = []
    for t in open_tickets:
        created = t.get("created_dt")
        if created is None:
            continue
        age_hrs = (now - created).total_seconds() / 3600
        cat = t.get("category", "unknown")
        tier = t.get("tier", "p3")
        cat_br = category_breach_rates.get(cat, 0.1)
        tier_br = tier_breach_rates.get(tier, 0.1)
        prob = _logistic_breach_risk(tier, age_hrs, cat_br, tier_br)

        sla_hrs = _SLA_THRESHOLDS.get(tier, _SLA_THRESHOLDS["p3"])["resolution"]
        remaining_hrs = max(0.0, sla_hrs - age_hrs)

        at_risk.append({
            "ticket_id":        t["ticket_id"],
            "tier":             tier,
            "tier_label":       _TIER_LABELS.get(tier, tier.upper()),
            "category":         cat,
            "age_hours":        round(age_hrs, 1),
            "sla_threshold_hrs": sla_hrs,
            "remaining_hrs":    round(remaining_hrs, 1),
            "breach_probability": prob,
            "risk_level": (
                "kritik" if prob >= 0.70
                else "yüksek" if prob >= 0.50
                else "orta" if prob >= 0.30
                else "düşük"
            ),
        })

    # Sort by breach probability descending
    at_risk.sort(key=lambda x: x["breach_probability"], reverse=True)
    return at_risk


# ---------------------------------------------------------------------------
# Parse datetime
# ---------------------------------------------------------------------------

def _parse_datetime(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------

def _parse_sla_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse SLA CSV -- flexible column detection."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[dict[str, Any]] = []

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            for k in (reader.fieldnames or []):
                if k.strip().lower().replace(" ", "_").replace("-", "_") == \
                   c.lower().replace(" ", "_"):
                    return k
        return None

    id_col         = _col("id", "ticket_id", "issue_id", "case_id", "record_id")
    tier_col       = _col("tier", "priority", "severity", "sla_tier", "level")
    created_col    = _col("created", "created_at", "created_date", "open_date", "date")
    resolved_col   = _col("resolved", "closed_at", "resolved_at", "close_date",
                          "resolution_date", "closed")
    response_col   = _col("response_time_hours", "response_hrs", "first_response",
                          "response_time", "time_to_first_response")
    resolution_col = _col("resolution_time_hours", "resolution_hrs",
                          "resolution_time", "time_to_resolve", "ttfr")
    nps_col        = _col("nps", "nps_score", "satisfaction", "csat", "rating")
    category_col   = _col("category", "issue_type", "type", "topic", "subject_area")
    status_col     = _col("status", "state", "ticket_status")

    for i, row in enumerate(reader):
        tier       = _normalize_tier(row.get(tier_col) or "p3")
        category   = (row.get(category_col) or "unknown").strip().lower()
        status_raw = (row.get(status_col) or "resolved").strip().lower()
        status     = "resolved" if status_raw in ("resolved", "closed", "done", "fixed") else "open"

        response_hrs   = None
        resolution_hrs = None
        nps            = None
        created_dt     = None

        try:
            response_hrs = float((row.get(response_col) or "").replace(",", ""))
        except (ValueError, TypeError):
            pass

        try:
            resolution_hrs = float((row.get(resolution_col) or "").replace(",", ""))
        except (ValueError, TypeError):
            pass

        # Calculate from timestamps if not directly available
        created_raw  = row.get(created_col) or "" if created_col else ""
        resolved_raw = row.get(resolved_col) or "" if resolved_col else ""
        created_dt   = _parse_datetime(created_raw) if created_raw else None

        if response_hrs is None or resolution_hrs is None:
            resolved_dt = _parse_datetime(resolved_raw) if resolved_raw else None
            if created_dt and resolved_dt and resolved_dt >= created_dt:
                diff_hrs = (resolved_dt - created_dt).total_seconds() / 3600
                if resolution_hrs is None:
                    resolution_hrs = diff_hrs
                if response_hrs is None:
                    response_hrs = diff_hrs * 0.1  # heuristic: 10% of resolution time

        try:
            nps_raw = float((row.get(nps_col) or "").replace(",", "")) if nps_col else None
            if nps_raw is not None:
                nps = max(-100.0, min(100.0, nps_raw))
        except (ValueError, TypeError):
            pass

        ticket_id = (row.get(id_col) or str(i + 1)) if id_col else str(i + 1)

        rows.append({
            "ticket_id":      ticket_id,
            "tier":           tier,
            "status":         status,
            "response_hrs":   response_hrs,
            "resolution_hrs": resolution_hrs,
            "nps":            nps,
            "category":       category,
            "created_dt":     created_dt,
        })

    return rows


# ---------------------------------------------------------------------------
# Pure Calculations
# ---------------------------------------------------------------------------

def _compute_sla_metrics(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation -- no LLM."""
    if not tickets:
        return {
            "total_tickets":             0,
            "sla_breach_count":          0,
            "sla_breach_rate":           0.0,
            "avg_response_time_hours":   0.0,
            "avg_resolution_time_hours": 0.0,
            "avg_nps_score":             0.0,
            "by_tier":                   {},
            "recurring_issues":          [],
            "trend":                     "stable",
            "at_risk_tickets":           [],
            "high_risk_count":           0,
            "alerts":                    [],
            "narrative":                 "",
        }

    total    = len(tickets)
    resolved = [t for t in tickets if t["status"] == "resolved"]
    open_tix = [t for t in tickets if t["status"] == "open"]

    # Response / resolution times
    resp_times = [t["response_hrs"] for t in resolved if t["response_hrs"] is not None]
    res_times  = [t["resolution_hrs"] for t in resolved if t["resolution_hrs"] is not None]
    nps_scores = [t["nps"] for t in tickets if t["nps"] is not None]

    avg_resp = sum(resp_times) / len(resp_times) if resp_times else 0.0
    avg_res  = sum(res_times) / len(res_times) if res_times else 0.0
    avg_nps  = sum(nps_scores) / len(nps_scores) if nps_scores else 0.0

    # SLA breach detection
    breach_count = 0
    for t in resolved:
        thresholds          = _SLA_THRESHOLDS.get(t["tier"], _SLA_THRESHOLDS["p3"])
        response_breached   = (t["response_hrs"]   or 0) > thresholds["response"]
        resolution_breached = (t["resolution_hrs"] or 0) > thresholds["resolution"]
        if response_breached or resolution_breached:
            breach_count += 1

    breach_rate = breach_count / len(resolved) if resolved else 0.0

    # Category and tier historical breach rates (for prediction)
    cat_total: dict[str, int]   = Counter()
    cat_breach: dict[str, int]  = Counter()
    tier_total: dict[str, int]  = Counter()
    tier_breach: dict[str, int] = Counter()

    for t in resolved:
        cat  = t["category"]
        tier = t["tier"]
        cat_total[cat]   += 1
        tier_total[tier] += 1
        thresholds = _SLA_THRESHOLDS.get(tier, _SLA_THRESHOLDS["p3"])
        if (t["response_hrs"] or 0) > thresholds["response"] or \
           (t["resolution_hrs"] or 0) > thresholds["resolution"]:
            cat_breach[cat]   += 1
            tier_breach[tier] += 1

    category_breach_rates = {
        cat: cat_breach[cat] / max(cat_total[cat], 1)
        for cat in cat_total
    }
    tier_breach_rates = {
        tier: tier_breach[tier] / max(tier_total[tier], 1)
        for tier in tier_total
    }

    # Breach prediction for open tickets  (Python 3.11+ aware UTC)
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    at_risk = _predict_breach_risk(open_tix, category_breach_rates, tier_breach_rates, now)
    high_risk_count = sum(1 for t in at_risk if t["risk_level"] in ("kritik", "yüksek"))

    # By tier
    by_tier: dict[str, Any] = {}
    for tier_key in ["p1", "p2", "p3", "p4"]:
        tier_tickets  = [t for t in tickets if t["tier"] == tier_key]
        tier_resolved = [t for t in tier_tickets if t["status"] == "resolved"]
        if not tier_tickets:
            continue

        tier_resp = [t["response_hrs"] for t in tier_resolved if t["response_hrs"] is not None]
        tier_res  = [t["resolution_hrs"] for t in tier_resolved if t["resolution_hrs"] is not None]
        tier_breaches = sum(
            1 for t in tier_resolved
            if (t["response_hrs"] or 0) > _SLA_THRESHOLDS[tier_key]["response"]
            or (t["resolution_hrs"] or 0) > _SLA_THRESHOLDS[tier_key]["resolution"]
        )
        by_tier[tier_key] = {
            "label":            _TIER_LABELS.get(tier_key, tier_key.upper()),
            "tickets":          len(tier_tickets),
            "resolved":         len(tier_resolved),
            "breaches":         tier_breaches,
            "breach_rate":      round(tier_breaches / len(tier_resolved), 3) if tier_resolved else 0.0,
            "avg_response_hrs": round(sum(tier_resp) / len(tier_resp), 1) if tier_resp else 0.0,
            "avg_resolution_hrs": round(sum(tier_res) / len(tier_res), 1) if tier_res else 0.0,
            "sla_response_threshold":   _SLA_THRESHOLDS[tier_key]["response"],
            "sla_resolution_threshold": _SLA_THRESHOLDS[tier_key]["resolution"],
        }

    # Recurring issues (top categories)
    cat_counts = Counter(t["category"] for t in tickets)
    total_cats = sum(cat_counts.values())
    recurring_issues = [
        {"issue": cat, "count": cnt, "pct": round(cnt / total_cats * 100, 1)}
        for cat, cnt in cat_counts.most_common(5)
        if cat != "unknown"
    ]

    # Trend: compare first vs second half
    trend = "stable"
    if len(resolved) >= 10:
        mid = len(resolved) // 2
        first_half_breach = sum(
            1 for t in resolved[:mid]
            if (t["response_hrs"] or 0) > _SLA_THRESHOLDS.get(t["tier"], {}).get("response", 8)
        ) / mid
        second_half_breach = sum(
            1 for t in resolved[mid:]
            if (t["response_hrs"] or 0) > _SLA_THRESHOLDS.get(t["tier"], {}).get("response", 8)
        ) / (len(resolved) - mid)
        if second_half_breach < first_half_breach - 0.05:
            trend = "iyileşiyor"
        elif second_half_breach > first_half_breach + 0.05:
            trend = "kötüleşiyor"
        else:
            trend = "stabil"

    return {
        "total_tickets":             total,
        "resolved_tickets":          len(resolved),
        "open_tickets":              len(open_tix),
        "sla_breach_count":          breach_count,
        "sla_breach_rate":           round(breach_rate, 4),
        "avg_response_time_hours":   round(avg_resp, 2),
        "avg_resolution_time_hours": round(avg_res, 2),
        "avg_nps_score":             round(avg_nps, 1),
        "by_tier":                   by_tier,
        "recurring_issues":          recurring_issues,
        "trend":                     trend,
        "at_risk_tickets":           at_risk[:10],   # top 10 at-risk open tickets
        "high_risk_count":           high_risk_count,
        "alerts":                    [],
        "narrative":                 "",
    }


def _build_sla_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts in Turkish."""
    alerts: list[dict[str, str]] = []

    breach_rate  = metrics.get("sla_breach_rate", 0.0)
    nps          = metrics.get("avg_nps_score", 0.0)
    trend        = metrics.get("trend", "stabil")
    by_tier      = metrics.get("by_tier", {})
    at_risk      = metrics.get("at_risk_tickets", [])
    high_risk_ct = metrics.get("high_risk_count", 0)

    if breach_rate >= 0.30:
        alerts.append({
            "level": "critical",
            "message": (
                f"SLA ihlal oranı %{breach_rate:.0%} — her 3 bilettten 1'i SLA'yı aşıyor. "
                "Acil operasyonel inceleme ve kapasite artışı gerekli."
            ),
        })
    elif breach_rate >= 0.15:
        alerts.append({
            "level": "high",
            "message": (
                f"SLA ihlal oranı %{breach_rate:.0%} — %15 eşiğini aşıyor. "
                "Personel seviyesi ve eskalasyon süreçleri gözden geçirilmeli."
            ),
        })

    # P1/Critical SLA breach
    p1 = by_tier.get("p1", {})
    if p1.get("breach_rate", 0) > 0.10:
        alerts.append({
            "level": "critical",
            "message": (
                f"P1-Kritik SLA ihlal oranı %{p1['breach_rate']:.0%}. "
                "Kritik olaylar SLA içinde çözümlenemiyor — doğrudan gelir etkisi."
            ),
        })

    if high_risk_ct > 0:
        top_tix = [t["ticket_id"] for t in at_risk[:3] if t["risk_level"] in ("kritik", "yüksek")]
        alerts.append({
            "level": "high",
            "message": (
                f"Makine öğrenimi tahminleme: {high_risk_ct} açık bilet yüksek SLA ihlal riski taşıyor"
                + (f" (Bilet: {', '.join(top_tix)})" if top_tix else "")
                + ". Proaktif eskalasyon önerilir."
            ),
        })

    if nps < 0 and metrics.get("total_tickets", 0) > 0:
        alerts.append({
            "level": "high",
            "message": (
                f"NPS skoru {nps:.0f} — negatif. "
                "Müşteriler eleştirmen konumunda; churn ve olumsuz yayılım riski."
            ),
        })
    elif nps < 20 and metrics.get("total_tickets", 0) > 0:
        alerts.append({
            "level": "medium",
            "message": (
                f"NPS {nps:.0f} — 20 benchmark'ının altında. "
                "Tekrarlayan sorunları azalt ve çözüm kalitesini iyileştir."
            ),
        })

    if trend == "kötüleşiyor":
        alerts.append({
            "level": "medium",
            "message": (
                "SLA performans trendi kötüleşiyor. "
                "Son biletler önceki dönemlere kıyasla daha yüksek ihlal oranına sahip."
            ),
        })

    return alerts


# ---------------------------------------------------------------------------
# LLM Narrative (Turkish)
# ---------------------------------------------------------------------------

async def _generate_sla_narrative(metrics: dict[str, Any], settings) -> str:
    """Türkçe COO narrative — SLA ihlal tahmini bağlamıyla."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOpenAI(
            model=getattr(settings, "openai_model", "gpt-4o-mini"),
            temperature=0.2,
            max_tokens=350,
            api_key=settings.openai_api_key,
        )
        breach     = metrics["sla_breach_rate"]
        resp_time  = metrics["avg_response_time_hours"]
        nps        = metrics["avg_nps_score"]
        trend      = metrics["trend"]
        total      = metrics["total_tickets"]
        high_risk  = metrics.get("high_risk_count", 0)
        open_count = metrics.get("open_tickets", 0)

        system = (
            "Sen kurumsal servis yönetimi (ITSM) alanında uzman bir COO asistanısın. "
            "Türkçe, profesyonel ve aksiyon odaklı içgörüler yazıyorsun. "
            "SLA, NPS ve servis kalitesi metrikleri hakkında C-suite düzeyinde özet sunuyorsun."
        )
        human = (
            f"Aşağıdaki SLA performans verilerine göre Türkçe 3-4 cümlelik COO özeti yaz:\n\n"
            f"- Toplam bilet: {total} ({open_count} açık)\n"
            f"- SLA ihlal oranı: %{breach:.0%}\n"
            f"- Ortalama yanıt süresi: {resp_time:.1f} saat\n"
            f"- NPS skoru: {nps:.0f}\n"
            f"- Trend: {trend}\n"
            f"- Yüksek riskli açık bilet (tahmin): {high_risk}\n\n"
            "Mevcut servis kalitesini, ihlal risklerini ve 2 öncelikli aksiyon öner."
        )
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        return resp.content.strip()
    except Exception:
        breach = metrics.get("sla_breach_rate", 0.0)
        nps    = metrics.get("avg_nps_score", 0.0)
        total  = metrics.get("total_tickets", 0)
        high_risk = metrics.get("high_risk_count", 0)
        return (
            f"{total} bilet analiz edildi; SLA ihlal oranı %{breach:.0%}, NPS {nps:.0f}."
            + (f" {high_risk} açık bilet yüksek ihlal riski taşıyor." if high_risk else "")
        )


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------

async def run_sla_agent(state: COOState, config: dict) -> dict[str, Any]:
    """
    COO SLA Skill — with logistic regression breach prediction.
    done_when: state['sla']['sla_breach_rate'] is a float.
    """
    csv_text = state.get("sla_csv") or ""

    if not csv_text.strip():
        logger.info("COO SLAAgent: no sla_csv provided -- skipping")
        return {"sla": None}

    try:
        rows    = _parse_sla_csv(csv_text)
        metrics = _compute_sla_metrics(rows)
        alerts  = _build_sla_alerts(metrics)
        metrics["alerts"] = alerts

        try:
            from app.config import get_settings
            settings = get_settings()
            if getattr(settings, "openai_api_key", None):
                metrics["narrative"] = await _generate_sla_narrative(metrics, settings)
        except Exception:
            pass

        if not metrics.get("narrative"):
            breach    = metrics.get("sla_breach_rate", 0.0)
            nps       = metrics.get("avg_nps_score", 0.0)
            total     = metrics.get("total_tickets", 0)
            high_risk = metrics.get("high_risk_count", 0)
            metrics["narrative"] = (
                f"{total} bilet analiz edildi; SLA ihlal oranı %{breach:.0%}, NPS {nps:.0f}."
                + (f" {high_risk} açık bilet yüksek ihlal riski taşıyor." if high_risk else "")
            )

        logger.info(
            "COO SLAAgent: tickets=%d breach=%.1f%% nps=%.0f high_risk_open=%d",
            metrics["total_tickets"],
            metrics["sla_breach_rate"] * 100,
            metrics["avg_nps_score"],
            metrics.get("high_risk_count", 0),
        )
        return {"sla": metrics}

    except Exception as exc:
        logger.exception("COO SLAAgent failed for job=%s", state.get("job_id"))
        return {"sla": None, "error": f"SLAAgent error: {exc}"}
