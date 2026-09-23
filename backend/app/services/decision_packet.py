"""Karar Paketi — the review moment, assembled from engines that already
exist (DDIA Ch.10: compose what you have, don't rebuild it).

A manager arriving at `awaiting_review` used to get findings and a list of
links that sent them *out of the page* to run simulations one by one. The
packet answers the four questions asked before anyone signs:

  1. Ne oldu?          → situation: the report's own numbers, anomalies,
                         and how low the confidence gate ran.
  2. Hangi seçenekler  → the three preset counterfactuals, each with its
     ve sonuçları?       *computed* 12-month effect — plus a "do nothing"
                         baseline, because a trade-off needs a reference.
  3. Veri ne taze?     → freshness: real as-of taken from the sources
                         themselves (file date, covered transaction range,
                         connector/ERP sync timestamps), never invented.
  4. Geçmişte ne       → precedent: this organisation's recorded board
     oldu?                decisions and how many actions are still open.

Deliberate properties:
  - Deterministic: no LLM in the packet path — fast, testable, and it
    cannot hallucinate a number the manager is about to act on.
  - Degrades, never fails: evidence (RAG) is best-effort; a missing report
    yields an empty options list with the freshness strip still honest.
  - One definition of the numbers: `load_pnl_cashflow_forecast` is shared
    with the simulate endpoints, so the packet and a deep-dive simulation
    can never read different reports.

Money fields follow the report's convention — kuruş (integer minor unit);
the UI divides. Timestamps are UTC; age maths live in `services/freshness.py`,
which normalises SQLite's naive datetimes before any comparison.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob
from app.services.forecast_backtest import build_backtest
from app.services.freshness import collect_freshness

logger = logging.getLogger(__name__)

# Job states where there is nothing to decide yet (the pipeline is mid-run).
RUNNING_STATUSES = frozenset({"pending", "ingesting", "analyzing"})


# ── Unit boundary: the stored report is lira, this path is kuruş ─────────────
# `report_agent._build_dashboard_json` divides every scalar money figure by
# 100 (`_fmt`: pipeline cents → lira; pinned by
# tests/test_agents/test_report_agent.py::test_cashflow_net_change_converted),
# while everything downstream — the panel's `fmtTL`, the counterfactual
# engine's own `/100`, the decision ledger's `expected` snapshot — is written
# against kuruş. The conversion happens exactly once, here. Series arrays
# (`monthly_series`, scenario `months`) are raw pipeline cents already and
# pass through untouched, as do ratios (margins) and month counts.

_PNL_MONEY_KEYS = ("revenue", "cogs", "gross_profit", "ebitda", "net_income", "total_opex")
_CF_MONEY_KEYS = ("operating", "investing", "financing", "net_change")


def _x100(value: Any) -> Any:
    """Lira figure → kuruş; anything that isn't a number passes through."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(value * 100)


def _pnl_to_kurus(pnl: dict[str, Any]) -> dict[str, Any]:
    out = dict(pnl)
    for key in _PNL_MONEY_KEYS:
        if key in out:
            out[key] = _x100(out[key])
    opex = out.get("opex")
    if isinstance(opex, dict):
        out["opex"] = {k: _x100(v) for k, v in opex.items()}
    return out


def _cashflow_to_kurus(cashflow: dict[str, Any]) -> dict[str, Any]:
    out = dict(cashflow)
    for key in _CF_MONEY_KEYS:
        if key in out:
            out[key] = _x100(out[key])
    return out


def _forecast_to_kurus(forecast: dict[str, Any]) -> dict[str, Any]:
    out = dict(forecast)
    scenarios = out.get("scenarios")
    if isinstance(scenarios, dict):
        converted: dict[str, Any] = {}
        for name, scenario in scenarios.items():
            if isinstance(scenario, dict) and "twelve_month_net" in scenario:
                scenario = {**scenario, "twelve_month_net": _x100(scenario["twelve_month_net"])}
            converted[name] = scenario
        out["scenarios"] = converted
    return out


# ── Report access (shared with api/counterfactual) ───────────────────────────

async def load_pnl_cashflow_forecast(
    db: AsyncSession, job_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Latest JSON report for a job → (pnl, cashflow, forecast) in **kuruş**.

    Moved out of `api/counterfactual` so the packet and the simulate
    endpoints read the *same* report — one definition of "the numbers".
    The stored report is lira; money fields are normalised to kuruş at
    this boundary (see the unit note above).
    """
    from app.models.report import Report, ReportFormat

    result = await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    rep = result.scalar_one_or_none()
    if not rep or not rep.data:
        return {}, {}, {}
    d = rep.data
    return (
        _pnl_to_kurus(d.get("pnl") or {}),
        _cashflow_to_kurus(d.get("cashflow") or {}),
        _forecast_to_kurus(d.get("forecast") or {}),
    )




# ── Situation ────────────────────────────────────────────────────────────────

async def build_situation(
    db: AsyncSession,
    job: AnalysisJob,
    pnl: dict[str, Any],
    cashflow: dict[str, Any],
    forecast: dict[str, Any],
) -> dict[str, Any]:
    """The numbers the decision hangs on — straight from the report.

    Keys mirror the report's own schema (money in kuruş); absent data is
    reported as None/0 rather than guessed, so the UI can render "yok"
    instead of a fabricated figure.
    """
    from app.models.anomaly import Anomaly

    opex = pnl.get("opex") or {}
    top_cat = max(opex, key=lambda k: opex[k], default=None)
    base = (forecast.get("scenarios") or {}).get("base") or {}
    anomaly_count = (
        await db.execute(
            select(func.count(Anomaly.id)).where(Anomaly.job_id == job.id)
        )
    ).scalar_one()

    return {
        "revenue_12m": int(pnl.get("revenue") or 0),
        "net_margin": pnl.get("net_margin"),
        "net_change_12m": int(cashflow.get("net_change") or 0),
        "top_opex_category": top_cat,
        "top_opex_amount": int(opex.get(top_cat)) if top_cat else None,
        "runway_months": base.get("runway_months"),
        "forecast_12m_net": base.get("twelve_month_net"),
        "anomaly_count": int(anomaly_count),
        "min_confidence": (
            float(job.min_confidence) if job.min_confidence is not None else None
        ),
    }


# ── Options ──────────────────────────────────────────────────────────────────

def build_preset_options(
    pnl: dict[str, Any],
    cashflow: dict[str, Any],
    forecast: dict[str, Any],
) -> list[dict[str, Any]]:
    """Baseline + the three presets, each with its computed consequence.

    The baseline ("do nothing") is not decoration: without it, every
    option looks either good or bad in isolation. Trade-offs need the
    reference the forecast already provides.
    """
    if not pnl:
        return []

    from app.services.counterfactual_engine import (
        CounterfactualEngine,
        compute_preset_results,
    )

    engine = CounterfactualEngine(pnl=pnl, cashflow=cashflow, forecast=forecast)
    options: list[dict[str, Any]] = [
        {
            "id": "baseline",
            "label": "Hiçbir şey yapma",
            "description": (
                "Mevcut planla devam et: baz senaryo tahmini olduğu gibi "
                "geçerli kalır."
            ),
            "baseline": True,
            "base_net_impact": 0,
            "breakeven_months": None,
            "cashflow_risk": None,
            "runway_after": engine.runway_months,
            "assumptions": ["Gelir ve gider eğilimleri değişmez (baz senaryo)"],
            "recommendation": None,
            "engine": "forecast",
            "scenarios": [],
        }
    ]

    for i, (label, result) in enumerate(compute_preset_results(pnl, cashflow, forecast)):
        d = result.to_dict()
        options.append(
            {
                "id": f"preset_{i + 1}",
                "label": label,
                "description": d["description"],
                "baseline": False,
                # The engine does not model runway-after, and inventing one
                # would be the exact failure this packet exists to prevent.
                "runway_after": None,
                "base_net_impact": d["base_net_impact"],
                "breakeven_months": d["breakeven_months"],
                "cashflow_risk": d["cashflow_risk"],
                "assumptions": d["assumptions"],
                "recommendation": d["recommendation"],
                "engine": "counterfactual",
                "scenarios": d["scenarios"],
            }
        )
    return options


# ── Precedent ────────────────────────────────────────────────────────────────

async def build_precedent(db: AsyncSession, job: AnalysisJob) -> dict[str, Any]:
    """This org's recorded decisions + open actions.

    Two memories, newest first: the DB decision ledger (the real one,
    with the outcome it later measured) and the file-backed boardroom
    convenience. Each degrades on its own — a read failure yields "no
    precedent from that source", never a dead packet.
    """
    empty: dict[str, Any] = {"decisions": [], "pending_actions": 0}
    if not job.org_id:
        return empty

    ledger: list[dict[str, Any]] = []
    try:
        from app.models.decision_log import DecisionLog

        rows = (
            await db.execute(
                select(DecisionLog)
                .where(DecisionLog.org_id == job.org_id)
                .order_by(desc(DecisionLog.created_at))
                .limit(3)
            )
        ).scalars().all()
        ledger = [
            {
                "id": r.id,
                "topic": r.topic,
                "final_decision": r.chosen_option_label,
                "resolution_status": r.status,
                # The ledger does not pretend a confidence it never computed.
                "confidence_score": None,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("Decision packet: decision ledger unavailable: %s", exc)

    boardroom: list[dict[str, Any]] = []
    pending_actions = 0
    try:
        from app.services.negotiation.boardroom_memory import get_boardroom_memory

        memory = get_boardroom_memory()
        boardroom = memory.list_recent_decisions(job.org_id, max_records=3)
        pending_actions = len(memory.list_pending_actions(job.org_id))
    except Exception as exc:
        logger.debug("Decision packet: precedent unavailable: %s", exc)

    merged = sorted(
        [*ledger, *boardroom],
        key=lambda d: str(d.get("created_at") or ""),
        reverse=True,
    )[:3]
    return {"decisions": merged, "pending_actions": pending_actions}


async def build_evidence(
    db: AsyncSession, job: AnalysisJob, top_opex_category: str | None
) -> str:
    """Best-effort RAG snippets for the situation — "" on any failure."""
    if not job.org_id:
        return ""
    from app.services.rag_service import retrieve_evidence

    query = " ".join(p for p in (top_opex_category, "gider", "nakit", "gelir") if p)
    try:
        return await retrieve_evidence(
            db, org_id=job.org_id, query=query, job_id=job.id, top_k=3
        )
    except Exception as exc:
        logger.debug("Decision packet: evidence unavailable: %s", exc)
        return ""


# ── Gate ─────────────────────────────────────────────────────────────────────

def build_gate(job: AnalysisJob) -> dict[str, Any]:
    """Why a human is looking at this at all — stated, not implied."""
    held = bool(job.awaiting_review)
    return {
        "held_for_review": held,
        "min_confidence": (
            float(job.min_confidence) if job.min_confidence is not None else None
        ),
        "reason": (
            "Analiz güven eşiğinin altında sonuç üretti — insan onayı bekleniyor."
            if held
            else None
        ),
    }


# ── Assembly ─────────────────────────────────────────────────────────────────

async def build_decision_packet(db: AsyncSession, job: AnalysisJob) -> dict[str, Any]:
    """The full packet. Read-only, deterministic, safe to call repeatedly
    while the manager keeps thinking."""
    pnl, cashflow, forecast = await load_pnl_cashflow_forecast(db, job.id)
    situation = await build_situation(db, job, pnl, cashflow, forecast)
    return {
        "job_id": job.id,
        "status": str(job.status),
        "awaiting_review": bool(job.awaiting_review),
        "generated_at": datetime.now(UTC).isoformat(),
        "gate": build_gate(job),
        "situation": situation,
        "options": build_preset_options(pnl, cashflow, forecast),
        "freshness": await collect_freshness(db, job),
        "precedent": await build_precedent(db, job),
        # "Tahminleriniz tuttu mu?" — org-wide, honest about thin data.
        "calibration": await build_backtest(db, org_id=job.org_id),
        "evidence": await build_evidence(
            db, job, situation.get("top_opex_category")
        ),
    }
