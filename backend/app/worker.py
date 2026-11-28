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

import asyncio
import functools
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis import exceptions as redis_exc

from app.config import get_settings
from app.core.preflight import enforce_or_exit
from app.core.tenancy import set_current_tenant

logger = logging.getLogger(__name__)

# The same logging as the API (app/main.py): JSON on stdout, the redaction filter, LOG_LEVEL. The arq command only
# configures its own loggers, so without this the worker's application lines (INFO: "CFO Scheduler started", outbox and
# job results) never reached the container log, and `dc logs worker | grep -i scheduler` (runbook) found nothing.
from app.services.telemetry import initialize_telemetry

initialize_telemetry(
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    json_logs=os.environ.get("LOG_FORMAT", "json").lower() == "json",
)

# The worker runs the scheduler and sends the mail: it gets the same production preflight as the API. A
# fatal finding (placeholder secret, no APP_ENV on Postgres, mail required but no sender) stops it here.
# The maintenance worker (arq app.worker.MaintenanceWorkerSettings) parses no uploads: the parser memory rule is the analysis worker's.
enforce_or_exit(get_settings(), process="worker-maintenance" if any(a.endswith("MaintenanceWorkerSettings") for a in sys.argv) else "worker")

# The erasure tombstone on every database write of company data (app/services/privacy/write_guard.py).
from app.services.privacy import write_guard as _write_guard

_write_guard.install()


class TransientWorkerError(RuntimeError):
    """Retryable infra error (network/redis/timeout)."""


# Strong refs to inline fallback runs — without these asyncio may garbage-collect
# a running task mid-pipeline.
_inline_tasks: set[asyncio.Task[Any]] = set()


def _log_inline_failure(task: asyncio.Task[Any]) -> None:
    """Inline runs have no worker to surface their traceback. Log it here."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Inline CFO analysis failed", exc_info=exc)


# Broker faults worth running inline for: the queue is unreachable right now.
# Deliberately excludes authentication and protocol errors — a wrong password or
# a refused command is a misconfiguration, and falling back to inline would hide
# it for as long as the deployment lives.
# redis-py's exceptions descend from RedisError, *not* from the builtins of the
# same name, so both families have to be named. AuthenticationError subclasses
# redis's ConnectionError, which is why the message check below is not optional.
_TRANSIENT_BROKER_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,             # builtins
    TimeoutError,                # builtins
    OSError,                     # socket-level: refused, reset, unreachable host
    redis_exc.ConnectionError,
    redis_exc.TimeoutError,
    redis_exc.BusyLoadingError,  # the server is starting up
)


def _is_transient_error(exc: Exception) -> bool:
    """Is this the broker being briefly unavailable, or something we should show?

    Classified by type first. The string markers used to include a bare
    "redis", which made any exception mentioning Redis transient — an
    authentication failure among them, so a wrong password would silently run
    every job inline and never be reported.
    """
    if isinstance(exc, _TRANSIENT_BROKER_ERRORS):
        # An auth error can arrive wrapped; the message is the only tell.
        txt = str(exc).lower()
        return not any(m in txt for m in ("auth", "wrongpass", "noperm", "denied"))
    txt = str(exc).lower()
    return any(
        m in txt
        for m in ("timeout", "temporar", "connection reset",
                  "connection refused", "network unreachable")
    )


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
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    ARQ task: run the full CEO pipeline (CFO + CTO parallel) in background.

    Enqueued by POST /ceo/analyze-async — returns job_id immediately.
    Results stored in Redis with key ceo:{job_id} for 24h.
    """
    logger.info("ARQ worker: starting CEO analysis for job=%s", job_id)
    owner = await get_ceo_job_owner(job_id)
    set_current_tenant((owner or {}).get("org_id"))

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
            org_id=org_id,
        )

        # The erasure tombstone: a company whose erasure was claimed while this ran gets no stored result.
        from app.services.privacy.tombstone import org_erased_now

        if await org_erased_now((owner or {}).get("org_id") or org_id):
            logger.warning("ARQ worker: CEO job=%s stopped: its organisation is being erased; nothing stored", job_id)
            return {"ok": False, "job_id": job_id, "erased": True}

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
            result_data.get("org_id") or result_data.get("job_id", "")[:8]
            # CEO synthesis result → update CompanyContext + trigger feedback rules

            from app.agents.orchestration.auto_chain import on_agent_complete as _oac
            from app.core.background import spawn

            spawn(_oac(
                agent="ceo",
                org_id=job_id,  # use job_id as org proxy if org_id not in result
                result={"job_id": job_id, "ceo_result": result},
                db=None,
            ), name=f"auto-chain-ceo-{job_id[:8]}")

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


async def _ek_belgeler(job_id: str, db: Any) -> list[dict[str, str]]:
    """The analysis's other financial documents, in the order they arrived."""
    from sqlalchemy import select

    from app.models.data_source import DataSource, DataSourceDomain, DataSourceType

    rows = (await db.execute(
        select(DataSource)
        .where(DataSource.job_id == job_id,
               DataSource.domain == DataSourceDomain.CFO,
               DataSource.source_type == DataSourceType.FINANCIAL_DOCUMENT)
        .order_by(DataSource.created_at)
    )).scalars().all()
    return [
        {"path": r.file_path,
         "type": (r.filename or "").rsplit(".", 1)[-1].lower(),
         "ad": r.filename or ""}
        for r in rows if r.file_path
    ]


def _records_run(fn: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[dict[str, Any]]]:
    """The CFO analysis with its AgentRun around it (plan v9 §K0 / §V6 S2)."""

    @functools.wraps(fn)
    async def wrapper(ctx: dict, job_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from app.agents.run_ledger import agent_run
        from app.database import engine, get_session_factory
        from app.models.analysis_job import AnalysisJob

        job_id = str(job_id).replace("\r", "").replace("\n", "")
        async with get_session_factory(engine())() as db:
            job = await db.get(AnalysisJob, job_id)
            if job is None:
                return await fn(ctx, job_id, *args, **kwargs)
            org_id = str(job.org_id) if job.org_id else None
            set_current_tenant(org_id)  # every LLM call of this job is made under this company's data mode
            await db.commit()
            async with agent_run(db, pipeline="cfo", org_id=org_id, job_id=job_id) as run:
                out = await fn(ctx, job_id, *args, **kwargs)
                if out.get("skipped"):
                    # A duplicate delivery ran nothing, so it is no run: it would
                    # count against the success rate of the run that did.
                    await db.delete(run.row)
                elif not out.get("ok"):
                    run.row.status = "failed"
                    run.row.error = str(out.get("error") or out.get("reason") or "")[:2000] or None
                elif "awaiting_review" in str(out.get("status") or "").lower():
                    run.row.status = "awaiting_review"
                return out

    return wrapper


@_records_run
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
    from app.agents.orchestrator import run_cfo_pipeline
    from app.agents.state import AgentRunConfig
    from app.database import engine, get_session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.anomaly import Anomaly
    from app.models.report import Report, ReportFormat, ReportType
    from app.services.ingest.persist import build_transaction
    from app.services.job_state import (
        claim_for_analysis,
        fail_job,
        finish_job,
        purge_job_outputs,
    )
    from app.services.privacy.tombstone import OrgErasedError
    from app.streaming.sse import publish_job_done, publish_job_error, publish_step_event

    # The id reaches here from an HTTP request. It is written into log lines
    # below, so a value carrying CR/LF could forge log entries; strip them.
    job_id = str(job_id).replace("\r", "").replace("\n", "")

    logger.info("ARQ worker: starting CFO analysis for job=%s", job_id)

    async with get_session_factory(engine())() as db:
        # Atomic claim — exactly one delivery of this job runs, however many
        # were enqueued (double-click, retry, inline + queued racing). A
        # duplicate delivery gets None and exits without writing a row.
        job = await claim_for_analysis(db, job_id)
        if job is None:
            current = await db.get(AnalysisJob, job_id)
            if current is None:
                logger.error("ARQ worker: job=%s not found in DB", job_id)
                return {"ok": False, "error": "job not found"}
            logger.warning(
                "ARQ worker: job=%s not claimable (status=%s) — duplicate delivery "
                "or terminal state; skipping without side effects",
                job_id,
                current.status,
            )
            return {
                "ok": False,
                "job_id": job_id,
                "status": str(current.status),
                "skipped": True,
                "reason": "not claimable",
            }

        started_at = datetime.now(UTC)
        if hasattr(job, "result_metadata"):
            meta = job.result_metadata or {}
            meta["analysis_started_at"] = started_at.isoformat()
            job.result_metadata = meta
        job.updated_at = started_at
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
            from app.config import get_settings as _gs

            run_config = AgentRunConfig(
                require_review=True,
                auto_proceed_min_confidence=_gs().agent_auto_proceed_min_confidence,
            )

            # More documents of the same analysis (several invoices dropped
            # together). Each used to start an analysis of its own.
            ek_belgeler = await _ek_belgeler(job_id, db)
            # The organisation's standing category corrections, loaded once
            # here — the pipeline's nodes hold no session (plan v5 §F0).
            from app.services.classifier import load_rules, rules_to_state

            org_id_str = str(job.org_id) if job.org_id else None
            category_rules = rules_to_state(await load_rules(org_id_str, db))
            # Close the read transaction before the long pipeline call: a
            # transaction left open across minutes of work is the exact pattern
            # that once wedged every other writer ("database is locked").
            # Not with rollback(): a rollback expires every loaded attribute,
            # and the next `job.file_path` then tried to lazy-load outside the
            # async context — MissingGreenlet, so every analysis on this path
            # failed. Load the job inside the async context, then commit the
            # read (expire_on_commit=False keeps the values).
            await db.refresh(job)
            await db.commit()

            # The balance the cash radar starts from, loaded here (the nodes hold no session):
            # the forecast's runway counts down from it, never from zero.
            from app.services.bank_accounts import proven_balance

            opening_cash = await proven_balance(db, org_id_str) if org_id_str else None
            await db.commit()

            result = await run_cfo_pipeline(
                job_id=job_id,
                file_path=job.file_path,
                file_type=job.file_type,
                run_config=run_config,
                budget_input=budget_input,
                ek_belgeler=ek_belgeler,
                # Without it every org-scoped step in the pipeline (memory,
                # the rules above) ran as if the job belonged to nobody.
                org_id=org_id_str,
                category_rules=category_rules,
                opening_cash=opening_cash,
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

            # The erasure tombstone, first statement of the outputs' transaction: a company whose erasure was
            # claimed while this ran gets nothing written (OrgErasedError, handled below), and an erasure that
            # starts now waits for this commit and then deletes what it wrote (app/services/privacy/tombstone.py).
            from app.services.privacy.tombstone import refuse_if_erased

            await refuse_if_erased(db, org_id_str)

            # A re-run recomputes: whatever a previous (failed) attempt left
            # behind goes first, so the tables hold one run's output — never a
            # union of two.
            await purge_job_outputs(db, job_id)

            # Persist transactions. A row that reaches here with no currency or
            # direction is not given one: it waits with the rows the extraction held.
            from app.services.held_rows import register_held

            held_rows: list[dict[str, Any]] = list(result.get("held_transactions") or [])
            persisted_rows: list[dict[str, Any]] = []
            # Every row is stored, each in its own currency: the pipeline's figures read the rows of one
            # currency (`agents/currency_split`), the transaction list and the journal lose nothing.
            for tx_data in [*(result.get("transactions") or []), *(result.get("foreign_transactions") or [])]:
                lacking = [
                    code for code, missing in (
                        ("currency_unknown", not str(tx_data.get("currency") or "").strip()),
                        ("direction_unknown", tx_data.get("type") not in ("income", "expense")),
                    ) if missing
                ]
                if lacking:
                    held_rows.append({**tx_data, "hold_reasons": lacking})
                    continue
                persisted_rows.append(tx_data)
            # One question, asked once: a row a person already released comes back
            # into this job as they answered it; a rejected or already waiting one
            # is not asked again.
            registered = await register_held(db, job_id, org_id_str, held_rows)
            persisted_rows.extend(registered["released_again"])
            for tx_data in persisted_rows:
                db.add(build_transaction(job_id, tx_data))

            # A person's single-row corrections survive a rerun (the rows above are new).
            from app.services.ledger_correction import apply_overrides

            await apply_overrides(db, org_id_str, job_id)

            # Counted in the same transaction as the rows they categorised.
            from app.services.classifier import record_hits

            await record_hits(result.get("category_rule_hits") or {}, db)

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
            terminal = (
                JobStatus.AWAITING_REVIEW if result.get("awaiting_review") else JobStatus.COMPLETED
            )
            completed_at = datetime.now(UTC)
            meta = dict(job.result_metadata or {})
            from app.services.ingest.summary import ingest_summary

            meta["ingest"] = ingest_summary(persisted_rows, registered, result.get("ingest_counts"))
            if result.get("pages_not_read"):   # pages of a PDF that yielded no text: shown on the upload result, held or not
                meta["ingest"]["pages_not_read"] = result["pages_not_read"]
            if terminal == JobStatus.AWAITING_REVIEW:
                from app.services.held_analysis import held_by

                why = held_by(result)
                if why is not None:
                    meta["held_by"] = why
            if terminal == JobStatus.COMPLETED and job.org_id:
                # What follows a completed analysis (ledger, company view,
                # chain) is owed from the moment the job reads completed, so the
                # debt is written in the same transaction. It used to run
                # inline after the commit with nothing recorded: a crash or the
                # job timeout in between, or a failed ledger append, left the
                # ledger and the radar without this upload and nobody knew.
                from app.services.review_continuation import BEKLIYOR

                meta["review"] = {"devam": BEKLIYOR, "devam_istendi": completed_at.isoformat()}
            from app.services.bank_balance import closing_balance

            # A statement with rows held for a person proves its balance over the whole file
            # (data_ingestion); the rows booked so far are only part of it.
            closing = result.get("statement_closing_balance") or closing_balance(
                list(result.get("transactions") or [])
            )
            if closing is not None:
                meta["closing_balance"] = closing
            # How far those balances are believed, and why not when they are not (what the radar and
            # the runway read); for a statement with held rows, the chain a person's answer re-reads.
            from app.services.bank_balance import assess, statement_extent
            from app.services.statement_account import account_identity

            meta["balance_proof"] = result.get("balance_proof") or assess(
                list(result.get("transactions") or []), result.get("ingest_counts"),
                identity=account_identity(str(result.get("raw_text") or "")) or None,
            )
            if result.get("statement_chain"):
                meta["statement_chain"] = {**result["statement_chain"], "period": result.get("statement_period")}

            # The days the statement covers (and the balances it opens and closes on): which
            # months of the company's cash are complete is read from these later.
            from app.services.coverage import apply_period

            extent = apply_period(
                result.get("statement_extent") or statement_extent(list(result.get("transactions") or [])),
                result.get("statement_period"),
                job.filename,
            )
            if extent is not None:
                meta["statement_extent"] = extent
            try:
                if meta.get("analysis_started_at"):
                    t0 = datetime.fromisoformat(meta["analysis_started_at"])
                    meta["job_completion_ms"] = int((completed_at - t0).total_seconds() * 1000)
            except Exception:
                pass
            # Persist conductor plan before auto-chain so ops/debug can inspect it.
            if job.org_id:
                try:
                    from app.agents.orchestration.auto_chain import build_conductor_plan_dict

                    plan_dict = await build_conductor_plan_dict(
                        org_id=str(job.org_id),
                        agent="cfo",
                        db=db,
                    )
                    if plan_dict:
                        meta["conductor_plan"] = plan_dict
                except Exception as exc:
                    logger.debug("conductor_plan metadata skipped: %s", exc)

            # One transaction for the outputs and the terminal status. The
            # guarded UPDATE's rowcount decides whether we still hold the
            # claim: if the reaper already failed this job, nothing — results
            # included — is written over its terminal state.
            won = await finish_job(
                db,
                job_id,
                status=terminal,
                values={
                    "logs": logs_serializable,
                    "min_confidence": result.get("min_confidence"),
                    "awaiting_review": bool(result.get("awaiting_review")),
                    "completed_at": completed_at,
                    "result_metadata": meta,
                },
            )
            if not won:
                await db.rollback()
                logger.error(
                    "ARQ worker: job=%s no longer held the claim at finish (reaped?) — "
                    "results discarded rather than written over the terminal state",
                    job_id,
                )
                await publish_job_error(
                    job_id,
                    "The job's state changed while it was running; these results were "
                    "discarded. Re-run the analysis.",
                )
                return {"ok": False, "job_id": job_id, "finish_lost": True}
            await db.commit()

            # A re-run asks nothing twice: rows a person already released or rejected come back as they
            # answered. The proof written above was read before those answers; read it again with them.
            if org_id_str and meta.get("statement_chain") and (
                registered["released_again"] or registered["already_rejected"]
            ):
                from app.services.balance_reverify import reverify

                await refuse_if_erased(db, org_id_str)
                await db.refresh(job)
                await reverify(db, org_id_str, {job_id: []})
                await db.commit()

            # Notify SSE subscribers that the job is done — before the slow
            # follow-ups below: a watcher's completion must not wait on RAG.
            await publish_job_done(job_id, status=str(terminal))

            logger.info(
                "ARQ worker: job=%s completed — status=%s awaiting_review=%s",
                job_id, terminal, bool(result.get("awaiting_review")),
            )

            # RAG indexing in its own transaction, after the analysis commit.
            # Embedding generation is a network call and used to sit inside the
            # outputs' write transaction — the open-across-I/O pattern this
            # file keeps having to repair.
            rag_indexed = 0
            if job.org_id:
                try:
                    from app.services.rag_service import index_job_text

                    # Prefer the pipeline-level `raw_text` if present; it is
                    # the canonical ingestion form used across evidence endpoints.
                    doc_text = (result.get("raw_text") or "").strip()
                    if not doc_text:
                        tx_raw_texts = [
                            (txd.get("raw_text") or "")
                            for txd in [*(result.get("transactions") or []), *(result.get("foreign_transactions") or [])]
                        ]
                        doc_text = "\n".join(tx_raw_texts).strip()
                    doc_text = doc_text[:80_000]  # chunking truncates further
                    if doc_text:
                        async with get_session_factory(engine())() as rag_db:
                            rag_indexed = await index_job_text(
                                rag_db,
                                org_id=str(job.org_id),
                                job_id=str(job_id),
                                source_type="cfo_transactions_raw",
                                raw_text=doc_text,
                            )
                            await rag_db.commit()
                except Exception as exc:
                    logger.debug("RAG indexing failed (non-fatal): %s", exc)

            # Embedding-count observability rides a small follow-up write.
            # Fresh read first: approval may have added its own metadata key
            # since this run committed, and a blind overwrite would drop it.
            if job.org_id and rag_indexed:
                try:
                    from sqlalchemy import func, select

                    from app.models.rag_chunk import RagChunk

                    fresh = await db.get(AnalysisJob, job_id)
                    if fresh is not None:
                        await db.refresh(fresh)
                        merged = dict(fresh.result_metadata or {})
                        emb_count = int(
                            (
                                await db.execute(
                                    select(func.count())
                                    .select_from(RagChunk)
                                    .where(
                                        RagChunk.job_id == job_id,
                                        RagChunk.embedding.isnot(None),
                                    )
                                )
                            ).scalar()
                            or 0
                        )
                        merged["rag_embeddings_indexed"] = emb_count
                        fresh.result_metadata = merged
                        await db.commit()
                except Exception as exc:
                    logger.debug("rag embedding count skipped: %s", exc)

            # ── FAZ-1A: Persist CompanyContext + semantic + auto-chain ─────────
            # Held while the job awaits review; run on approval instead
            # (app.api.analysis.approve_review).
            if terminal == JobStatus.COMPLETED and job.org_id:
                # Runs here and now, but through the owed-continuation record:
                # it claims the row, marks it done at the end, and a failure or
                # a death mid-way leaves it owed for the reaper to dispatch
                # again. The analysis itself is already committed and stands.
                from app.services.review_continuation import devam_et

                try:
                    await devam_et(str(job_id))
                except Exception:
                    logger.exception(
                        "ARQ worker: job=%s completed, continuation failed — left owed; "
                        "the reaper dispatches it again", job_id,
                    )

            return {"ok": True, "job_id": job_id, "status": str(terminal)}

        except OrgErasedError:
            # The company is being erased or was erased while this ran (the checkpoint saver or the outputs'
            # transaction refused): nothing is persisted, not even a failure on the job row, which the erasure
            # deleted or scrubbed. Not retried.
            await db.rollback()
            logger.warning("ARQ worker: job=%s stopped: its organisation is being erased; nothing persisted", job_id)
            return {"ok": False, "job_id": job_id, "erased": True, "retryable": False}
        except Exception as exc:
            logger.exception("ARQ worker: job=%s failed", job_id)
            transient = _is_transient_error(exc)
            # Discard first, then record the failure. Committing on this
            # session used to persist every half-written row alongside the
            # FAILED status — a failed run could leave partial transactions
            # behind for the report to pick up.
            await db.rollback()
            fresh_err: Any = None
            try:
                fresh_err = await db.get(AnalysisJob, job_id)
                if fresh_err is not None:
                    await db.refresh(fresh_err)
            except Exception:
                fresh_err = None
            meta_err: dict[str, Any] = dict(
                (fresh_err.result_metadata if fresh_err is not None else None) or {}
            )
            meta_err["worker_failure"] = {
                "retryable": transient,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "at": datetime.now(UTC).isoformat(),
            }
            # Guarded too: a reaper that already failed this job keeps its
            # terminal state and its error message.
            await fail_job(
                db,
                job_id,
                error=str(exc),
                values=(
                    {"result_metadata": meta_err, "awaiting_review": False}
                    if fresh_err is not None
                    else None
                ),
            )
            await db.commit()
            # Notify SSE subscribers of failure (best-effort, non-fatal)
            try:
                await publish_job_error(job_id, str(exc))
            except Exception:
                pass
            if transient:
                raise TransientWorkerError(str(exc))
            return {
                "ok": False,
                "job_id": job_id,
                "status": str(JobStatus.FAILED),
                "retryable": False,
            }


# ── Pool helper (used by FastAPI to enqueue) ───────────────────────────────────

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """Return singleton ARQ Redis pool (created lazily).

    The API is a producer, not a consumer: it must fail fast so the caller can
    fall back, not hold an HTTP request open through ARQ's default retry ladder
    (5 attempts x 1s delay = ~17s before the first error surfaces).
    """
    global _pool
    if _pool is None:
        settings = get_settings()
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        redis_settings.conn_retries = settings.arq_producer_conn_retries
        _pool = await create_pool(redis_settings)
    return _pool




async def run_rag_backfill_maintenance(ctx: dict) -> dict[str, Any]:
    """
    ARQ maintenance task: backfill missing rag_chunks for recently completed jobs.
    Runs on the maintenance queue so analysis throughput stays isolated under load.
    """
    from sqlalchemy import func, select

    from app.database import engine, get_session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.rag_chunk import RagChunk
    from app.models.transaction import Transaction
    from app.services.rag_service import index_job_text

    settings = get_settings()
    if not settings.rag_backfill_enabled:
        return {"ok": True, "skipped": True, "reason": "disabled"}

    lookback_days = max(1, settings.rag_backfill_lookback_days)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

    checked = 0
    indexed = 0
    embeddings_backfilled = 0
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

        # Phase 2: embed chunks that have no vector, or one that does not match the company's current data
        # mode / pseudonym key (bounded, idempotent, resumable: app/services/rag_reindex.py)
        from app.services.rag_reindex import reindex_batch

        embeddings_backfilled = await reindex_batch(db)

        if indexed > 0 or embeddings_backfilled > 0:
            await db.commit()

    logger.info(
        "Maintenance RAG backfill: checked=%d indexed=%d embeddings=%d lookback_days=%d",
        checked,
        indexed,
        embeddings_backfilled,
        lookback_days,
    )
    return {
        "ok": True,
        "checked": checked,
        "indexed": indexed,
        "embeddings_backfilled": embeddings_backfilled,
    }


async def run_usage_prune_maintenance(ctx: dict) -> dict[str, Any]:
    """ARQ maintenance task: prune usage_events older than 90 days."""
    from app.database import engine, get_session_factory
    from app.services.usage_meter import prune_old_usage_events

    async with get_session_factory(engine())() as db:
        deleted = await prune_old_usage_events(db=db, days=90)
    logger.info("Maintenance usage prune: deleted=%d", deleted)
    return {"ok": True, "deleted": deleted}


async def run_semantic_rebuild(ctx: dict, org_id: str) -> dict[str, Any]:
    """ARQ maintenance task: rebuild semantic snapshot after a debounce skip."""
    from app.database import engine, get_session_factory
    from app.services.semantic.rebuild import rebuild_semantic_snapshot

    set_current_tenant(str(org_id))
    async with get_session_factory(engine())() as db:
        snap = await rebuild_semantic_snapshot(str(org_id), db, include_brief=True)
    ok = snap is not None
    logger.info(
        "Maintenance semantic rebuild org=%s ok=%s period=%s metrics=%s",
        org_id,
        ok,
        snap.period.key if snap else None,
        len(snap.metrics) if snap else 0,
    )
    return {
        "ok": ok,
        "org_id": str(org_id),
        "period": snap.period.key if snap else None,
        "metric_count": len(snap.metrics) if snap else 0,
        "awaiting_review": bool(snap.brief and snap.brief.awaiting_review) if snap else None,
    }


async def run_review_continuation(ctx: dict, job_id: str) -> dict[str, Any]:
    """ARQ maintenance task: what an approval releases (see services.review_continuation)."""
    from app.services.review_continuation import devam_et

    return await devam_et(str(job_id))


async def enqueue_semantic_rebuild_job(org_id: str, *, defer_by: float = 0.0) -> bool:
    """Enqueue a per-org trailing semantic rebuild on the maintenance queue."""
    pool = await get_arq_pool()
    settings = get_settings()
    lock_key = f"semantic:rebuild:pending:{org_id}"
    ttl = max(int(defer_by) + 5, 15)
    try:
        acquired = await pool.set(lock_key, "1", ex=ttl, nx=True)
        if not acquired:
            logger.debug("Semantic rebuild already pending org=%s", org_id)
            return True
    except Exception as exc:
        logger.debug("Semantic rebuild lock failed org=%s: %s", org_id, exc)

    job_kwargs: dict[str, Any] = {"_queue_name": settings.arq_maintenance_queue_name}
    if defer_by and defer_by > 0:
        job_kwargs["_defer_by"] = timedelta(seconds=defer_by)
    await pool.enqueue_job("run_semantic_rebuild", org_id, **job_kwargs)
    logger.info("Enqueued trailing semantic rebuild org=%s defer_by=%.1fs", org_id, defer_by)
    return True


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
) -> str:
    """Enqueue a CFO analysis job. Called from FastAPI endpoint.

    Returns how the work was dispatched: `"queued"` when the broker took it, or
    `"inline"` when it ran in this process instead. Callers report that rather
    than a bare boolean, because the two are not the same promise — an inline
    run dies with the process and is never retried, and a caller that says
    "queued" either way tells the user their work is safe when it is not.

    Inline only happens for a broker that is briefly unreachable and only when
    `allow_inline_job_fallback` is set. An authentication or protocol failure
    propagates: that is a misconfiguration, and hiding it behind a working
    upload would keep it hidden for the life of the deployment.
    """
    settings = get_settings()
    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_cfo_analysis",
            job_id,
            budget_input,
            _queue_name=settings.arq_analysis_queue_name,
        )
    except Exception as exc:
        if not (settings.allow_inline_job_fallback and _is_transient_error(exc)):
            raise
        global _pool
        _pool = None  # poisoned singleton — force a fresh connect next time
        logger.warning(
            "Broker unreachable (%s) — running CFO analysis inline for job=%s. "
            "No durability: this run will not survive a restart and is not retried.",
            exc,
            job_id,
        )
        # Fire-and-forget: `enqueue_analysis` must return immediately — callers
        # poll job status / subscribe to SSE. Awaiting here would hold the HTTP
        # request open for the whole pipeline.
        task = asyncio.create_task(run_cfo_analysis({}, job_id, budget_input))
        _inline_tasks.add(task)
        task.add_done_callback(_inline_tasks.discard)
        task.add_done_callback(_log_inline_failure)
        return "inline"
    logger.info("Enqueued CFO analysis: job=%s", job_id)
    # Hand the reaper a clock: if no worker ever claims this job, the enqueue
    # lease expires and the job fails visibly instead of sitting `pending`
    # forever. Best-effort — the claim in the worker is the real guard.
    await _stamp_enqueue_lease(job_id)
    return "queued"


async def _stamp_enqueue_lease(job_id: str) -> None:
    """Best-effort: never let lease bookkeeping fail a working dispatch."""
    try:
        from app.database import engine, get_session_factory
        from app.services.job_state import mark_enqueue_lease

        async with get_session_factory(engine())() as db:
            await mark_enqueue_lease(db, job_id)
    except Exception as exc:
        logger.debug("Enqueue lease not stamped for job=%s: %s", job_id, exc)


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
    org_id: str | None = None,
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
        org_id=org_id,
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


async def record_ceo_job_owner(job_id: str, *, org_id: Any, user_id: Any) -> None:
    """Remember who started a CEO job, for as long as its status is kept.

    CEO job ids live only in Redis and the status route took no user, so any
    caller holding an id read the whole board deck. The owner is stored beside
    the status with the same lifetime and checked on every poll.
    """
    import json

    pool = await get_arq_pool()
    await pool.set(
        f"ceo:{job_id}:owner",
        json.dumps({"org_id": str(org_id) if org_id else None, "user_id": str(user_id)}),
        ex=86400,
    )


async def get_ceo_job_owner(job_id: str) -> dict[str, Any] | None:
    """The recorded owner of a CEO job, or None if unknown or unreachable."""
    import json

    try:
        pool = await get_arq_pool()
        raw = await pool.get(f"ceo:{job_id}:owner")
    except Exception as exc:
        if not _is_transient_error(exc):
            raise
        return None
    if raw is None:
        return None
    data = json.loads(raw)
    return {"org_id": data.get("org_id"), "user_id": data.get("user_id")}


async def get_ceo_job_status(job_id: str) -> dict[str, Any]:
    """
    Poll CEO job status from Redis.
    Returns: {"status": "pending"|"completed"|"failed", "job_id": ..., "result": ...}
    """
    import json

    # CEO job status lives only in Redis. With no broker there is nothing to
    # poll — say so, rather than letting a connection timeout become a 500 the
    # caller cannot act on.
    try:
        pool = await get_arq_pool()
        raw = await pool.get(f"ceo:{job_id}")
    except Exception as exc:
        if not _is_transient_error(exc):
            raise
        global _pool
        _pool = None
        logger.warning("CEO job status unavailable — broker unreachable: %s", exc)
        return {"status": "unavailable", "job_id": job_id, "error": str(exc)}
    if raw is None:
        return {"status": "not_found", "job_id": job_id}
    return json.loads(raw)


# ── ARQ Worker settings ────────────────────────────────────────────────────────

async def _verify_checkpointer(ctx: dict[str, Any]) -> None:
    """Production: a durable checkpointer that cannot be built stops this worker (no per-process fallback)."""
    import asyncio

    from app.agents.checkpointer import verify_checkpointer

    await asyncio.to_thread(verify_checkpointer)


async def _start_crons(ctx: dict[str, Any]) -> None:
    """Run APScheduler here when SCHEDULER_PROCESS=worker (staging/prod)."""
    from app.scheduler import start_scheduler

    await _verify_checkpointer(ctx)
    start_scheduler("worker")


async def _stop_crons(ctx: dict[str, Any]) -> None:
    from app.scheduler import stop_scheduler

    stop_scheduler()


class WorkerSettings:
    """ARQ worker configuration. Run with: arq app.worker.WorkerSettings"""

    functions = [run_cfo_analysis, run_ceo_analysis]
    queue_name = get_settings().arq_analysis_queue_name
    max_jobs = get_settings().arq_analysis_max_jobs  # concurrent jobs per worker process
    job_timeout = 600               # 10 minutes max per job
    keep_result = 86400             # keep job result in Redis for 24h
    retry_jobs = True
    max_tries = 2                   # retry once on failure
    # The crons live in this worker type only — never in the maintenance one.
    on_startup = _start_crons
    on_shutdown = _stop_crons
    # Deploy and `docker stop`: on SIGTERM let running jobs finish (up to a full
    # job_timeout) before cancelling them. docker-compose.prod.yml's
    # stop_grace_period must stay above this.
    job_completion_wait = 600
    # The health key `arq --check` (container healthcheck) and /api/v1/ready
    # read; arq's default of 3600 s would report a dead worker for an hour.
    health_check_interval = 30

    # A plain attribute: arq reads the settings class's `__dict__`, so a classmethod here is handed over as the raw
    # descriptor and `create_pool` fails with "'classmethod' object has no attribute 'host'" (the worker never started).
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


from app.services.privacy.jobs import run_data_export  # KVKK company export


class MaintenanceWorkerSettings:
    """
    Dedicated queue for maintenance workloads (backfill, cleanup, long non-user jobs).
    This isolates user-facing analysis throughput under high traffic.
    """

    functions = [run_rag_backfill_maintenance, run_usage_prune_maintenance, run_semantic_rebuild,
                 run_review_continuation, run_data_export]
    queue_name = get_settings().arq_maintenance_queue_name
    max_jobs = get_settings().arq_maintenance_max_jobs
    job_timeout = 1200
    keep_result = 86400
    retry_jobs = True
    max_tries = 2
    job_completion_wait = 300       # docker-compose.prod.yml stop_grace_period stays above this
    health_check_interval = 30      # see WorkerSettings
    # run_review_continuation reaches run_cfo_pipeline (post_completion): build the saver at startup, off the event
    # loop, so production stops here and not inside a job (no crons in this worker type).
    on_startup = _verify_checkpointer

    # A plain attribute: arq reads the settings class's `__dict__`, so a classmethod here is handed over as the raw
    # descriptor and `create_pool` fails with "'classmethod' object has no attribute 'host'" (the worker never started).
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
