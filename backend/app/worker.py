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
from datetime import datetime, timedelta, timezone
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings, ArqRedis

from app.config import get_settings

logger = logging.getLogger(__name__)


class TransientWorkerError(RuntimeError):
    """Retryable infra error (network/redis/timeout)."""


def _is_transient_error(exc: Exception) -> bool:
    txt = str(exc).lower()
    transient_markers = (
        "timeout",
        "temporar",
        "connection reset",
        "connection refused",
        "network",
        "redis",
    )
    return any(m in txt for m in transient_markers)


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

        # FAZ-4B: trigger cross-domain correlation for ceo agent
        if result_data := result:
            org_id_from_result = result_data.get("org_id") or result_data.get("job_id", "")[:8]
            # CEO synthesis result → update CompanyContext + trigger feedback rules
            import asyncio
            from app.services.auto_chain import on_agent_complete as _oac
            asyncio.create_task(_oac(
                agent="ceo",
                org_id=job_id,  # use job_id as org proxy if org_id not in result
                result={"job_id": job_id, "ceo_result": result},
                db=None,
            ))

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
        started_at = datetime.now(timezone.utc)
        if hasattr(job, "result_metadata"):
            meta = job.result_metadata or {}
            meta["analysis_started_at"] = started_at.isoformat()
            job.result_metadata = meta
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # ── FAZ-1C: CapabilityRouter pre-flight check ──────────────────
            # Build a minimal state to let the router decide which agents run.
            # If Redis / file not yet parsed, we proceed with defaults.
            from app.services.capability_router import get_capability_router

            _preflight_state: dict[str, Any] = {"file_path": job.file_path}
            _routing_plan = get_capability_router().route(_preflight_state)
            logger.info(
                "CapabilityRouter pre-flight: job=%s — %s",
                job_id, _routing_plan.summary(),
            )
            # Pass routing plan to pipeline so it can skip unavailable agents
            run_config = AgentRunConfig(require_review=True)

            result = await run_cfo_pipeline(
                job_id=job_id,
                file_path=job.file_path,
                file_type=job.file_type,
                run_config=run_config,
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

            # RAG (v1) indexing: store CFO raw_text evidence chunks.
            # Non-fatal: indexleme başarısız olsa bile job raporu yine yayınlanır.
            try:
                if job.org_id:
                    from app.services.rag_service import index_job_text

                    # Prefer the pipeline-level `raw_text` if present; it is the
                    # canonical ingestion form used across evidence endpoints.
                    doc_text = (result.get("raw_text") or "").strip()
                    if not doc_text:
                        tx_raw_texts = [
                            (txd.get("raw_text") or "")
                            for txd in (result.get("transactions") or [])
                        ]
                        doc_text = "\n".join(tx_raw_texts).strip()
                    # Keep storage bounded (chunk_text itself will be truncated by service).
                    doc_text = doc_text[:80_000]

                    await index_job_text(
                        db,
                        org_id=str(job.org_id),
                        job_id=str(job_id),
                        source_type="cfo_transactions_raw",
                        raw_text=doc_text,
                    )
            except Exception as exc:
                logger.debug("RAG indexing failed (non-fatal): %s", exc)

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
            completed_at = datetime.now(timezone.utc)
            job.completed_at = completed_at
            job.updated_at = datetime.now(timezone.utc)
            if hasattr(job, "result_metadata"):
                meta = job.result_metadata or {}
                try:
                    if meta.get("analysis_started_at"):
                        t0 = datetime.fromisoformat(meta["analysis_started_at"])
                        meta["job_completion_ms"] = int((completed_at - t0).total_seconds() * 1000)
                except Exception:
                    pass
                job.result_metadata = meta
            await db.commit()

            # Notify SSE subscribers that the job is done
            await publish_job_done(job_id, status=str(job.status))

            logger.info(
                "ARQ worker: job=%s completed — status=%s awaiting_review=%s",
                job_id, job.status, job.awaiting_review,
            )

            # ── FAZ-1A: Trigger auto-chain (fire-and-forget) ──────────────────
            if job.status == JobStatus.COMPLETED and job.org_id:
                import asyncio
                from app.services.auto_chain import on_agent_complete

                chain_result: dict[str, Any] = {
                    "job_id":     job_id,
                    "dashboard":  result.get("dashboard_json") or {},
                    "anomalies":  result.get("anomalies") or [],
                    "forecast":   (result.get("dashboard_json") or {}).get("forecast"),
                    "pnl":        (result.get("dashboard_json") or {}).get("pnl"),
                    "cashflow":   (result.get("dashboard_json") or {}).get("cashflow"),
                }

                asyncio.create_task(
                    on_agent_complete(
                        agent="cfo",
                        org_id=job.org_id,
                        result=chain_result,
                        db=None,
                    )
                )
                logger.info("ARQ worker: auto_chain triggered for cfo → org=%s", job.org_id)

                # ── M3: Invalidate analytics cache on CFO completion ───────────
                async def _invalidate_analytics_cache(org_id: str) -> None:
                    try:
                        from app.services.cache_service import invalidate_org_analytics
                        count = await invalidate_org_analytics(org_id)
                        if count:
                            logger.debug("Cache invalidated: org=%s keys=%d", org_id, count)
                    except Exception as exc:
                        logger.debug("Cache invalidation failed (non-fatal): %s", exc)

                asyncio.create_task(_invalidate_analytics_cache(str(job.org_id)))

                # ── S5-1/S5-2: Save to memory + run trend analysis ─────────────
                asyncio.create_task(
                    _save_to_memory_and_trend(
                        org_id=job.org_id,
                        job_id=job_id,
                        result=result,
                    )
                )

            return {"ok": True, "job_id": job_id, "status": str(job.status)}

        except Exception as exc:
            logger.exception("ARQ worker: job=%s failed", job_id)
            transient = _is_transient_error(exc)
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            meta = (job.result_metadata or {}) if hasattr(job, "result_metadata") else {}
            meta["worker_failure"] = {
                "retryable": transient,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "at": datetime.now(timezone.utc).isoformat(),
            }
            if hasattr(job, "result_metadata"):
                job.result_metadata = meta
            job.updated_at = datetime.now(timezone.utc)
            await db.commit()
            # Notify SSE subscribers of failure (best-effort, non-fatal)
            try:
                await publish_job_error(job_id, str(exc))
            except Exception:
                pass
            if transient:
                raise TransientWorkerError(str(exc))
            return {"ok": False, "job_id": job_id, "status": str(job.status), "retryable": False}


# ── Pool helper (used by FastAPI to enqueue) ───────────────────────────────────

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """Return singleton ARQ Redis pool (created lazily)."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def _save_to_memory_and_trend(
    org_id: str,
    job_id: str,
    result: dict[str, Any],
) -> None:
    """
    S5-1/S5-2: Save CFO result to memory store and run trend analysis.
    Fire-and-forget background task — non-fatal.
    """
    try:
        from app.services.agent_memory import get_memory_store, EpisodeRecord
        from app.services.trend_detector import TrendDetector
        from datetime import datetime, timezone

        pnl = (result.get("dashboard_json") or {}).get("pnl") or {}
        anomalies = result.get("anomalies") or []
        period = datetime.now(timezone.utc).strftime("%Y-%m")

        store = get_memory_store()  # auto-configured from settings

        # Save episode to memory
        episode = EpisodeRecord(
            org_id=org_id,
            agent="pnl_agent",
            period=period,
            summary={
                "revenue":      pnl.get("revenue"),
                "net_income":   pnl.get("net_income"),
                "net_margin":   pnl.get("net_margin"),
                "ebitda":       pnl.get("ebitda"),
                "anomalies":    [{"anomaly_type": a.get("anomaly_type"), "severity": a.get("severity")} for a in anomalies[:10]],
            },
            narrative=pnl.get("narrative", ""),
            job_id=job_id,
        )
        await store.save(episode)

        # Run trend analysis
        detector = TrendDetector(memory_store=store)
        trend_result = await detector.analyze(
            org_id=org_id,
            current_pnl=pnl,
            current_anomalies=anomalies,
            current_period=period,
        )

        # Store trend analysis in Redis for the frontend to read
        if trend_result.trend_alerts or trend_result.recurring_anomalies:
            pool = await get_arq_pool()
            import json
            await pool.set(
                f"trend:{org_id}",
                json.dumps(trend_result.to_dict()),
                ex=86400,  # 24h TTL
            )
            logger.info(
                "Trend analysis: org=%s alerts=%d recurring=%d",
                org_id,
                len(trend_result.trend_alerts),
                len(trend_result.recurring_anomalies),
            )

    except Exception as exc:
        logger.debug("Memory+trend save failed (non-fatal): %s", exc)


async def run_rag_backfill_maintenance(ctx: dict) -> dict[str, Any]:
    """
    ARQ maintenance task: backfill missing rag_chunks for recently completed jobs.
    Runs on the maintenance queue so analysis throughput stays isolated under load.
    """
    from app.database import get_session_factory, engine
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.transaction import Transaction
    from app.models.rag_chunk import RagChunk
    from app.services.rag_service import index_job_text
    from sqlalchemy import func, select

    settings = get_settings()
    if not settings.rag_backfill_enabled:
        return {"ok": True, "skipped": True, "reason": "disabled"}

    lookback_days = max(1, settings.rag_backfill_lookback_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    checked = 0
    indexed = 0
    async with get_session_factory(engine())() as db:
        jobs_result = await db.execute(
            select(AnalysisJob).where(
                AnalysisJob.status == JobStatus.COMPLETED,
                AnalysisJob.completed_at.isnot(None),
                AnalysisJob.completed_at >= cutoff,
                AnalysisJob.org_id.isnot(None),
            )
        )
        jobs = jobs_result.scalars().all()
        for job in jobs:
            checked += 1
            count_result = await db.execute(
                select(func.count()).select_from(RagChunk).where(
                    RagChunk.org_id == str(job.org_id),
                    RagChunk.job_id == str(job.id),
                    RagChunk.source_type == "cfo_transactions_raw",
                )
            )
            if int(count_result.scalar() or 0) > 0:
                continue

            tx_result = await db.execute(
                select(Transaction.raw_text).where(Transaction.job_id == job.id)
            )
            doc_text = "\n".join((row[0] or "") for row in tx_result.all()).strip()
            if not doc_text:
                continue

            added = await index_job_text(
                db,
                org_id=str(job.org_id),
                job_id=str(job.id),
                source_type="cfo_transactions_raw",
                raw_text=doc_text[:80_000],
            )
            if added > 0:
                indexed += 1

        if indexed > 0:
            await db.commit()

    logger.info(
        "Maintenance RAG backfill: checked=%d indexed=%d lookback_days=%d",
        checked,
        indexed,
        lookback_days,
    )
    return {"ok": True, "checked": checked, "indexed": indexed}


async def run_usage_prune_maintenance(ctx: dict) -> dict[str, Any]:
    """ARQ maintenance task: prune usage_events older than 90 days."""
    from app.database import get_session_factory, engine
    from app.services.usage_meter import prune_old_usage_events

    async with get_session_factory(engine())() as db:
        deleted = await prune_old_usage_events(db=db, days=90)
    logger.info("Maintenance usage prune: deleted=%d", deleted)
    return {"ok": True, "deleted": deleted}


async def enqueue_maintenance_job(task_name: str, *args: Any, **kwargs: Any) -> bool:
    """
    Enqueue a job on the maintenance queue.
    Uses a short Redis lock to avoid duplicate enqueues when scheduler overlaps.
    """
    pool = await get_arq_pool()
    settings = get_settings()
    lock_key = f"maintenance:enqueue:{task_name}"
    try:
        acquired = await pool.set(lock_key, "1", ex=900, nx=True)
        if not acquired:
            logger.debug("Maintenance enqueue skipped (lock): %s", task_name)
            return False
    except Exception as exc:
        logger.warning("Maintenance enqueue lock failed for %s: %s", task_name, exc)

    await pool.enqueue_job(
        task_name,
        *args,
        _queue_name=settings.arq_maintenance_queue_name,
        **kwargs,
    )
    logger.info("Enqueued maintenance job: %s", task_name)
    return True


async def enqueue_analysis(
    job_id: str,
    budget_input: dict[str, Any] | None = None,
) -> None:
    """Enqueue a CFO analysis job. Called from FastAPI endpoint."""
    pool = await get_arq_pool()
    settings = get_settings()
    await pool.enqueue_job(
        "run_cfo_analysis",
        job_id,
        budget_input,
        _queue_name=settings.arq_analysis_queue_name,
    )
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
    settings = get_settings()
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
        _queue_name=settings.arq_analysis_queue_name,
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
    queue_name = get_settings().arq_analysis_queue_name
    max_jobs = get_settings().arq_analysis_max_jobs  # concurrent jobs per worker process
    job_timeout = 600               # 10 minutes max per job
    keep_result = 86400             # keep job result in Redis for 24h
    retry_jobs = True
    max_tries = 2                   # retry once on failure

    @classmethod
    def redis_settings(cls) -> RedisSettings:
        settings = get_settings()
        return RedisSettings.from_dsn(settings.redis_url)


class MaintenanceWorkerSettings:
    """
    Dedicated queue for maintenance workloads (backfill, cleanup, long non-user jobs).
    This isolates user-facing analysis throughput under high traffic.
    """

    functions = [run_rag_backfill_maintenance, run_usage_prune_maintenance]
    queue_name = get_settings().arq_maintenance_queue_name
    max_jobs = get_settings().arq_maintenance_max_jobs
    job_timeout = 1200
    keep_result = 86400
    retry_jobs = True
    max_tries = 2
    @classmethod
    def redis_settings(cls) -> RedisSettings:
        settings = get_settings()
        return RedisSettings.from_dsn(settings.redis_url)
