"""What follows a completed CFO analysis (plan v10 §13.4 E1).

Split out of `worker.py`, which mixed queue plumbing, the analysis run itself and
everything that happens after it. This module is the "after": the company view read
from the ledger, the semantic snapshot, the auto-chain, cache invalidation, memory and
trend. It does not enqueue work; the one thing it takes from the queue module is the
Redis pool the trend alert is written to.

`worker.run_cfo_analysis` and `services.review_continuation` call
`continue_after_completion`; the company-view endpoints call `apply_company_view`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)


async def saved_result(job_id: str, db: Any) -> dict[str, Any]:
    """The parts of a finished analysis continue_after_completion reads,
    loaded from what the worker persisted (dashboard JSON report, anomalies)."""
    from sqlalchemy import desc, select

    from app.models.anomaly import Anomaly
    from app.models.report import Report, ReportFormat

    report = (await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )).scalar_one_or_none()
    anomalies = (await db.execute(select(Anomaly).where(Anomaly.job_id == job_id))).scalars().all()
    return {
        "dashboard_json": (report.data if report is not None else None) or {},
        "anomalies": [
            {
                "anomaly_type": a.anomaly_type,
                "severity": a.severity,
                "title": a.title,
                "description": a.description,
                "transaction_ids": a.transaction_ids,
                "evidence": a.evidence,
                "confidence": float(a.confidence) if a.confidence is not None else None,
            }
            for a in anomalies
        ],
    }


def cfo_chain_result(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """The CFO result as the company context stores it."""
    dashboard = result.get("dashboard_json") or {}
    return {
        "job_id":     job_id,
        "dashboard":  dashboard,
        "anomalies":  result.get("anomalies") or [],
        "forecast":   dashboard.get("forecast"),
        "pnl":        dashboard.get("pnl"),
        "cashflow":   dashboard.get("cashflow"),
    }


async def continue_after_completion(
    job_id: str, org_id: str, result: dict[str, Any], db: Any
) -> None:
    """What follows a completed CFO analysis: company context, semantic
    snapshot, the auto-chain, cache invalidation, memory and trend.

    Runs when the worker completes a job, and when a person approves one that
    was held for review — only dashboard_json and anomalies are read, both of
    which are persisted, so an approved job continues from what was saved.
    """
    chain_result = cfo_chain_result(job_id, result)

    # The company's record of its money (plan v9 §K1). Idempotent: if this fails
    # the analysis stands, and `scripts/ledger_backfill.py` repairs the ledger.
    try:
        from app.services.ledger import append_job

        await append_job(db, job_id)
    except Exception:
        logger.exception("Ledger append failed for job=%s", str(job_id).replace("\r", "").replace("\n", ""))
        await db.rollback()

    # Plan v9 §K1: the company's picture is read from its ledger, so one upload
    # adds what it holds and cannot replace the rest.
    await refresh_company_view(org_id, db, job_id=job_id, fallback=chain_result)
    # Job-level events happen for every completed analysis.
    _job_side_effects(job_id, org_id, result)


def _clean_id(value: str) -> str:
    """Ids reach here from HTTP requests and go into log lines: no CR/LF."""
    return str(value).replace("\r", "").replace("\n", "")


async def _note_company_view(db: Any, job_id: str | None, applied: bool, reason: str) -> None:
    """Record on the analysis what became of the company's view, and why."""
    from app.models.analysis_job import AnalysisJob

    job = await db.get(AnalysisJob, job_id) if job_id else None
    if job is not None:
        meta = dict(job.result_metadata or {})
        meta["company_view"] = {"applied": applied, "reason": reason}
        job.result_metadata = meta
        await db.commit()


async def _settle_held_views(db: Any, org_id: str, signature: str) -> bool:
    """Retire held views of an older ledger: approving one would bring old figures
    back. True if a view of this very ledger is already waiting for its owner."""
    from sqlalchemy import select

    from app.models.agent_job import AgentJob, AgentJobStatus

    held = (await db.execute(select(AgentJob).where(
        AgentJob.org_id == org_id,
        AgentJob.agent_type == "cfo",
        AgentJob.status == AgentJobStatus.AWAITING_REVIEW,
    ))).scalars().all()
    waiting = False
    for job in held:
        if (job.result_json or {}).get("ledger_signature") == signature:
            waiting = True
        else:
            job.status = AgentJobStatus.FAILED
            job.error_message = "Defter değişti; bu görünümün yerine yenisi hesaplandı."
    await db.commit()
    return waiting


async def _analyse_ledger(view: Any, org_id: str, job_id: str | None, db: Any) -> dict[str, Any]:
    """The CFO pipeline over the ledger's rows, with its AgentRun around it."""
    from app.agents import orchestrator
    from app.agents.run_ledger import agent_run

    async with agent_run(db, pipeline="cfo_ledger", org_id=org_id, job_id=job_id) as run:
        result = await orchestrator.run_cfo_pipeline(
            # Its own id: this is not the upload's analysis, and it must not
            # resume that run's checkpoint or overwrite its report.
            job_id=str(uuid.uuid4()),
            file_path="",
            file_type="ledger",
            org_id=org_id,
            ledger_view=view.for_pipeline(),
        )
        if result.get("halted"):
            run.row.status = "halted"
        elif result.get("awaiting_review"):
            run.row.status = "awaiting_review"
    return dict(result)


async def _publish_ledger_view(
    view: Any, result: dict[str, Any], org_id: str, active: str | None, db: Any
) -> tuple[str, dict[str, Any]]:
    """One write through the gate. Returns (why, what was written)."""
    from app.services.company_context import get_company_context
    from app.services.context_persist import persist_agent_completion

    result["dashboard_json"] = {**result["dashboard_json"], "source": "ledger", "period": view.period}
    chain = {**cfo_chain_result(active or "", result), "ledger_signature": view.signature}
    decision = await persist_agent_completion(
        org_id, "cfo",
        # The gate reads how the run went, so what it held can say why.
        {**chain, "logs": result.get("logs") or [], "min_confidence": result.get("min_confidence"),
         "awaiting_review": result.get("awaiting_review"), "error": result.get("error")},
        db, job_id=active, trigger_auto_chain=False, force_rebuild=True,
    )
    if decision.get("awaiting_review"):
        return "ledger_view_held", chain
    written = (await get_company_context(org_id, db)).last_cfo_result or {}
    # persist_agent_completion logs a failed save and returns; a chain run on a
    # context that was not written would synthesise the old view as if new.
    return ("ledger" if written.get("ledger_signature") == view.signature else "ledger_view_failed"), chain


async def _ledger_view_reason(
    org_id: str, db: Any, job_id: str | None, view: Any
) -> tuple[str, str | None, dict[str, Any] | None]:
    """(why, the analysis behind the view, what to chain) for a ledger with rows."""
    from app.services.company_context import get_company_context
    from app.services.company_view import ledger_view

    current = (await get_company_context(org_id, db)).last_cfo_result or {}
    active = job_id or current.get("job_id")
    waiting = await _settle_held_views(db, org_id, view.signature)
    if current.get("ledger_signature") == view.signature:
        return "ledger_unchanged", active, None
    if waiting:
        return "ledger_view_held", active, None

    result = await _analyse_ledger(view, org_id, active, db)
    if not result.get("dashboard_json"):
        logger.error("Ledger view produced no dashboard for org=%s", org_id)
        return "ledger_view_failed", active, None
    # Another upload or decision moved the ledger while this ran. Whatever moved
    # it runs after it, and reads more than this run did.
    moved = await ledger_view(db, org_id)
    if moved is None or moved.signature != view.signature:
        return "ledger_moved", active, None
    reason, chain = await _publish_ledger_view(view, result, org_id, active, db)
    return reason, active, chain


async def refresh_company_view(
    org_id: str, db: Any, *, job_id: str | None = None, fallback: dict[str, Any] | None = None
) -> bool:
    """Read the company's picture from its ledger; True if the picture changed.

    `job_id` is the analysis that prompted this, if one did; a person's decision
    on the ledger prompts it too. With no dated row to read, `fallback` (that
    analysis's own result) goes through the older rule instead.
    """
    from app.services.company_view import ledger_view

    org_id = _clean_id(org_id)
    job_id = _clean_id(job_id) if job_id else None
    try:
        view = await ledger_view(db, org_id)
        if view is None:
            if job_id and fallback:
                if await apply_company_view(job_id, org_id, fallback, db, force=False):
                    spawn_auto_chain(job_id, org_id, fallback)
                    return True
            return False
        reason, active, chain = await _ledger_view_reason(org_id, db, job_id, view)
        await _note_company_view(db, job_id, reason == "ledger", reason)
    except Exception:
        logger.exception("Company view from the ledger failed for org=%s", org_id)
        await db.rollback()
        await _note_company_view(db, job_id, False, "ledger_view_failed")
        return False
    if reason != "ledger" or chain is None:
        return False
    if active:
        # Only a new company picture re-runs what reads it (CEO synthesis…).
        spawn_auto_chain(active, org_id, chain)
    return True


async def refresh_company_view_detached(org_id: str) -> None:
    """For a request's background task: its own session, since the request's closes."""
    from app.core.background import with_session

    await with_session(lambda db: refresh_company_view(org_id, db))


async def apply_company_view(
    job_id: str, org_id: str, chain_result: dict[str, Any], db: Any, *, force: bool
) -> bool:
    """Make this analysis the company's active CFO view, unless it adds no
    period (`company_view.should_replace`) and the person did not ask for it.
    Records the decision on the job either way. Returns whether it applied."""
    from app.services.company_context import get_company_context, save_company_context
    from app.services.company_view import should_replace

    # Both reach here from an HTTP request (POST /analysis/{id}/company-view)
    # and are written into log lines below; strip CR/LF as run_cfo_analysis does.
    job_id = _clean_id(job_id)
    org_id = _clean_id(org_id)

    try:
        ctx_obj = await get_company_context(org_id, db)
        current = (ctx_obj.last_cfo_result or {}).get("dashboard")
        replace, reason = should_replace(current, chain_result.get("dashboard"))
        if force and chain_result.get("dashboard"):
            replace, reason = True, "applied_by_user"

        await _note_company_view(db, job_id, replace, reason)
        if not replace:
            logger.info(
                "Company view kept for org=%s: job=%s not applied (%s)", org_id, job_id, reason
            )
            return False

        ctx_obj.update_agent_result("cfo", chain_result)
        ctx_obj.set_active_job("cfo", str(job_id))
        await save_company_context(ctx_obj, db)
        from app.services.semantic.rebuild import rebuild_semantic_snapshot

        await rebuild_semantic_snapshot(org_id, db, include_brief=True)
        logger.info(
            "ARQ worker: CompanyContext + semantic persisted for org=%s job=%s",
            org_id,
            job_id,
        )
    except Exception as exc:
        # Not applied: running the auto-chain on a context that was not
        # written would synthesise from the old view as if it were new.
        logger.warning("ARQ worker: context/semantic persist failed (non-fatal): %s", exc)
        return False
    return True


def spawn_auto_chain(job_id: str, org_id: str, chain_result: dict[str, Any]) -> None:
    """Re-run what reads the company's CFO view (auto-chain → CEO …)."""
    from app.agents.orchestration.auto_chain import on_agent_complete
    from app.core.background import spawn

    spawn(
        on_agent_complete(
            agent="cfo",
            org_id=org_id,
            result=chain_result,
            db=None,
        ),
        name=f"auto-chain-cfo-{job_id[:8]}",
    )
    logger.info("ARQ worker: auto_chain triggered for cfo → org=%s", org_id)


def _job_side_effects(job_id: str, org_id: str, result: dict[str, Any]) -> None:
    """Cache invalidation, memory/trend and trigger events for a completed job."""
    from app.core.background import spawn

    # ── M3: Invalidate analytics cache on CFO completion ───────────
    async def _invalidate_analytics_cache(org_id: str) -> None:
        try:
            from app.services.cache_service import invalidate_org_analytics
            count = await invalidate_org_analytics(org_id)
            if count:
                logger.debug("Cache invalidated: org=%s keys=%d", org_id, count)
        except Exception as exc:
            logger.debug("Cache invalidation failed (non-fatal): %s", exc)

    spawn(_invalidate_analytics_cache(org_id), name=f"cache-invalidate-{job_id[:8]}")

    # ── S5-1/S5-2: Save to memory + run trend analysis ─────────────
    spawn(
        _save_to_memory_and_trend(
            org_id=org_id,
            job_id=job_id,
            result=result,
        ),
        name=f"memory-trend-{job_id[:8]}",
    )

    # ── P4-3: Trigger engine — job.completed / tx.arrived ──────────
    # Own session, fire-and-forget: a misbehaving trigger must never fail the
    # analysis it rode in on (same guard as cache invalidation above).
    async def _emit_trigger_events() -> None:
        try:
            from app.database import session_factory
            from app.services.triggers.sources import emit_job_events

            async with session_factory()() as trig_db:
                await emit_job_events(
                    trig_db,
                    job_id=str(job_id),
                    org_id=org_id,
                    dashboard=result.get("dashboard_json") or {},
                )
        except Exception as exc:
            logger.warning("trigger events failed (non-fatal): %s", exc)

    spawn(_emit_trigger_events(), name=f"triggers-{job_id[:8]}")


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
        from datetime import datetime

        from app.services.agent_memory import EpisodeRecord, get_memory_store
        from app.services.trend_detector import TrendDetector

        pnl = (result.get("dashboard_json") or {}).get("pnl") or {}
        anomalies = result.get("anomalies") or []
        period = datetime.now(UTC).strftime("%Y-%m")

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
        store.save(episode)

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
            import json

            from app.worker import get_arq_pool

            pool = await get_arq_pool()
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
