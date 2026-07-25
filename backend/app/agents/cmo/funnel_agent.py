"""
CMO Funnel Agent -- CMO Skill 2 of 3.

Responsibility: Parse lead funnel CSV and compute stage conversion rates,
cycle time, bottleneck detection, and source attribution.

Supported CSV formats (flexible column detection):
  - HubSpot export: Lead, Stage, Source, Created Date, Close Date
  - Salesforce export: lead_id, status, lead_source, created_date, close_date
  - Generic: id/lead, stage/status, source/channel, created/date, closed/closed_date

done_when: state['funnel']['overall_conversion_rate'] is a float
"""
from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from app.agents.cmo.state import CMOState

logger = logging.getLogger(__name__)


# ── Stage normalization ───────────────────────────────────────────────────────

_STAGE_MAP = {
    # Lead / raw
    "lead": "lead", "new": "lead", "raw": "lead", "prospect": "lead",
    # MQL
    "mql": "mql", "marketing_qualified": "mql", "marketing qualified": "mql",
    "qualified": "mql", "inbound": "mql",
    # SQL
    "sql": "sql", "sales_qualified": "sql", "sales qualified": "sql",
    "opportunity": "sql", "demo": "sql", "proposal": "sql",
    # Won
    "won": "won", "closed won": "won", "closed_won": "won",
    "customer": "won", "converted": "won",
    # Lost (tracked but excluded from funnel flow)
    "lost": "lost", "closed lost": "lost", "closed_lost": "lost",
    "disqualified": "lost", "churned": "lost",
}

_STAGE_ORDER = ["lead", "mql", "sql", "won"]


def _normalize_stage(raw: str) -> str:
    return _STAGE_MAP.get(raw.strip().lower().replace("-", "_"), "lead")


# ── CSV Parser ────────────────────────────────────────────────────────────────

def _parse_funnel_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse funnel CSV -- flexible column detection."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[dict[str, Any]] = []

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            for k in (reader.fieldnames or []):
                if k.strip().lower().replace(" ", "_") == c.lower().replace(" ", "_"):
                    return k
        return None

    id_col      = _col("id", "lead_id", "contact_id", "record_id")
    stage_col   = _col("stage", "status", "lifecycle_stage", "lead_status")
    source_col  = _col("source", "lead_source", "channel", "utm_source", "origin")
    created_col = _col("created", "created_date", "date", "created_at", "lead_date")
    closed_col  = _col("closed", "closed_date", "close_date", "converted_date", "won_date")

    for i, row in enumerate(reader):
        stage_raw = row.get(stage_col) or "lead"
        stage     = _normalize_stage(stage_raw)
        source    = (row.get(source_col) or "unknown").strip().lower()
        lead_id   = row.get(id_col) or str(i + 1)

        created_dt: datetime | None = None
        closed_dt:  datetime | None = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                raw_c = (row.get(created_col) or "").strip()
                if raw_c:
                    created_dt = datetime.strptime(raw_c, fmt)
                    break
            except ValueError:
                continue
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                raw_cl = (row.get(closed_col) or "").strip()
                if raw_cl:
                    closed_dt = datetime.strptime(raw_cl, fmt)
                    break
            except ValueError:
                continue

        cycle_days: float | None = None
        if created_dt and closed_dt and closed_dt >= created_dt:
            cycle_days = (closed_dt - created_dt).days

        rows.append({
            "lead_id":    lead_id,
            "stage":      stage,
            "source":     source,
            "created_dt": created_dt,
            "closed_dt":  closed_dt,
            "cycle_days": cycle_days,
        })

    return rows


# ── Pure Calculations ─────────────────────────────────────────────────────────

def _compute_funnel_metrics(leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation -- no LLM."""
    if not leads:
        return {
            "total_leads": 0,
            "mql_count": 0,
            "sql_count": 0,
            "won_count": 0,
            "lead_to_mql_rate": 0.0,
            "mql_to_sql_rate": 0.0,
            "sql_to_won_rate": 0.0,
            "overall_conversion_rate": 0.0,
            "avg_cycle_days": 0.0,
            "by_source": {},
            "bottleneck_stage": "lead_to_mql",
            "alerts": [],
            "narrative": "",
        }

    # Stage counts -- a lead at "won" has passed through all prior stages
    stage_idx = {s: i for i, s in enumerate(_STAGE_ORDER)}

    def _reached(lead: dict, stage: str) -> bool:
        return stage_idx.get(lead["stage"], -1) >= stage_idx.get(stage, 99)

    total  = len(leads)
    mqls   = sum(1 for l in leads if _reached(l, "mql"))
    sqls   = sum(1 for l in leads if _reached(l, "sql"))
    wons   = sum(1 for l in leads if _reached(l, "won"))

    l2m = mqls / total if total > 0 else 0.0
    m2s = sqls / mqls  if mqls  > 0 else 0.0
    s2w = wons / sqls  if sqls  > 0 else 0.0
    overall = wons / total if total > 0 else 0.0

    cycle_days = [l["cycle_days"] for l in leads if l["cycle_days"] is not None]
    avg_cycle = sum(cycle_days) / len(cycle_days) if cycle_days else 0.0

    # ── Bottleneck: stage with lowest conversion ───────────────────────────────
    stage_rates = {
        "lead_to_mql": l2m,
        "mql_to_sql":  m2s,
        "sql_to_won":  s2w,
    }
    bottleneck = min(stage_rates, key=lambda k: stage_rates[k])

    # ── By source ─────────────────────────────────────────────────────────────
    src_map: dict[str, dict[str, int]] = defaultdict(
        lambda: {"leads": 0, "mqls": 0, "sqls": 0, "won": 0}
    )
    for l in leads:
        src = l["source"]
        src_map[src]["leads"] += 1
        if _reached(l, "mql"):
            src_map[src]["mqls"] += 1
        if _reached(l, "sql"):
            src_map[src]["sqls"] += 1
        if _reached(l, "won"):
            src_map[src]["won"] += 1

    by_source: dict[str, Any] = {}
    for src, counts in src_map.items():
        n = counts["leads"]
        by_source[src] = {
            **counts,
            "conversion_rate": round(counts["won"] / n, 4) if n > 0 else 0.0,
        }

    return {
        "total_leads":             total,
        "mql_count":               mqls,
        "sql_count":               sqls,
        "won_count":               wons,
        "lead_to_mql_rate":        round(l2m, 4),
        "mql_to_sql_rate":         round(m2s, 4),
        "sql_to_won_rate":         round(s2w, 4),
        "overall_conversion_rate": round(overall, 4),
        "avg_cycle_days":          round(avg_cycle, 1),
        "by_source":               by_source,
        "bottleneck_stage":        bottleneck,
        "alerts":                  [],
        "narrative":               "",
    }


def _build_funnel_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts from funnel metrics."""
    alerts: list[dict[str, str]] = []

    overall = metrics.get("overall_conversion_rate", 0.0)
    l2m     = metrics.get("lead_to_mql_rate", 0.0)
    m2s     = metrics.get("mql_to_sql_rate", 0.0)
    s2w     = metrics.get("sql_to_won_rate", 0.0)
    cycle   = metrics.get("avg_cycle_days", 0.0)
    bottleneck = metrics.get("bottleneck_stage", "")

    if overall < 0.01 and metrics.get("total_leads", 0) > 0:
        alerts.append({
            "level": "critical",
            "message": (
                f"Overall conversion rate is {overall:.1%} — "
                "less than 1% of leads become customers."
            ),
        })
    elif overall < 0.05 and metrics.get("total_leads", 0) > 0:
        alerts.append({
            "level": "high",
            "message": (
                f"Conversion rate {overall:.1%} is below 5% benchmark. "
                f"Main bottleneck: {bottleneck.replace('_', ' ')} stage."
            ),
        })

    if l2m < 0.10 and metrics.get("total_leads", 0) > 0:
        alerts.append({
            "level": "high",
            "message": (
                f"Only {l2m:.0%} of leads become MQLs. "
                "Improve lead qualification criteria or targeting."
            ),
        })

    if m2s < 0.20 and metrics.get("mql_count", 0) > 0:
        alerts.append({
            "level": "medium",
            "message": (
                f"MQL→SQL rate is {m2s:.0%}. "
                "Sales and marketing alignment needed — review MQL definition."
            ),
        })

    if s2w < 0.15 and metrics.get("sql_count", 0) > 0:
        alerts.append({
            "level": "medium",
            "message": (
                f"SQL→Won rate is {s2w:.0%}. "
                "Review sales process, pricing, or competitive positioning."
            ),
        })

    if cycle > 90 and metrics.get("won_count", 0) > 0:
        alerts.append({
            "level": "medium",
            "message": (
                f"Average sales cycle is {cycle:.0f} days. "
                "Long cycle increases churn risk and cash flow pressure."
            ),
        })

    return alerts


# ── LLM Narrative ─────────────────────────────────────────────────────────────

async def _generate_funnel_narrative(metrics: dict[str, Any], settings) -> str:
    """Optional LLM narrative -- falls back to rule-based summary."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            max_tokens=300,
            api_key=settings.openai_api_key,
        )
        overall = metrics["overall_conversion_rate"]
        bottleneck = metrics["bottleneck_stage"]
        cycle = metrics["avg_cycle_days"]
        prompt = (
            f"Lead funnel: overall_conversion={overall:.1%}, "
            f"bottleneck={bottleneck}, avg_cycle={cycle:.0f} days. "
            "Write a 2-sentence CMO-level insight on funnel health."
        )
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        return resp.content.strip()
    except Exception:
        overall    = metrics.get("overall_conversion_rate", 0.0)
        bottleneck = metrics.get("bottleneck_stage", "unknown")
        total      = metrics.get("total_leads", 0)
        won        = metrics.get("won_count", 0)
        return (
            f"{won} customers converted from {total} leads "
            f"({overall:.1%} overall rate). "
            f"Primary bottleneck is the {bottleneck.replace('_', ' ')} stage."
        )


# ── LangGraph Node ─────────────────────────────────────────────────────────────

async def run_funnel_agent(state: CMOState, config: dict) -> dict[str, Any]:
    """
    CMO Funnel Skill.
    done_when: state['funnel']['overall_conversion_rate'] is a float.
    """
    csv_text = state.get("funnel_csv") or ""

    if not csv_text.strip():
        logger.info("CMO FunnelAgent: no funnel_csv provided -- skipping")
        return {"funnel": None}

    try:
        rows    = _parse_funnel_csv(csv_text)
        metrics = _compute_funnel_metrics(rows)
        alerts  = _build_funnel_alerts(metrics)
        metrics["alerts"] = alerts

        try:
            from app.config import get_settings
            settings = get_settings()
            metrics["narrative"] = await _generate_funnel_narrative(metrics, settings)
        except Exception:
            metrics["narrative"] = ""

        logger.info(
            "CMO FunnelAgent: job=%s leads=%d won=%d conversion=%.2f%%",
            state.get("job_id"), metrics["total_leads"],
            metrics["won_count"], metrics["overall_conversion_rate"] * 100,
        )
        return {"funnel": metrics}

    except Exception as exc:
        logger.exception("CMO FunnelAgent failed for job=%s", state.get("job_id"))
        return {"funnel": None, "error": f"FunnelAgent error: {exc}"}
