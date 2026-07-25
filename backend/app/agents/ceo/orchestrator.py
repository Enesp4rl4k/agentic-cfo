"""
CEO Orchestrator — meta-LangGraph that runs CFO + CTO in parallel,
then synthesizes cross-domain insights.

Pipeline:
  START
  → [parallel] run_cfo  + run_cto   (asyncio.gather — both pipelines fire simultaneously)
  → condense_summaries               (extract CEO-relevant KPIs from both outputs)
  → synthesis                        (cross-domain risk correlation — rule-based, no LLM)
  → strategic_priorities             (ranked action list — rule-based + LLM enrichment)
  → board_deck                       (6-slide board presentation + one-pager)
  → END

  hold_for_review (if critical cross-risks detected)

Design notes:
- CFO and CTO pipelines are fully independent — they run in asyncio.gather
  so total runtime ≈ max(CFO_time, CTO_time), not sum.
- CEO graph is deliberately simple: 5 sequential nodes after parallel fan-in.
- "Nothing grades its own homework": synthesis is separate from board_deck.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.graph import StateGraph, END

from app.agents.ceo.state import (
    CEOState,
    CEOStepLog,
    CEOSkillResult,
    CEORunConfig,
    DEFAULT_CEO_RUN_CONFIG,
    CEO_ROUTE_HOLD,
    CEO_ROUTE_END,
)
from app.agents.ceo.synthesis_agent          import (
    run_synthesis_agent,
    _condense_financial_summary,
    _condense_tech_summary,
)
from app.agents.ceo.strategic_priorities_agent import run_strategic_priorities_agent
from app.agents.ceo.board_deck_agent           import run_board_deck_agent

logger = logging.getLogger(__name__)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _append_log(state: CEOState, log: CEOStepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    min_conf = state.get("min_confidence", 1.0)
    if log.confidence is not None:
        min_conf = min(min_conf, log.confidence)
    return {"logs": existing, "min_confidence": min_conf}


def _run_config(config: dict) -> CEORunConfig:
    return config.get("configurable", {}).get("ceo_run_config", DEFAULT_CEO_RUN_CONFIG)


# ── Nodes ──────────────────────────────────────────────────────────────────────

async def node_run_pipelines(state: CEOState, config: dict) -> CEOState:
    """
    Fan-out node: run CFO, CTO, CMO, COO, and CHRO pipelines in parallel.
    All are optional — missing inputs are handled by their respective pipelines.

    CFO supports two input modes:
      a) file-based: file_path + file_type
      b) direct JSON: transactions list (bypasses data ingestion parsing)
    """
    cfo_input  = state.get("_cfo_input") or {}
    cto_input  = state.get("_cto_input") or {}
    cmo_input  = state.get("_cmo_input") or {}
    coo_input  = state.get("_coo_input") or {}
    chro_input = state.get("_chro_input") or {}
    job_id     = state.get("job_id", "ceo-job")

    cfo_result: dict[str, Any] = {}
    cto_result: dict[str, Any] = {}
    cmo_result: dict[str, Any] = {}
    coo_result: dict[str, Any] = {}
    chro_result: dict[str, Any] = {}

    async def _run_cfo() -> None:
        nonlocal cfo_result
        if not cfo_input:
            return
        try:
            transactions = cfo_input.get("transactions")
            if transactions:
                # Direct JSON mode — bypass file parsing, inject transactions directly
                # _run_cfo_from_transactions is defined later in this same module
                cfo_result = await _run_cfo_from_transactions(
                    job_id=f"{job_id}-cfo",
                    transactions=transactions,
                    budget=cfo_input.get("budget"),
                )
            else:
                from app.agents.orchestrator import run_cfo_pipeline
                result = await run_cfo_pipeline(
                    job_id=f"{job_id}-cfo",
                    file_path=cfo_input.get("file_path", ""),
                    file_type=cfo_input.get("file_type", ""),
                    budget_input=cfo_input.get("budget"),
                )
                cfo_result = dict(result)
            logger.info("CEO: CFO pipeline finished for job=%s", job_id)
        except Exception as exc:
            logger.warning("CEO: CFO pipeline failed: %s", exc)

    async def _run_cto() -> None:
        nonlocal cto_result
        if not cto_input:
            return
        try:
            from app.agents.cto.orchestrator import run_cto_pipeline
            result = await run_cto_pipeline(
                job_id=f"{job_id}-cto",
                cloud_billing_csv=cto_input.get("cloud_billing_csv"),
                git_log_text=cto_input.get("git_log_text"),
                incident_csv=cto_input.get("incident_csv"),
                sprint_csv=cto_input.get("sprint_csv"),
            )
            cto_result = dict(result)
            logger.info("CEO: CTO pipeline finished for job=%s", job_id)
        except Exception as exc:
            logger.warning("CEO: CTO pipeline failed: %s", exc)

    async def _run_cmo() -> None:
        nonlocal cmo_result
        if not cmo_input:
            return
        try:
            from app.agents.cmo.orchestrator import run_cmo_pipeline
            result = await run_cmo_pipeline(
                campaign_csv=cmo_input.get("campaign_csv"),
                funnel_csv=cmo_input.get("funnel_csv"),
                cohort_csv=cmo_input.get("cohort_csv"),
            )
            cmo_result = dict(result)
            logger.info("CEO: CMO pipeline finished for job=%s", job_id)
        except Exception as exc:
            logger.warning("CEO: CMO pipeline failed: %s", exc)

    async def _run_coo() -> None:
        nonlocal coo_result
        if not coo_input:
            return
        try:
            from app.agents.coo.orchestrator import run_coo_pipeline
            result = await run_coo_pipeline(
                headcount_csv=coo_input.get("headcount_csv"),
                attrition_csv=coo_input.get("attrition_csv"),
                compensation_csv=coo_input.get("compensation_csv"),
            )
            coo_result = dict(result)
            logger.info("CEO: COO pipeline finished for job=%s", job_id)
        except Exception as exc:
            logger.warning("CEO: COO pipeline failed: %s", exc)

    async def _run_chro() -> None:
        nonlocal chro_result
        if not chro_input:
            return
        try:
            from app.agents.chro.orchestrator import run_chro_pipeline
            result = await run_chro_pipeline(
                headcount_csv=chro_input.get("headcount_csv"),
                attrition_csv=chro_input.get("attrition_csv"),
                compensation_csv=chro_input.get("compensation_csv"),
            )
            chro_result = dict(result)
            logger.info("CEO: CHRO pipeline finished for job=%s", job_id)
        except Exception as exc:
            logger.warning("CEO: CHRO pipeline failed: %s", exc)

    # Parallel execution
    await asyncio.gather(_run_cfo(), _run_cto(), _run_cmo(), _run_coo(), _run_chro())

    patch = _append_log(state, CEOStepLog(
        step="run_pipelines",
        ok=True,
        detail=(
            f"CFO: {'ok' if cfo_result else 'skipped'}, "
            f"CTO: {'ok' if cto_result else 'skipped'}, "
            f"CMO: {'ok' if cmo_result else 'skipped'}, "
            f"COO: {'ok' if coo_result else 'skipped'}, "
            f"CHRO: {'ok' if chro_result else 'skipped'}"
        ),
        confidence=0.95,
    ))
    patch["_cfo_result"] = cfo_result
    patch["_cto_result"] = cto_result
    patch["_cmo_result"] = cmo_result
    patch["_coo_result"] = coo_result
    patch["_chro_result"] = chro_result
    return {**state, **patch}  # type: ignore[return-value]


async def node_condense_summaries(state: CEOState, config: dict) -> CEOState:
    """Extract CEO-relevant KPIs from raw CFO/CTO/CMO/COO/CHRO pipeline outputs."""
    cfo_result = state.get("_cfo_result") or {}
    cto_result = state.get("_cto_result") or {}
    cmo_result = state.get("_cmo_result") or {}
    coo_result = state.get("_coo_result") or {}
    chro_result = state.get("_chro_result") or {}

    fin  = _condense_financial_summary(cfo_result) if cfo_result else {}
    tech = _condense_tech_summary(cto_result)      if cto_result else {}
    mkt  = _condense_marketing_summary(cmo_result) if cmo_result else {}
    ops  = _condense_ops_summary(coo_result)       if coo_result else {}
    hr   = _condense_hr_summary(chro_result)       if chro_result else {}

    patch = _append_log(state, CEOStepLog(
        step="condense_summaries",
        ok=True,
        detail=(
            f"Financial: revenue={fin.get('revenue_cents', 0)/100:,.0f} "
            f"| Tech health: {tech.get('overall_health_score', 'N/A')}/10 "
            f"| Headcount: {hr.get('total_headcount', 0)} "
            f"| Ops score: {ops.get('overall_ops_score', 'N/A')}/10"
        ),
        confidence=0.95,
    ))
    patch["financial_summary"] = fin
    patch["tech_summary"] = tech
    patch["marketing_summary"] = mkt
    patch["ops_summary"] = ops
    patch["hr_summary"] = hr
    return {**state, **patch}  # type: ignore[return-value]


async def node_synthesis(state: CEOState, config: dict) -> CEOState:
    result = await run_synthesis_agent(state, _run_config(config))
    patch = _append_log(state, CEOStepLog(
        step="synthesis", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if result.needs_review:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


async def node_strategic_priorities(state: CEOState, config: dict) -> CEOState:
    result = await run_strategic_priorities_agent(state, _run_config(config))
    patch = _append_log(state, CEOStepLog(
        step="strategic_priorities", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_board_deck(state: CEOState, config: dict) -> CEOState:
    result = await run_board_deck_agent(state, _run_config(config))
    patch = _append_log(state, CEOStepLog(
        step="board_deck", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_okr(state: CEOState, config: dict) -> CEOState:
    from app.agents.ceo.okr_agent import run_okr_agent
    return await run_okr_agent(state, config)  # type: ignore[return-value]


async def node_hold_for_review(state: CEOState, config: dict) -> CEOState:
    patch = _append_log(state, CEOStepLog(
        step="review_gate",
        ok=True,
        detail=f"Held — confidence={state.get('min_confidence', 0):.2f}",
    ))
    patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


# ── Routing ────────────────────────────────────────────────────────────────────

def route_after_synthesis(state: CEOState) -> str:
    if state.get("awaiting_review") and _run_config({}).require_review:
        return CEO_ROUTE_HOLD
    if (state.get("min_confidence") or 1.0) < 0.75:
        return CEO_ROUTE_HOLD
    return "strategic_priorities"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_ceo_graph() -> StateGraph:
    graph = StateGraph(CEOState)

    graph.add_node("run_pipelines",        node_run_pipelines)
    graph.add_node("condense_summaries",   node_condense_summaries)
    graph.add_node("synthesis",            node_synthesis)
    graph.add_node("strategic_priorities", node_strategic_priorities)
    graph.add_node("board_deck",           node_board_deck)
    graph.add_node("okr",                  node_okr)
    graph.add_node("hold_for_review",      node_hold_for_review)

    graph.set_entry_point("run_pipelines")

    graph.add_edge("run_pipelines",      "condense_summaries")
    graph.add_edge("condense_summaries", "synthesis")

    graph.add_conditional_edges(
        "synthesis",
        route_after_synthesis,
        {
            "strategic_priorities": "strategic_priorities",
            CEO_ROUTE_HOLD:         "hold_for_review",
        },
    )

    graph.add_edge("strategic_priorities", "board_deck")
    graph.add_edge("board_deck",           "okr")
    graph.add_edge("okr",                  END)
    graph.add_edge("hold_for_review",      END)

    return graph


ceo_graph = build_ceo_graph().compile()


# ── Public entry point ─────────────────────────────────────────────────────────

async def _run_cfo_from_transactions(
    job_id: str,
    transactions: list[dict[str, Any]],
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run a lightweight CFO analysis directly from a list of transaction dicts,
    bypassing file upload and OCR.

    Transactions should follow the schema:
      {"amount_cents": int, "type": "revenue"|"expense", "date": "YYYY-MM-DD",
       "category": str (optional), "description": str (optional)}

    Returns a dict that mimics the shape of CFOState so synthesis_agent can
    call _condense_financial_summary() on it without changes.
    """
    from app.agents.pnl_agent import run_pnl
    from app.agents.cashflow_agent import run_cashflow
    from app.agents.forecast_agent import run_forecast
    from app.agents.state import DEFAULT_RUN_CONFIG

    # Normalize transaction types: frontend may send "revenue" but agents expect "income"
    normalized: list[dict[str, Any]] = []
    for t in transactions:
        tx = dict(t)
        if tx.get("type") == "revenue":
            tx["type"] = "income"
        normalized.append(tx)

    # Build a minimal CFOState with pre-parsed transactions
    synthetic_state: dict[str, Any] = {
        "job_id": job_id,
        "file_path": "",
        "file_type": "json",
        "transactions": normalized,
        "logs": [],
        "min_confidence": 1.0,
        "awaiting_review": False,
        "halted": False,
        "error": None,
        "triggered_alerts": [],
    }
    if budget:
        synthetic_state["budget_input"] = budget

    cfg = DEFAULT_RUN_CONFIG

    # Run core agents sequentially — skip data_ingestion (already have transactions)
    try:
        from app.agents.state import CFOState
        pnl_result = await run_pnl(synthetic_state, cfg)  # type: ignore[arg-type]
        if pnl_result.ok:
            synthetic_state.update(pnl_result.patch)
        cf_result = await run_cashflow(synthetic_state, cfg)  # type: ignore[arg-type]
        if cf_result.ok:
            synthetic_state.update(cf_result.patch)
        fc_result = await run_forecast(synthetic_state, cfg)  # type: ignore[arg-type]
        if fc_result.ok:
            synthetic_state.update(fc_result.patch)
    except Exception as exc:
        logger.warning("_run_cfo_from_transactions: agent error: %s", exc)

    return synthetic_state


async def run_ceo_pipeline(
    job_id: str,
    # CFO inputs — file-based
    cfo_file_path: str | None = None,
    cfo_file_type: str | None = None,
    # CFO inputs — direct JSON
    cfo_transactions: list[dict[str, Any]] | None = None,
    cfo_budget: dict[str, Any] | None = None,
    # CTO inputs
    cloud_billing_csv: str | None = None,
    git_log_text: str | None = None,
    incident_csv: str | None = None,
    sprint_csv: str | None = None,
    # Meta
    company_name: str | None = None,
    period: str | None = None,
    run_config: CEORunConfig | None = None,
) -> CEOState:
    """
    Run the full CEO analysis pipeline.

    CFO and CTO pipelines run in parallel — at least one must have valid input.

    CFO input modes (mutually exclusive, file-based takes priority):
      a) file-based: cfo_file_path + cfo_file_type
      b) direct JSON: cfo_transactions list

    Returns final CEOState with:
      - financial_summary, tech_summary
      - cross_risks
      - strategic_priorities
      - board_deck (slides + one-pager)
    """
    cfg = run_config or DEFAULT_CEO_RUN_CONFIG

    cfo_input: dict[str, Any] = {}
    if cfo_file_path and cfo_file_type:
        cfo_input = {"file_path": cfo_file_path, "file_type": cfo_file_type, "budget": cfo_budget}
    elif cfo_transactions:
        cfo_input = {"transactions": cfo_transactions, "budget": cfo_budget}

    cto_input: dict[str, Any] = {}
    if any([cloud_billing_csv, git_log_text, incident_csv, sprint_csv]):
        cto_input = {
            "cloud_billing_csv": cloud_billing_csv,
            "git_log_text":      git_log_text,
            "incident_csv":      incident_csv,
            "sprint_csv":        sprint_csv,
        }

    initial_state: CEOState = {
        "job_id":      job_id,
        "company_name": company_name,
        "period":      period,
        "_cfo_input":  cfo_input,  # type: ignore[typeddict-unknown-key]
        "_cto_input":  cto_input,  # type: ignore[typeddict-unknown-key]
        "logs":            [],
        "min_confidence":  1.0,
        "awaiting_review": False,
        "halted":          False,
        "error":           None,
    }

    result: CEOState = await ceo_graph.ainvoke(
        initial_state,
        config={"configurable": {"ceo_run_config": cfg}},
    )

    deck = result.get("board_deck") or {}
    logger.info(
        "CEO pipeline finished: job=%s slides=%d priorities=%d cross_risks=%d",
        job_id,
        len(deck.get("slides", [])),
        len(result.get("strategic_priorities") or []),
        len(result.get("cross_risks") or []),
    )
    return result
