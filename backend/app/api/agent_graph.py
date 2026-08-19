"""
Agent Graph API — expose pipeline execution state as a graph structure.

Returns a DAG (directed acyclic graph) representation of the agent pipeline
execution, including node statuses, durations, and connections.

Consumed by the frontend AgentGraphVisualizer component to render a live
or historical pipeline status view.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.user import User

router = APIRouter(tags=["agent-graph"])


# ── Static graph topology ─────────────────────────────────────────────────────
# Defines the fixed DAG structure of the CEO pipeline.
# Node IDs must match the step names logged by orchestrators.

CFO_SUBGRAPH = [
    {"id": "pnl",       "label": "P&L",          "group": "cfo", "x": 0,   "y": 0},
    {"id": "cashflow",  "label": "Cash Flow",     "group": "cfo", "x": 0,   "y": 1},
    {"id": "forecast",  "label": "Forecast",      "group": "cfo", "x": 0,   "y": 2},
    {"id": "anomaly",   "label": "Anomaly Scan",  "group": "cfo", "x": 0,   "y": 3},
    {"id": "tax",       "label": "Tax",           "group": "cfo", "x": 0,   "y": 4},
    {"id": "budget",    "label": "Budget",        "group": "cfo", "x": 0,   "y": 5},
]

CEO_NODES = [
    {"id": "run_pipelines",     "label": "Run Pipelines",       "group": "orchestrator", "x": 2, "y": 2},
    {"id": "condense_summaries","label": "Condense Summaries",  "group": "orchestrator", "x": 2, "y": 3},
    {"id": "synthesis",         "label": "CEO Synthesis",       "group": "synthesis",    "x": 2, "y": 4},
    {"id": "strategic_priorities","label": "Strategic Priorities","group": "synthesis",  "x": 2, "y": 5},
    {"id": "board_deck",        "label": "Board Deck",          "group": "output",       "x": 2, "y": 6},
    {"id": "swot",              "label": "SWOT Analysis",       "group": "output",       "x": 3, "y": 6},
    {"id": "hold_for_review",   "label": "Hold for Review",     "group": "control",      "x": 3, "y": 5},
]

KERNEL_NODES = [
    {"id": "cto_kernel",  "label": "CTO Kernel",  "group": "kernel", "x": 1, "y": 0},
    {"id": "cmo_kernel",  "label": "CMO Kernel",  "group": "kernel", "x": 1, "y": 1},
    {"id": "chro_kernel", "label": "CHRO Kernel", "group": "kernel", "x": 1, "y": 2},
    {"id": "coo_kernel",  "label": "COO Kernel",  "group": "kernel", "x": 1, "y": 3},
    {"id": "audit",       "label": "Audit",       "group": "kernel", "x": 1, "y": 4},
    {"id": "compliance",  "label": "Compliance",  "group": "kernel", "x": 1, "y": 5},
]

# Directed edges: (source_id, target_id, label?)
PIPELINE_EDGES = [
    # CFO sub-pipeline
    ("pnl",        "cashflow",           None),
    ("cashflow",   "forecast",           None),
    ("forecast",   "anomaly",            None),
    ("anomaly",    "tax",                None),
    ("tax",        "budget",             None),
    # CFO → orchestrator
    ("budget",          "run_pipelines", "CFO"),
    # Kernel → orchestrator
    ("cto_kernel",      "run_pipelines", None),
    ("cmo_kernel",      "run_pipelines", None),
    ("chro_kernel",     "run_pipelines", None),
    ("coo_kernel",      "run_pipelines", None),
    ("audit",           "run_pipelines", None),
    ("compliance",      "run_pipelines", None),
    # Orchestrator flow
    ("run_pipelines",     "condense_summaries", None),
    ("condense_summaries","synthesis",          None),
    ("synthesis",         "strategic_priorities","on_success"),
    ("synthesis",         "hold_for_review",    "low_confidence"),
    ("strategic_priorities","board_deck",        None),
    ("strategic_priorities","swot",              None),
]

# Node group colors (CSS var names used by the frontend)
GROUP_COLORS = {
    "cfo":          "blue",
    "kernel":       "violet",
    "orchestrator": "amber",
    "synthesis":    "emerald",
    "output":       "sky",
    "control":      "rose",
}


def _build_topology() -> dict[str, Any]:
    """Return the static graph topology with group metadata."""
    all_nodes = CFO_SUBGRAPH + KERNEL_NODES + CEO_NODES
    edges = [
        {"source": s, "target": t, "label": label}
        for s, t, label in PIPELINE_EDGES
    ]
    return {
        "nodes": [
            {**n, "color": GROUP_COLORS.get(n["group"], "gray")}
            for n in all_nodes
        ],
        "edges": edges,
    }


def _parse_step_logs(logs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Convert a list of step log dicts into a {node_id: status_dict} map.

    Logs come from CEOStepLog / COOStepLog / etc. serialized to dict.
    Expected fields: step, ok, detail, confidence, duration_ms (optional).
    """
    status_map: dict[str, dict[str, Any]] = {}
    for log in logs:
        step = log.get("step", "")
        if not step:
            continue
        # Normalize step names to node IDs
        node_id = _normalize_step(step)
        status_map[node_id] = {
            "status": "success" if log.get("ok") else "error",
            "detail": log.get("detail"),
            "confidence": log.get("confidence"),
            "duration_ms": log.get("duration_ms"),
        }
    return status_map


def _normalize_step(step: str) -> str:
    """Normalize step name variants to canonical node IDs."""
    mapping = {
        "node_run_pipelines":      "run_pipelines",
        "node_condense_summaries": "condense_summaries",
        "node_synthesis":          "synthesis",
        "node_strategic_priorities":"strategic_priorities",
        "node_board_deck":         "board_deck",
        "node_swot":               "swot",
        "node_hold_for_review":    "hold_for_review",
        # CFO pipeline
        "pnl_agent":               "pnl",
        "cashflow_agent":          "cashflow",
        "forecast_agent":          "forecast",
        "anomaly_agent":           "anomaly",
        "tax_agent":               "tax",
        "budget_agent":            "budget",
        # Kernels
        "cto":                     "cto_kernel",
        "cto_kernel":              "cto_kernel",
        "cmo":                     "cmo_kernel",
        "cmo_kernel":              "cmo_kernel",
        "chro":                    "chro_kernel",
        "chro_kernel":             "chro_kernel",
        "coo":                     "coo_kernel",
        "coo_kernel":              "coo_kernel",
        "audit_kernel":            "audit",
        "compliance_kernel":       "compliance",
    }
    return mapping.get(step.lower(), step.lower())


def _merge_topology_with_status(
    topology: dict[str, Any],
    status_map: dict[str, dict[str, Any]],
    running_node: str | None,
) -> dict[str, Any]:
    """Merge static topology with runtime execution status."""
    enriched_nodes = []
    for node in topology["nodes"]:
        node_id = node["id"]
        runtime = status_map.get(node_id)
        enriched = {**node}

        if runtime:
            enriched["status"] = runtime["status"]
            enriched["detail"] = runtime.get("detail")
            enriched["confidence"] = runtime.get("confidence")
            enriched["duration_ms"] = runtime.get("duration_ms")
        elif node_id == running_node:
            enriched["status"] = "running"
        else:
            enriched["status"] = "pending"

        enriched_nodes.append(enriched)

    return {**topology, "nodes": enriched_nodes}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/agent-graph/topology")
async def get_graph_topology() -> dict[str, Any]:
    """
    Return the static pipeline topology (nodes + edges).
    Used to render the graph canvas before any job runs.
    """
    return {"data": _build_topology(), "error": None}


@router.get("/agent-graph/job/{job_id}")
async def get_job_graph(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return the pipeline graph with execution status overlaid for a specific job.

    Node statuses: "pending" | "running" | "success" | "error"
    """
    # Load job record
    result = await db.execute(
        select(AnalysisJob).where(AnalysisJob.id == job_id)
    )
    job = result.scalar_one_or_none()

    topology = _build_topology()

    if not job:
        return {
            "data": {
                **topology,
                "job_id": job_id,
                "job_status": "not_found",
                "progress_pct": 0,
            },
            "error": None,
        }

    # Extract step logs from job metadata
    metadata: dict[str, Any] = job.result_metadata or {}
    raw_logs: list[dict[str, Any]] = metadata.get("step_logs", [])
    status_map = _parse_step_logs(raw_logs)

    # Determine currently running node (if job is in progress)
    running_node: str | None = None
    job_status: str = getattr(job, "status", "unknown")
    if job_status in ("running", "pending"):
        # Best guess: last logged node's successor
        logged_ids = list(status_map.keys())
        running_node = logged_ids[-1] if logged_ids else "pnl"

    enriched = _merge_topology_with_status(topology, status_map, running_node)

    # Compute overall progress percentage
    total_nodes = len(enriched["nodes"])
    completed = sum(
        1 for n in enriched["nodes"]
        if n.get("status") in ("success", "error")
    )
    progress_pct = round(completed / total_nodes * 100) if total_nodes else 0

    return {
        "data": {
            **enriched,
            "job_id": job_id,
            "job_status": job_status,
            "progress_pct": progress_pct,
            "completed_nodes": completed,
            "total_nodes": total_nodes,
            "running_node": running_node,
        },
        "error": None,
    }


@router.get("/agent-graph/summary")
async def get_pipeline_summary(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a human-readable description of the full pipeline for documentation
    and onboarding tooltips.
    """
    return {
        "data": {
            "groups": [
                {
                    "id": "cfo",
                    "label": "CFO Pipeline",
                    "description": "P&L, nakit akışı, tahmin, anomali, vergi ve bütçe analizleri.",
                    "node_count": len(CFO_SUBGRAPH),
                },
                {
                    "id": "kernel",
                    "label": "C-Suite Kernels",
                    "description": "CTO, CMO, CHRO, COO, Audit ve Compliance paralel analizleri.",
                    "node_count": len(KERNEL_NODES),
                },
                {
                    "id": "synthesis",
                    "label": "CEO Sentezi",
                    "description": "Tüm domainleri birleştiren cross-risk analizi ve stratejik öncelikler.",
                    "node_count": 2,
                },
                {
                    "id": "output",
                    "label": "Çıktılar",
                    "description": "Board Deck PDF ve SWOT analizi oluşturma.",
                    "node_count": 2,
                },
            ],
            "total_nodes": len(CFO_SUBGRAPH) + len(KERNEL_NODES) + len(CEO_NODES),
            "total_edges": len(PIPELINE_EDGES),
        },
        "error": None,
    }
