"""
CFO Orchestrator v2 — LangGraph StateGraph.

Tam pipeline:
  START
  → data_ingestion
  → review_gate (confidence check)
  → pnl
  → cashflow
  → forecast
  → anomaly       (non-fatal)
  → multi_period  (non-fatal, needs 2+ months)
  → tax           (non-fatal)
  → budget        (non-fatal, needs budget_input)
  → alert         (always runs, aggregates all signals)
  → report
  → END

  hold_for_review (terminal if confidence < 0.80)

Non-fatal nodes: failure does not halt the pipeline.
Fatal nodes: data_ingestion, pnl — without these, nothing else can run.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

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

# Additional routing constants for mid-pipeline halt gates
ROUTE_CASHFLOW = "cashflow"
ROUTE_FORECAST = "forecast"
ROUTE_ANOMALY  = "anomaly"
from app.agents.data_ingestion import run_data_ingestion
from app.agents.pnl_agent import run_pnl
from app.agents.cashflow_agent import run_cashflow
from app.agents.forecast_agent import run_forecast
from app.agents.anomaly_agent import run_anomaly_detection
from app.agents.multi_period_agent import run_multi_period
from app.agents.tax_agent import run_tax
from app.agents.budget_agent import run_budget
from app.agents.alert_agent import run_alerts
from app.agents.report_agent import run_report
from app.services.capability_router import get_capability_router
from app.services.reflection_agent import get_reflection_agent
from app.services.agent_memory import AgentMemoryStore, EpisodeRecord, get_memory_store

logger = logging.getLogger(__name__)

# Module-level kernel service instances (singleton pattern)
_router    = get_capability_router()
_reflector = get_reflection_agent(pass_threshold=0.55)
_memory    = get_memory_store(backend="sqlite", db_path="./agent_memory.db")


# ── Helper ────────────────────────────────────────────────────────────────────

def _append_log(state: CFOState, log: StepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    min_conf = state.get("min_confidence", 1.0)
    if log.confidence is not None:
        min_conf = min(min_conf, log.confidence)
    return {"logs": existing, "min_confidence": min_conf}


def _run_config(config: dict) -> AgentRunConfig:
    return config.get("configurable", {}).get("run_config", DEFAULT_RUN_CONFIG)


# ── Routing skip helper ───────────────────────────────────────────────────────

def _is_skipped(state: CFOState, agent_name: str) -> bool:
    """
    Check if CapabilityRouter decided to skip this agent.
    Returns True when the routing plan says should_run=False for this agent.
    """
    plan = state.get("routing_plan") or {}
    decisions = plan.get("decisions") or {}
    decision = decisions.get(agent_name)
    if decision is None:
        return False  # No plan → run everything (safe default)
    return not decision.get("should_run", True)


def _update_reflection(state: CFOState, agent: str, narrative: str, context: dict) -> dict:
    """
    Run ReflectionAgent on a narrative and merge the score into state.
    Returns a patch dict with updated reflection_scores.
    """
    try:
        result = _reflector.evaluate_narrative(narrative, context)
        scores = dict(state.get("reflection_scores") or {})
        scores[agent] = result.to_dict()
        return {"reflection_scores": scores}
    except Exception as exc:
        logger.warning("ReflectionAgent failed for %s: %s", agent, exc)
        return {}


# ── Node builders ─────────────────────────────────────────────────────────────
# Fatal nodes (halt on failure)

async def node_data_ingestion(state: CFOState, config: dict) -> CFOState:
    result = await run_data_ingestion(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="data_ingestion", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if not result.ok:
        patch.update({"halted": True, "awaiting_review": True, "error": result.detail})
    if result.needs_review:
        patch["awaiting_review"] = True

    # After ingestion, build routing plan for downstream agents
    merged_state = {**state, **patch}
    try:
        plan = _router.route(merged_state)
        patch["routing_plan"] = {
            "execution_order": plan.execution_order,
            "skipped": plan.skipped,
            "decisions": {
                k: {"should_run": v.should_run, "reason": v.reason}
                for k, v in plan.decisions.items()
            },
        }
        logger.info("CapabilityRouter: %s", plan.summary())
    except Exception as exc:
        logger.warning("CapabilityRouter failed: %s", exc)

    return {**state, **patch}  # type: ignore[return-value]


async def node_pnl(state: CFOState, config: dict) -> CFOState:
    result = await run_pnl(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="pnl", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if not result.ok:
        patch.update({"halted": True, "error": result.detail})
    else:
        # ReflectionAgent: evaluate PnL narrative quality
        pnl_data = result.patch.get("pnl") or {}
        narrative = pnl_data.get("narrative") or ""
        if narrative:
            patch.update(_update_reflection(state, "pnl", narrative, pnl_data))
    return {**state, **patch}  # type: ignore[return-value]


async def node_cashflow(state: CFOState, config: dict) -> CFOState:
    result = await run_cashflow(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="cashflow", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if not result.ok:
        patch.update({"halted": True, "error": result.detail})
    else:
        cf_data = result.patch.get("cashflow") or {}
        narrative = cf_data.get("narrative") or ""
        if narrative:
            patch.update(_update_reflection(state, "cashflow", narrative, cf_data))
    return {**state, **patch}  # type: ignore[return-value]


async def node_forecast(state: CFOState, config: dict) -> CFOState:
    result = await run_forecast(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="forecast", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if not result.ok:
        patch.update({"halted": True, "error": result.detail})
    else:
        fc_data = result.patch.get("forecast") or {}
        narrative = fc_data.get("narrative") or ""
        if narrative:
            patch.update(_update_reflection(state, "forecast", narrative, fc_data))
    return {**state, **patch}  # type: ignore[return-value]


# Non-fatal nodes (failure → log + continue)
# Each checks routing plan before running — if skipped, returns state unchanged.

async def node_anomaly(state: CFOState, config: dict) -> CFOState:
    if _is_skipped(state, "anomaly_agent"):
        logger.debug("Skipping anomaly_agent (routing plan)")
        return state
    result = await run_anomaly_detection(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="anomaly", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_multi_period(state: CFOState, config: dict) -> CFOState:
    if _is_skipped(state, "multi_period_agent"):
        logger.debug("Skipping multi_period_agent (routing plan)")
        return state
    result = await run_multi_period(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="multi_period", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_tax(state: CFOState, config: dict) -> CFOState:
    if _is_skipped(state, "tax_agent"):
        logger.debug("Skipping tax_agent (routing plan)")
        return state
    result = await run_tax(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="tax", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_budget(state: CFOState, config: dict) -> CFOState:
    if _is_skipped(state, "budget_agent"):
        logger.debug("Skipping budget_agent (routing plan)")
        return state
    result = await run_budget(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="budget", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_alert(state: CFOState, config: dict) -> CFOState:
    result = await run_alerts(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="alert", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    return {**state, **patch}  # type: ignore[return-value]


async def node_report(state: CFOState, config: dict) -> CFOState:
    result = await run_report(state, _run_config(config))
    patch = _append_log(state, StepLog(
        step="report", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if not result.ok:
        patch["error"] = result.detail
    return {**state, **patch}  # type: ignore[return-value]


async def node_hold_for_review(state: CFOState, config: dict) -> CFOState:
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


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_ingestion(state: CFOState) -> str:
    if state.get("halted"):
        return ROUTE_END
    if state.get("awaiting_review"):
        return ROUTE_HOLD
    if (state.get("min_confidence") or 1.0) < 0.80:
        return ROUTE_HOLD
    return ROUTE_PNL


def _route_fatal_node(next_node: str) -> "Callable[[CFOState], str]":
    """
    Factory: returns a routing function that checks `halted` after a fatal node.
    If halted → END; otherwise → next_node.
    Used to break the silent failure chain: if cashflow halts, forecast never runs.
    """
    def _route(state: CFOState) -> str:
        if state.get("halted"):
            return ROUTE_END
        return next_node
    _route.__name__ = f"route_to_{next_node}"
    return _route


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_cfo_graph() -> StateGraph:
    graph = StateGraph(CFOState)

    # Register all nodes
    graph.add_node("data_ingestion",  node_data_ingestion)
    graph.add_node("pnl",             node_pnl)
    graph.add_node("cashflow",        node_cashflow)
    graph.add_node("forecast",        node_forecast)
    graph.add_node("anomaly",         node_anomaly)
    graph.add_node("multi_period",    node_multi_period)
    graph.add_node("tax",             node_tax)
    graph.add_node("budget",          node_budget)
    graph.add_node("alert",           node_alert)
    graph.add_node("report",          node_report)
    graph.add_node("hold_for_review", node_hold_for_review)

    graph.set_entry_point("data_ingestion")

    # ── Confidence gate after ingestion ───────────────────────────────────────
    graph.add_conditional_edges(
        "data_ingestion",
        route_after_ingestion,
        {
            ROUTE_PNL:  "pnl",
            ROUTE_HOLD: "hold_for_review",
            ROUTE_END:  END,
        },
    )

    # ── Fatal nodes: halt-check conditional edges ─────────────────────────────
    # pnl → halt-check → cashflow (or END if pnl failed)
    graph.add_conditional_edges(
        "pnl",
        _route_fatal_node("cashflow"),
        {"cashflow": "cashflow", ROUTE_END: END},
    )

    # cashflow → halt-check → forecast (or END if cashflow failed)
    graph.add_conditional_edges(
        "cashflow",
        _route_fatal_node("forecast"),
        {"forecast": "forecast", ROUTE_END: END},
    )

    # forecast → halt-check → anomaly (or END if forecast failed)
    graph.add_conditional_edges(
        "forecast",
        _route_fatal_node("anomaly"),
        {"anomaly": "anomaly", ROUTE_END: END},
    )

    # ── Non-fatal nodes: always continue (failure logged, pipeline proceeds) ──
    graph.add_edge("anomaly",      "multi_period")
    graph.add_edge("multi_period", "tax")
    graph.add_edge("tax",          "budget")
    graph.add_edge("budget",       "alert")
    graph.add_edge("alert",        "report")
    graph.add_edge("report",       END)
    graph.add_edge("hold_for_review", END)

    return graph


# Compiled graph — reused across requests (thread-safe)
cfo_graph = build_cfo_graph().compile()


# ── Public entry point ────────────────────────────────────────────────────────

async def run_cfo_pipeline(
    job_id: str,
    file_path: str,
    file_type: str,
    run_config: AgentRunConfig | None = None,
    budget_input: dict | None = None,
    org_id: str | None = None,
    period: str | None = None,
) -> CFOState:
    """
    Run the full CFO analysis pipeline.

    Args:
        job_id:       Analysis job ID
        file_path:    Uploaded file path on disk
        file_type:    pdf | xlsx | csv
        run_config:   Optional agent run configuration
        budget_input: Optional budget dict for BudgetAgent
        org_id:       Organization ID for memory retrieval/storage
        period:       Reporting period label (e.g. "2024-Q4") for memory

    Returns:
        Final CFOState — caller persists to DB.

    Kernel integrations:
        1. CapabilityRouter — called inside node_data_ingestion after
           transactions are parsed; routing_plan stored in state.
        2. ReflectionAgent — called after node_pnl/cashflow/forecast;
           reflection_scores stored in state.
        3. AgentMemoryStore — episode saved after pipeline completes;
           memory_episode_ids stored in state.
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
        "triggered_alerts": [],
        "org_id": org_id,
        "routing_plan": None,
        "reflection_scores": None,
        "memory_episode_ids": None,
    }

    if budget_input:
        initial_state["budget_input"] = budget_input  # type: ignore[assignment]

    result: CFOState = await cfo_graph.ainvoke(
        initial_state,
        config={"configurable": {"run_config": cfg}},
    )

    logger.info(
        "CFO pipeline finished: job=%s halted=%s awaiting_review=%s "
        "anomalies=%d alerts=%d reflection_agents=%d",
        job_id,
        result.get("halted"),
        result.get("awaiting_review"),
        len(result.get("anomalies") or []),
        len(result.get("triggered_alerts") or []),
        len(result.get("reflection_scores") or {}),
    )

    # ── AgentMemoryStore: save episode for future context retrieval ───────────
    if org_id and not result.get("halted"):
        try:
            pnl = result.get("pnl") or {}
            cf  = result.get("cashflow") or {}
            episode = EpisodeRecord(
                org_id=org_id,
                agent="cfo_pipeline",
                period=period or job_id[:8],
                job_id=job_id,
                summary={
                    "revenue":        pnl.get("revenue"),
                    "net_income":     pnl.get("net_income"),
                    "net_margin":     pnl.get("net_margin"),
                    "net_cashflow":   cf.get("net_change"),
                    "anomaly_count":  len(result.get("anomalies") or []),
                    "alert_count":    len(result.get("triggered_alerts") or []),
                    "min_confidence": result.get("min_confidence"),
                },
                narrative=(pnl.get("narrative") or "")[:300],
                confidence=result.get("min_confidence") or 1.0,
                tags=["pipeline", file_type],
            )
            _memory.save(episode)
            # Merge episode id back into state for observability
            existing_ids = list(result.get("memory_episode_ids") or [])
            existing_ids.append(episode.id)
            result = {**result, "memory_episode_ids": existing_ids}  # type: ignore[assignment]
            logger.info("AgentMemory: saved episode %s for org %s", episode.id, org_id)
        except Exception as exc:
            logger.warning("AgentMemoryStore.save failed: %s", exc)

    return result
