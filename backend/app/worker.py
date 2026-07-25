"""
ARQ Worker — async Redis-backed job queue.

Replaces FastAPI BackgroundTasks for CFO pipeline jobs.
- Jobs survive application restarts (stored in Redis)
- Worker runs as a separate process: `arq app.worker.WorkerSettings`
- FastAPI enqueues jobs via `arq.create_pool` — no coupling to request lifecycle

Usage:
    # In docker-compose / Dockerfile:
    arq app.worker.WorkerSettings

    # In FastAPI endpoint:
    from app.worker import enqueue_analysis
    await enqueue_analysis(job_id, budget_input)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings, ArqRedis

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── Task functions ─────────────────────────────────────────────────────────────

async def run_ceo_analysis(
    ctx: dict,
    job_id: str,
    # CFO inputs
    cfo_file_path: str | None = None,
    cfo_file_type: str | None = None,
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
) -> dict[str, Any]:
    """
    ARQ task: run the full CEO pipeline (CFO + CTO parallel) in background.

    Enqueued by POST /ceo/analyze-async — returns job_id immediately.
    Results stored in Redis with key ceo:{job_id} for 24h.
    """
    logger.info("ARQ worker: starting CEO analysis for job=%s", job_id)

    try:
        from app.agents.ceo.orchestrator import run_ceo_pipeline

        result = await run_ceo_pipeline(
            job_id=job_id,
            cfo_file_path=cfo_file_path,
            cfo_file_type=cfo_file_type,
            cfo_transactions=cfo_transactions,
            cfo_budget=cfo_budget,
            cloud_billing_csv=cloud_billing_csv,
            git_log_text=git_log_text,
            incident_csv=incident_csv,
            sprint_csv=sprint_csv,
            company_name=company_name,
            period=period,
        )

        # Store result in Redis for polling — key: ceo:{job_id}
        pool = await get_arq_pool()
        import json

        def _serialize(obj: Any) -> Any:
            if hasattr(obj, "__dataclass_fields__"):
                return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        serialized = json.dumps({
            "status": "completed",
            "job_id": job_id,
            "result": {
                "financial_summary":    result.get("financial_summary"),
                "tech_summary":         result.get("tech_summary"),
                "cross_risks":          result.get("cross_risks") or [],
                "strategic_priorities": result.get("strategic_priorities") or [],
                "board_deck":           result.get("board_deck"),
                "okr_status":           result.get("okr_status"),
                "awaiting_review":      result.get("awaiting_review", False),
                "min_confidence":       result.get("min_confidence"),
                "error":                result.get("error"),
                "logs": [
                    {"step": lg.step, "ok": lg.ok, "detail": lg.detail, "confidence": lg.confidence}
                    for lg in (result.get("logs") or [])
                ],
            },
        }, default=_serialize)

        await pool.set(f"ceo:{job_id}", serialized, ex=86400)  # 24h TTL

        logger.info("ARQ worker: CEO job=%s completed", job_id)
        return {"ok": True, "job_id": job_id}

    except Exception as exc:
        logger.exception("ARQ worker: CEO job=%s failed", job_id)
        pool = await get_arq_pool()
        import json
        await pool.set(
            f"ceo:{job_id}",
            json.dumps({"status": "failed", "job_id": job_id, "error": str(exc)}),
            ex=3600,
        )
        raise


async def run_cfo_analysis(
    ctx: dict,
    job_id: str,
    budget_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    ARQ task: run the full CFO pipeline and persist results to DB.
    Replaces `_run_and_persist` in api/analysis.py.

    Called by the ARQ worker process — NOT by the FastAPI request process.
    This means the job survives application restarts.
    """
    from app.database import get_session_factory, engine
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.transaction import Transaction
    from app.models.report import Report, ReportType, ReportFormat
    from app.models.anomaly import Anomaly
    from app.agents.orchestrator import run_cfo_pipeline
    from app.agents.state import AgentRunConfig

    from app.streaming.sse import publish_step_event, publish_job_done, publish_job_error

    logger.info("ARQ worker: starting CFO analysis for job=%s", job_id)

    async with get_session_factory(engine())() as db:
        job = await db.get(AnalysisJob, job_id)
        if not job:
            logger.error("ARQ worker: job=%s not found in DB", job_id)
            return {"ok": False, "error": "job not found"}

        job.status = JobStatus.ANALYZING
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            result = await run_cfo_pipeline(
                job_id=job_id,
                file_path=job.file_path,
                file_type=job.file_type,
                run_config=AgentRunConfig(require_review=False),
                budget_input=budget_input,
            )

            # Publish each completed step to SSE clients
            for log in result.get("logs") or []:
                await publish_step_event(
                    job_id=job_id,
                    step=log.step,
                    ok=log.ok,
                    detail=log.detail,
                    confidence=log.confidence,
                )

            # Persist transactions
            for tx_data in result.get("transactions") or []:
                tx = Transaction(
                    job_id=job_id,
                    amount_kurus=tx_data.get("amount_cents", 0),
                    currency=tx_data.get("currency", "USD"),
                    type=tx_data.get("type", "expense"),
                    category=tx_data.get("category", "other_expense"),
                    description=tx_data.get("description", ""),
                    vendor=tx_data.get("vendor"),
                    transaction_date=datetime.fromisoformat(tx_data["transaction_date"])
                    if tx_data.get("transaction_date")
                    else datetime.now(timezone.utc),
                    raw_text=tx_data.get("raw_text"),
                    confidence=tx_data.get("confidence"),
                )
                db.add(tx)

            # Persist dashboard JSON report
            if result.get("dashboard_json"):
                db.add(Report(
                    job_id=job_id,
                    report_type=ReportType.FULL,
                    report_format=ReportFormat.JSON,
                    data=result["dashboard_json"],
                ))

            # Persist Excel report reference
            report_paths = result.get("report_paths") or {}
            if report_paths.get("xlsx"):
                db.add(Report(
                    job_id=job_id,
                    report_type=ReportType.FULL,
                    report_format=ReportFormat.EXCEL,
                    file_path=report_paths["xlsx"],
                ))

            # Persist anomalies
            for a in result.get("anomalies") or []:
                db.add(Anomaly(
                    job_id=job_id,
                    anomaly_type=a.get("anomaly_type", "unknown"),
                    severity=a.get("severity", "medium"),
                    title=a.get("title", ""),
                    description=a.get("description", ""),
                    transaction_ids=a.get("transaction_ids"),
                    evidence=a.get("evidence"),
                    confidence=a.get("confidence"),
                ))

            logs_serializable = [
                {"step": lg.step, "ok": lg.ok, "detail": lg.detail, "confidence": lg.confidence}
                for lg in (result.get("logs") or [])
            ]
            job.status = (
                JobStatus.AWAITING_REVIEW if result.get("awaiting_review") else JobStatus.COMPLETED
            )
            job.logs = logs_serializable
            job.min_confidence = result.get("min_confidence")
            job.awaiting_review = bool(result.get("awaiting_review"))
            job.completed_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            await db.commit()

            # Notify SSE subscribers that the job is done
            await publish_job_done(job_id, status=str(job.status))

            logger.info(
                "ARQ worker: job=%s completed — status=%s awaiting_review=%s",
                job_id, job.status, job.awaiting_review,
            )
            return {"ok": True, "job_id": job_id, "status": str(job.status)}

        except Exception as exc:
            logger.exception("ARQ worker: job=%s failed", job_id)
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            await db.commit()
            # Notify SSE subscribers of failure (best-effort, non-fatal)
            try:
                await publish_job_error(job_id, str(exc))
            except Exception:
                pass
            raise  # ARQ will mark the job as failed and can retry


# ── Pool helper (used by FastAPI to enqueue) ───────────────────────────────────

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """Return singleton ARQ Redis pool (created lazily)."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def enqueue_analysis(
    job_id: str,
    budget_input: dict[str, Any] | None = None,
) -> None:
    """Enqueue a CFO analysis job. Called from FastAPI endpoint."""
    pool = await get_arq_pool()
    await pool.enqueue_job("run_cfo_analysis", job_id, budget_input)
    logger.info("Enqueued CFO analysis: job=%s", job_id)


async def enqueue_ceo_analysis(
    job_id: str,
    cfo_file_path: str | None = None,
    cfo_file_type: str | None = None,
    cfo_transactions: list[dict[str, Any]] | None = None,
    cfo_budget: dict[str, Any] | None = None,
    cloud_billing_csv: str | None = None,
    git_log_text: str | None = None,
    incident_csv: str | None = None,
    sprint_csv: str | None = None,
    company_name: str | None = None,
    period: str | None = None,
) -> None:
    """
    Enqueue a CEO analysis job. Called from POST /ceo/analyze-async.
    Returns immediately — result polled via GET /ceo/status/{job_id}.
    """
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_ceo_analysis",
        job_id,
        cfo_file_path=cfo_file_path,
        cfo_file_type=cfo_file_type,
        cfo_transactions=cfo_transactions,
        cfo_budget=cfo_budget,
        cloud_billing_csv=cloud_billing_csv,
        git_log_text=git_log_text,
        incident_csv=incident_csv,
        sprint_csv=sprint_csv,
        company_name=company_name,
        period=period,
    )
    # Mark job as pending in Redis immediately so polling returns a valid status
    import json
    await pool.set(
        f"ceo:{job_id}",
        json.dumps({"status": "pending", "job_id": job_id}),
        ex=86400,
    )
    logger.info("Enqueued CEO analysis: job=%s", job_id)


async def get_ceo_job_status(job_id: str) -> dict[str, Any]:
    """
    Poll CEO job status from Redis.
    Returns: {"status": "pending"|"completed"|"failed", "job_id": ..., "result": ...}
    """
    import json
    pool = await get_arq_pool()
    raw = await pool.get(f"ceo:{job_id}")
    if raw is None:
        return {"status": "not_found", "job_id": job_id}
    return json.loads(raw)


# ── ARQ Worker settings ────────────────────────────────────────────────────────

class WorkerSettings:
    """ARQ worker configuration. Run with: arq app.worker.WorkerSettings"""

    functions = [run_cfo_analysis, run_ceo_analysis]
    max_jobs = 10                   # concurrent jobs per worker process
    job_timeout = 600               # 10 minutes max per job
    keep_result = 86400             # keep job result in Redis for 24h
    retry_jobs = True
    max_tries = 2                   # retry once on failure

    @classmethod
    def redis_settings(cls) -> RedisSettings:
        settings = get_settings()
        return RedisSettings.from_dsn(settings.redis_url)
