"""
CFO Orchestrator — LangGraph StateGraph.

Graph topology (8 skills):
  START → data_ingestion → review_gate → pnl → cashflow → forecast
                                                              ↓
                                               tax → anomaly → budget → report → END
                                    ↓
                              hold_for_review → END

The review_gate fires after data_ingestion:
  - confidence < 0.80 or awaiting_review → hold_for_review
  - otherwise → proceed to pnl

After forecast, the extended skills (tax, anomaly, budget) run in parallel
conceptually but are sequenced in LangGraph for simplicity — they are fast
rule-based agents and don't block on each other's output.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from app.agents.state import (
    CFOState,
    AgentRunConfig,
    DEFAULT_RUN_CONFIG,
    StepLog,
    ROUTE_PNL,
    ROUTE_HOLD,
    ROUTE_END,
)
from app.agents.data_ingestion import run_data_ingestion
from app.agents.pnl_agent import run_pnl
from app.agents.cashflow_agent import run_cashflow
from app.agents.forecast_agent import run_forecast
from app.agents.tax_agent import run_tax
from app.agents.anomaly_agent import run_anomaly_detection
from app.agents.budget_agent import run_budget_comparison
from app.agents.report_agent import run_report

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: append a StepLog to state
# ---------------------------------------------------------------------------

def _append_log(state: CFOState, log: StepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    min_conf = state.get("min_confidence", 1.0)
    if log.confidence is not None:
        min_conf = min(min_conf, log.confidence)
    return {"logs": existing, "min_confidence": min_conf}


# ---------------------------------------------------------------------------
# Node wrappers
# ---------------------------------------------------------------------------

async def node_data_ingestion(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_data_ingestion(state, run_config)
    patch = _append_log(state, StepLog(
        step="data_ingestion",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    if not result.ok:
        patch["halted"] = True
        patch["awaiting_review"] = True
        patch["error"] = result.detail
    if result.needs_review:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


async def node_pnl(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_pnl(state, run_config)
    patch = _append_log(state, StepLog(
        step="pnl",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    if not result.ok:
        patch["halted"] = True
        patch["error"] = result.detail
    return {**state, **patch}  # type: ignore[return-value]


async def node_cashflow(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_cashflow(state, run_config)
    patch = _append_log(state, StepLog(
        step="cashflow",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    if not result.ok:
        patch["halted"] = True
        patch["error"] = result.detail
    return {**state, **patch}  # type: ignore[return-value]


async def node_forecast(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_forecast(state, run_config)
    patch = _append_log(state, StepLog(
        step="forecast",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    if not result.ok:
        patch["halted"] = True
        patch["error"] = result.detail
    return {**state, **patch}  # type: ignore[return-value]


async def node_tax(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_tax(state, run_config)
    patch = _append_log(state, StepLog(
        step="tax",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    # Tax failures are non-fatal — pipeline continues without tax data
    if not result.ok:
        logger.warning("Tax agent failed — continuing pipeline: %s", result.detail)
    return {**state, **patch}  # type: ignore[return-value]


async def node_anomaly(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_anomaly_detection(state, run_config)
    patch = _append_log(state, StepLog(
        step="anomaly",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    if result.needs_review:
        patch["awaiting_review"] = True
    # Anomaly failures are non-fatal
    if not result.ok:
        logger.warning("Anomaly agent failed — continuing: %s", result.detail)
    return {**state, **patch}  # type: ignore[return-value]


async def node_budget(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_budget_comparison(state, run_config)
    patch = _append_log(state, StepLog(
        step="budget",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    # Budget failures are non-fatal
    if not result.ok:
        logger.warning("Budget agent failed — continuing: %s", result.detail)
    return {**state, **patch}  # type: ignore[return-value]


async def node_report(state: CFOState, config: dict) -> CFOState:
    run_config: AgentRunConfig = config.get("configurable", {}).get(
        "run_config", DEFAULT_RUN_CONFIG
    )
    result = await run_report(state, run_config)
    patch = _append_log(state, StepLog(
        step="report",
        ok=result.ok,
        detail=result.detail,
        confidence=result.confidence,
    ))
    patch.update(result.patch)
    if not result.ok:
        patch["error"] = result.detail
    return {**state, **patch}  # type: ignore[return-value]


async def node_hold_for_review(state: CFOState, config: dict) -> CFOState:
    """Terminal node when the run is held for human approval."""
    patch = _append_log(state, StepLog(
        step="review_gate",
        ok=True,
        detail=(
            f"Held for review — confidence={state.get('min_confidence', 0):.2f}, "
            f"awaiting_review={state.get('awaiting_review')}"
        ),
    ))
    patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Conditional edge: review gate
# ---------------------------------------------------------------------------

def route_after_ingestion(state: CFOState) -> str:
    if state.get("halted"):
        return ROUTE_END
    if state.get("awaiting_review"):
        return ROUTE_HOLD
    min_conf = state.get("min_confidence", 1.0)
    if min_conf < 0.80:
        return ROUTE_HOLD
    return ROUTE_PNL


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_cfo_graph() -> StateGraph:
    graph = StateGraph(CFOState)

    # Register all nodes
    graph.add_node("data_ingestion", node_data_ingestion)
    graph.add_node("pnl", node_pnl)
    graph.add_node("cashflow", node_cashflow)
    graph.add_node("forecast", node_forecast)
    graph.add_node("tax", node_tax)
    graph.add_node("anomaly", node_anomaly)
    graph.add_node("budget", node_budget)
    graph.add_node("report", node_report)
    graph.add_node("hold_for_review", node_hold_for_review)

    graph.set_entry_point("data_ingestion")

    # Confidence gate after ingestion
    graph.add_conditional_edges(
        "data_ingestion",
        route_after_ingestion,
        {
            ROUTE_PNL: "pnl",
            ROUTE_HOLD: "hold_for_review",
            ROUTE_END: END,
        },
    )

    # Core analysis pipeline
    graph.add_edge("pnl", "cashflow")
    graph.add_edge("cashflow", "forecast")

    # Extended CFO skills — run after forecast, non-fatal
    graph.add_edge("forecast", "tax")
    graph.add_edge("tax", "anomaly")
    graph.add_edge("anomaly", "budget")
    graph.add_edge("budget", "report")

    graph.add_edge("report", END)
    graph.add_edge("hold_for_review", END)

    return graph


# Compiled graph — reused across requests (thread-safe)
cfo_graph = build_cfo_graph().compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_cfo_pipeline(
    job_id: str,
    file_path: str,
    file_type: str,
    run_config: AgentRunConfig | None = None,
) -> CFOState:
    """
    Run the full CFO analysis pipeline for a given upload job.
    Returns the final CFOState — caller persists logs and results to DB.
    """
    cfg = run_config or DEFAULT_RUN_CONFIG
    initial_state: CFOState = {
        "job_id": job_id,
        "file_path": file_path,
        "file_type": file_type,
        "logs": [],
        "min_confidence": 1.0,
        "awaiting_review": False,
        "halted": False,
        "error": None,
    }
    result: CFOState = await cfo_graph.ainvoke(
        initial_state,
        config={"configurable": {"run_config": cfg}},
    )
    logger.info(
        "CFO pipeline finished job=%s awaiting_review=%s halted=%s",
        job_id,
        result.get("awaiting_review"),
        result.get("halted"),
    )
    return result
