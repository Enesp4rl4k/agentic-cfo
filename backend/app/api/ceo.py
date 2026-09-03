"""
CEO API endpoints — /api/v1/ceo/*

POST /ceo/analyze                  → run full CEO pipeline synchronously
POST /ceo/analyze-async            → enqueue CEO pipeline as background job (ARQ)
GET  /ceo/status/{job_id}          → poll async job status from Redis
POST /ceo/export-pdf               → render board_deck + OKR to PDF (WeasyPrint)
GET  /ceo/health-check             → verify CEO pipeline is importable
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


class CEOAnalyzeRequest(BaseModel):
    """
    CEO analysis request.
    Provide at least one of: CFO inputs OR CTO inputs.
    Both together gives full cross-domain synthesis.

    CFO inputs (two modes — pick one):
      a) file-based:  cfo_file_path + cfo_file_type  (from prior /upload)
      b) direct JSON: transactions (list) + optional budget (dict)

    CTO inputs: cloud_billing_csv / git_log_text / incident_csv / sprint_csv
    """
    company_name: str | None = None
    period: str | None = None          # e.g. "2024-Q2"

    # CFO inputs — file-based
    cfo_file_path: str | None = None   # path on server (from prior upload)
    cfo_file_type: str | None = None   # pdf | xlsx | csv

    # CFO inputs — direct JSON (alternative to file)
    transactions: list[dict[str, Any]] | None = None
    budget: dict[str, Any] | None = None

    # CTO inputs
    cloud_billing_csv: str | None = None
    git_log_text: str | None = None
    incident_csv: str | None = None
    sprint_csv: str | None = None


@router.post("/ceo/analyze")
async def run_ceo_analysis(body: CEOAnalyzeRequest) -> dict[str, Any]:
    """
    Run full CEO analysis pipeline synchronously.

    CFO and CTO pipelines run in parallel (asyncio.gather).
    Results are cross-correlated into strategic priorities and board deck.
    """
    from app.agents.ceo.orchestrator import run_ceo_pipeline

    has_cfo_file = bool(body.cfo_file_path and body.cfo_file_type)
    has_cfo_json = bool(body.transactions)
    has_cfo = has_cfo_file or has_cfo_json
    has_cto = any([
        body.cloud_billing_csv,
        body.git_log_text,
        body.incident_csv,
        body.sprint_csv,
    ])

    if not has_cfo and not has_cto:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide at least one input: "
                "cfo_file_path+cfo_file_type or transactions[] for financial data, "
                "or cloud_billing_csv / git_log_text / incident_csv / sprint_csv for tech data."
            ),
        )

    job_id = str(uuid.uuid4())

    try:
        result = await run_ceo_pipeline(
            job_id=job_id,
            cfo_file_path=body.cfo_file_path,
            cfo_file_type=body.cfo_file_type,
            cfo_transactions=body.transactions,
            cfo_budget=body.budget,
            cloud_billing_csv=body.cloud_billing_csv,
            git_log_text=body.git_log_text,
            incident_csv=body.incident_csv,
            sprint_csv=body.sprint_csv,
            company_name=body.company_name,
            period=body.period,
        )

        logs_serializable = [
            {
                "step":       lg.step,
                "ok":         lg.ok,
                "detail":     lg.detail,
                "confidence": lg.confidence,
            }
            for lg in (result.get("logs") or [])
        ]

        # Compute overall_health_score: blend financial + tech signals
        overall_health_score = _compute_overall_health(result)

        return {
            "data": {
                "job_id":               job_id,
                "awaiting_review":      result.get("awaiting_review", False),
                "min_confidence":       result.get("min_confidence"),
                "overall_health_score": overall_health_score,
                "financial_summary":    result.get("financial_summary"),
                "tech_summary":         result.get("tech_summary"),
                "cross_risks":          result.get("cross_risks") or [],
                "strategic_priorities": result.get("strategic_priorities") or [],
                "board_deck":           result.get("board_deck"),
                "okr_status":           result.get("okr_status"),
                "logs":                 logs_serializable,
                "error":                result.get("error"),
            },
            "error": None,
        }

    except Exception as exc:
        logger.exception("CEO pipeline failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"CEO analysis failed: {exc}")


def _compute_overall_health(result: dict[str, Any]) -> float | None:
    """
    Compute a 0–100 overall health score from financial + tech signals.
    Higher = healthier.

    Returns None if insufficient data.
    """
    scores: list[float] = []

    fin = result.get("financial_summary") or {}
    tech = result.get("tech_summary") or {}

    # Financial health component (0–100)
    if fin:
        fin_score = 60.0  # neutral baseline
        net_margin = fin.get("net_margin", 0) or 0
        runway = fin.get("cash_runway_months")

        # Margin contribution: 0% margin → 0, 20%+ margin → +25 pts
        fin_score += min(25.0, max(-25.0, net_margin * 125))

        # Runway contribution: <2m → -30, 2-6m → -10, 6-12m → +0, 12m+ → +15
        if runway is not None:
            if runway < 2:
                fin_score -= 30
            elif runway < 6:
                fin_score -= 10
            elif runway >= 12:
                fin_score += 15

        scores.append(max(0.0, min(100.0, fin_score)))

    # Tech health component (0–100)
    # CTO health score is 0–10 where lower = healthier, flip to 0–100
    tech_health_raw = tech.get("overall_health_score")
    if tech_health_raw is not None:
        tech_score = max(0.0, min(100.0, (10.0 - float(tech_health_raw)) * 10))
        scores.append(tech_score)

    if not scores:
        return None

    return round(sum(scores) / len(scores), 1)


@router.post("/ceo/analyze-async")
async def run_ceo_analysis_async(body: CEOAnalyzeRequest) -> dict[str, Any]:
    """
    Enqueue CEO analysis as a background ARQ job.

    Returns job_id immediately. Poll GET /ceo/status/{job_id} for results.
    Status values: "pending" → "completed" | "failed"
    """
    from app.worker import enqueue_ceo_analysis

    has_cfo_file = bool(body.cfo_file_path and body.cfo_file_type)
    has_cfo_json = bool(body.transactions)
    has_cfo = has_cfo_file or has_cfo_json
    has_cto = any([
        body.cloud_billing_csv,
        body.git_log_text,
        body.incident_csv,
        body.sprint_csv,
    ])

    if not has_cfo and not has_cto:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide at least one input: "
                "cfo_file_path+cfo_file_type or transactions[] for financial data, "
                "or cloud_billing_csv / git_log_text / incident_csv / sprint_csv for tech data."
            ),
        )

    job_id = str(uuid.uuid4())

    try:
        await enqueue_ceo_analysis(
            job_id=job_id,
            cfo_file_path=body.cfo_file_path,
            cfo_file_type=body.cfo_file_type,
            cfo_transactions=body.transactions,
            cfo_budget=body.budget,
            cloud_billing_csv=body.cloud_billing_csv,
            git_log_text=body.git_log_text,
            incident_csv=body.incident_csv,
            sprint_csv=body.sprint_csv,
            company_name=body.company_name,
            period=body.period,
        )
    except Exception as exc:
        logger.exception("Failed to enqueue CEO analysis job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {exc}")

    return {
        "data": {
            "job_id": job_id,
            "status": "pending",
            "poll_url": f"/api/v1/ceo/status/{job_id}",
        },
        "error": None,
    }


@router.get("/ceo/status/{job_id}")
async def get_ceo_job_status(job_id: str) -> dict[str, Any]:
    """
    Poll CEO async job status.

    Returns:
      - status "pending"   → job is still running
      - status "completed" → result is in the "result" field
      - status "failed"    → error is in the "error" field
      - status "not_found" → job_id unknown or expired (24h TTL)
    """
    from app.worker import get_ceo_job_status as _get_status

    status_data = await _get_status(job_id)
    status = status_data.get("status", "not_found")

    if status == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found or expired.",
        )

    # For completed jobs, compute overall_health_score from nested result
    if status == "completed":
        inner = status_data.get("result") or {}
        status_data["result"]["overall_health_score"] = _compute_overall_health(inner)

    return {"data": status_data, "error": None}


class CEOExportRequest(BaseModel):
    """
    Request body for POST /ceo/export-pdf.

    Pass the board_deck object from a prior /ceo/analyze response.
    okr_status is optional — if provided, an OKR appendix slide is included.
    company_name and period are used for the PDF filename.
    """
    board_deck: dict[str, Any]
    okr_status: dict[str, Any] | None = None
    company_name: str | None = None
    period: str | None = None


@router.post("/ceo/export-pdf")
async def export_board_deck_pdf(body: CEOExportRequest) -> Response:
    """
    Render board deck (+ optional OKR appendix) to a downloadable PDF.

    Uses WeasyPrint (already in requirements.txt).
    Returns application/pdf with Content-Disposition: attachment.
    """
    try:
        from app.services.pdf_export import board_deck_to_pdf
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        pdf_bytes = board_deck_to_pdf(
            board_deck=body.board_deck,
            okr_status=body.okr_status,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    company = (body.company_name or "board-deck").lower().replace(" ", "-")
    period  = (body.period or "current").replace(" ", "-")
    filename = f"{company}-{period}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


class CEOAnalyzeFromJobRequest(BaseModel):
    company_name: str | None = None
    period: str | None = None


@router.post("/ceo/analyze-from-job/{job_id}")
async def run_ceo_from_job(
    job_id: str,
    body: CEOAnalyzeFromJobRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Run the full CEO pipeline using all DataSource files already uploaded for job_id.

    This is the primary entry point for the frontend wizard flow:
      1. User uploads bank statement → POST /upload → job_id
      2. User uploads domain files  → POST /datasource/{job_id}/cto/cloud_billing, etc.
      3. User clicks "Run CEO Analysis" → POST /ceo/analyze-from-job/{job_id}

    The endpoint reads all DataSource records for the job, reads each file from disk,
    and passes the text content to the CEO pipeline via the correct kwarg.

    Supported domains: cfo (bank_statement), cto, chro, cmo, coo
    """
    from app.agents.ceo.orchestrator import run_ceo_pipeline
    from app.models.analysis_job import AnalysisJob
    from app.models.data_source import DataSource, DataSourceDomain, DataSourceType

    # ── Validate parent job ───────────────────────────────────────────────────
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    # ── Load all data sources for this job ────────────────────────────────────
    result = await db.execute(
        select(DataSource).where(DataSource.job_id == job_id)
    )
    sources = result.scalars().all()

    # ── Build pipeline kwargs from files on disk ──────────────────────────────
    cfo_file_path: str | None = None
    cfo_file_type: str | None = None
    domain_kwargs: dict[str, str] = {}

    for src in sources:
        try:
            with open(src.file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            logger.warning("Could not read DataSource file %s: %s", src.file_path, exc)
            continue

        if src.domain == DataSourceDomain.CFO and src.source_type == DataSourceType.BANK_STATEMENT:
            # CFO bank statement uses file_path directly (parsers read binary)
            cfo_file_path = src.file_path
            cfo_file_type = src.file_path.rsplit(".", 1)[-1].lower()
        else:
            kwarg = src.pipeline_kwarg()
            if kwarg:
                domain_kwargs[kwarg] = content

    # Use the AnalysisJob's own file as the CFO source if no explicit CFO DataSource
    if not cfo_file_path and job.file_path:
        cfo_file_path = job.file_path
        cfo_file_type = job.file_type

    if not cfo_file_path and not domain_kwargs:
        raise HTTPException(
            status_code=400,
            detail=(
                "No data sources found for this job. "
                "Upload a bank statement and/or domain CSV files first."
            ),
        )

    params = body or CEOAnalyzeFromJobRequest()

    try:
        ceo_result = await run_ceo_pipeline(
            job_id=f"{job_id}-ceo",
            cfo_file_path=cfo_file_path,
            cfo_file_type=cfo_file_type,
            cloud_billing_csv=domain_kwargs.get("cloud_billing_csv"),
            git_log_text=domain_kwargs.get("git_log_text"),
            incident_csv=domain_kwargs.get("incident_csv"),
            sprint_csv=domain_kwargs.get("sprint_csv"),
            campaign_csv=domain_kwargs.get("campaign_csv"),
            funnel_csv=domain_kwargs.get("funnel_csv"),
            cohort_csv=domain_kwargs.get("cohort_csv"),
            process_csv=domain_kwargs.get("process_csv"),
            resource_csv=domain_kwargs.get("resource_csv"),
            sla_csv=domain_kwargs.get("sla_csv"),
            headcount_csv=domain_kwargs.get("headcount_csv"),
            attrition_csv=domain_kwargs.get("attrition_csv"),
            compensation_csv=domain_kwargs.get("compensation_csv"),
            company_name=params.company_name,
            period=params.period,
        )
    except Exception as exc:
        logger.exception("CEO pipeline failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"CEO analysis failed: {exc}")

    logs_serializable = [
        {"step": lg.step, "ok": lg.ok, "detail": lg.detail, "confidence": lg.confidence}
        for lg in (ceo_result.get("logs") or [])
    ]

    return {
        "data": {
            "job_id":               job_id,
            "awaiting_review":      ceo_result.get("awaiting_review", False),
            "min_confidence":       ceo_result.get("min_confidence"),
            "overall_health_score": _compute_overall_health(ceo_result),
            "financial_summary":    ceo_result.get("financial_summary"),
            "tech_summary":         ceo_result.get("tech_summary"),
            "marketing_summary":    ceo_result.get("marketing_summary"),
            "ops_summary":          ceo_result.get("ops_summary"),
            "hr_summary":           ceo_result.get("hr_summary"),
            "cross_risks":          ceo_result.get("cross_risks") or [],
            "strategic_priorities": ceo_result.get("strategic_priorities") or [],
            "board_deck":           ceo_result.get("board_deck"),
            "okr_status":           ceo_result.get("okr_status"),
            "sources_used":         [
                {"domain": s.domain, "source_type": s.source_type, "filename": s.filename}
                for s in sources
            ],
            "logs":  logs_serializable,
            "error": ceo_result.get("error"),
        },
        "error": None,
    }


@router.post("/ceo/synthesize")
async def synthesize_ceo_from_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    CEO Synthesis from CompanyContext.

    Loads all available agent results from the authenticated user's org CompanyContext
    and runs CEO synthesis (cross-domain correlation → strategic priorities → board deck).

    This skips re-running CFO/CTO/CMO pipelines — it uses cached results.
    Much faster than /ceo/analyze for re-synthesis after new agent data arrives.

    Called by:
    - auto_chain when multiple agents complete
    - Frontend "Refresh CEO Analysis" button
    """
    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    org_id = current_user.org_id

    from app.agents.ceo.orchestrator import (
        DEFAULT_CEO_RUN_CONFIG,
        node_board_deck,
        node_condense_summaries,
        node_strategic_priorities,
        node_synthesis,
    )
    from app.services.company_context import get_company_context, save_company_context

    # Load company context
    ctx = await get_company_context(org_id, db)

    if not ctx.last_cfo_result and not ctx.last_cto_result:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No agent results found for org '{org_id}'. "
                "Run CFO and/or CTO analysis first."
            ),
        )

    job_id = str(uuid.uuid4())

    # Build initial CEOState from CompanyContext results
    # This bypasses the pipeline fan-out step entirely
    initial_state: dict[str, Any] = {
        "job_id": job_id,
        "company_name": ctx.company_name,
        "logs": [],
        "min_confidence": 1.0,
        "awaiting_review": False,
        # Inject all available agent results
        "_cfo_result":        ctx.last_cfo_result  or {},
        "_cto_result":        ctx.last_cto_result  or {},
        "_cmo_result":        ctx.last_cmo_result  or {},
        "_coo_result":        ctx.last_coo_result  or {},
        "_chro_result":       ctx.last_chro_result or {},
        "_risk_result":       ctx.last_risk_result or {},
        "_audit_result":      ctx.last_audit_result or {},
        "_compliance_result": ctx.last_compliance_result or {},
    }

    config = {"configurable": {"ceo_run_config": DEFAULT_CEO_RUN_CONFIG}}

    try:
        # Step 1: Condense summaries from all agent results
        state = await node_condense_summaries(initial_state, config)  # type: ignore[arg-type]

        # Step 2: Cross-domain synthesis (detect cross-risks)
        state = await node_synthesis(state, config)  # type: ignore[arg-type]

        # Step 3: Strategic priorities
        state = await node_strategic_priorities(state, config)  # type: ignore[arg-type]

        # Step 4: Board deck
        state = await node_board_deck(state, config)  # type: ignore[arg-type]

    except Exception as exc:
        logger.exception("CEO context synthesis failed for org=%s", org_id)
        raise HTTPException(status_code=500, detail=f"CEO synthesis failed: {exc}")

    # Save CEO result back to CompanyContext
    try:
        ctx_fresh = await get_company_context(org_id, db)
        ctx_fresh.update_agent_result("ceo", {
            "financial_summary":    state.get("financial_summary"),
            "tech_summary":         state.get("tech_summary"),
            "marketing_summary":    state.get("marketing_summary"),
            "ops_summary":          state.get("ops_summary"),
            "hr_summary":           state.get("hr_summary"),
            "cross_risks":          state.get("cross_risks") or [],
            "strategic_priorities": state.get("strategic_priorities") or [],
            "board_deck":           state.get("board_deck"),
            "sources": "company_context",
            "agents_used": [
                a for a in ["cfo", "cto", "cmo", "coo", "chro", "risk", "audit"]
                if getattr(ctx, f"last_{a}_result", None) is not None
            ],
        })
        await save_company_context(ctx_fresh, db)
        try:
            from app.services.semantic.rebuild import rebuild_semantic_snapshot

            await rebuild_semantic_snapshot(org_id, db, include_brief=True)
        except Exception as rebuild_exc:
            logger.warning("CEO synthesis semantic rebuild failed: %s", rebuild_exc)
    except Exception as exc:
        logger.warning("Failed to save CEO synthesis to context: %s", exc)

    logs_serializable = [
        {"step": lg.step, "ok": lg.ok, "detail": lg.detail, "confidence": lg.confidence}
        for lg in (state.get("logs") or [])
        if hasattr(lg, "step")
    ]

    agents_used = [
        a for a in ["cfo", "cto", "cmo", "coo", "chro", "risk"]
        if getattr(ctx, f"last_{a}_result", None) is not None
    ]

    return {
        "data": {
            "job_id":               job_id,
            "org_id":               org_id,
            "agents_used":          agents_used,
            "awaiting_review":      state.get("awaiting_review", False),
            "min_confidence":       state.get("min_confidence"),
            "overall_health_score": _compute_overall_health(dict(state)),
            "financial_summary":    state.get("financial_summary"),
            "tech_summary":         state.get("tech_summary"),
            "marketing_summary":    state.get("marketing_summary"),
            "ops_summary":          state.get("ops_summary"),
            "hr_summary":           state.get("hr_summary"),
            "cross_risks":          state.get("cross_risks") or [],
            "strategic_priorities": state.get("strategic_priorities") or [],
            "board_deck":           state.get("board_deck"),
            "logs":                 logs_serializable,
            "error":                state.get("error"),
        },
        "error": None,
    }


@router.get("/ceo/health-check")
async def ceo_health() -> dict[str, Any]:
    """Verify CEO pipeline agents are importable and graph compiles."""
    from app.agents.ceo.orchestrator import ceo_graph
    return {
        "data": {
            "status": "ok",
            "graph_nodes": list(ceo_graph.nodes.keys()) if hasattr(ceo_graph, "nodes") else [],
            "agents": ["synthesis", "strategic_priorities", "board_deck"],
            "sub_pipelines": ["cfo", "cto", "chro", "cmo", "coo"],
        },
        "error": None,
    }
