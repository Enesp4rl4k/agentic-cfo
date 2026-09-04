"""
System Management API

Provides unified operational visibility for:
  - core infrastructure health (DB, Redis, imports)
  - platform operations overview (job statuses, recent failures, sync status)
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import as_utc
from app.database import get_db
from app.models.agent_conflict import AgentConflict
from app.models.analysis_job import AnalysisJob
from app.models.sync_run import SyncRun

router = APIRouter(tags=["system"])
OPS_SCHEMA_VERSION = "v1.2"
SLA_ANALYZING_BREACH_MINUTES = 15

ERROR_BUDGETS = {
    "analysis": {"weekly_failure_rate_target_pct": 2.0},
    "chat": {"weekly_failure_rate_target_pct": 1.0},
    "sync": {"weekly_failure_rate_target_pct": 3.0},
}


async def _check_redis() -> dict[str, Any]:
    try:
        import redis.asyncio as redis  # type: ignore[import]

        from app.config import get_settings

        settings = get_settings()
        client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()
        await client.aclose()
        return {"ok": True, "detail": "redis ping ok"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


async def _queue_depths() -> dict[str, int]:
    try:
        import redis.asyncio as redis  # type: ignore[import]

        from app.config import get_settings

        settings = get_settings()
        client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        analysis_depth = int(await client.llen(settings.arq_analysis_queue_name))
        maintenance_depth = int(await client.llen(settings.arq_maintenance_queue_name))
        await client.aclose()
        return {
            "analysis": analysis_depth,
            "maintenance": maintenance_depth,
        }
    except Exception:
        return {"analysis": -1, "maintenance": -1}


def _check_agent_imports() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    modules = [
        ("cfo_orchestrator", "app.agents.orchestrator"),
        ("risk_orchestrator", "app.agents.risk.orchestrator"),
        ("ceo_orchestrator", "app.agents.ceo.orchestrator"),
    ]
    for name, module_path in modules:
        try:
            __import__(module_path)
            checks[name] = True
        except Exception:
            checks[name] = False
    return {
        "ok": all(checks.values()),
        "modules": checks,
    }


def _safe_pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return int(values[0])
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1))))
    return int(ordered[k])


def _derive_actions(*, failed_count: int, awaiting_review_count: int, breaches: Iterable[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if failed_count > 0:
        actions.append("Inspect latest failed jobs and classify root cause before new deployments.")
    if awaiting_review_count > 0:
        actions.append("Clear awaiting_review queue to prevent decision latency for users.")
    if any(True for _ in breaches):
        actions.append("Escalate SLA breaches to on-call and prioritize queue drain.")
    if not actions:
        actions.append("System is stable; keep monitoring and run routine verification checks.")
    return actions[:3]


@router.get("/system/llm-costs")
async def llm_costs(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    LLM spend rollup from the LLMCallLog ledger over the last `days`:
    totals plus per-model, per-org and per-day breakdowns. Also returns the
    in-process gateway aggregate (resets on restart) for a live view.
    """
    from datetime import timedelta

    from sqlalchemy import String, cast
    from sqlalchemy import func as sa_func

    from app.models.llm_call_log import LLMCallLog
    from app.platform.model_gateway import ledger_snapshot

    since = datetime.now(UTC) - timedelta(days=days)
    day_key = sa_func.substr(cast(LLMCallLog.created_at, String), 1, 10)  # YYYY-MM-DD, portable

    async def _grouped(col) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(
                    col,
                    func.count().label("calls"),
                    func.coalesce(func.sum(LLMCallLog.cost_usd), 0.0).label("cost_usd"),
                    func.coalesce(func.sum(LLMCallLog.input_tokens), 0).label("in_tok"),
                    func.coalesce(func.sum(LLMCallLog.output_tokens), 0).label("out_tok"),
                )
                .where(LLMCallLog.created_at >= since)
                .group_by(col)
                .order_by(func.sum(LLMCallLog.cost_usd).desc())
            )
        ).all()
        return [
            {
                "key": r[0],
                "calls": int(r.calls),
                "cost_usd": round(float(r.cost_usd), 6),
                "input_tokens": int(r.in_tok),
                "output_tokens": int(r.out_tok),
            }
            for r in rows
        ]

    total = (
        await db.execute(
            select(
                func.count().label("calls"),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0.0).label("cost_usd"),
            ).where(LLMCallLog.created_at >= since)
        )
    ).first()

    ok_calls = await db.scalar(
        select(func.count()).where(
            LLMCallLog.created_at >= since, LLMCallLog.ok.is_(True)
        )
    )

    return {
        "data": {
            "window_days": days,
            "total_calls": int(total.calls if total else 0),
            "ok_calls": int(ok_calls or 0),
            "total_cost_usd": round(float(total.cost_usd if total else 0.0), 6),
            "by_model": await _grouped(LLMCallLog.model),
            "by_org": await _grouped(LLMCallLog.org_id),
            "by_task": await _grouped(LLMCallLog.task_type),
            "by_day": await _grouped(day_key),
            "live_process_aggregate": ledger_snapshot(),
        },
        "error": None,
    }


@router.get("/system/health")
async def system_health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()

    # DB check
    db_ok = True
    db_detail = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_detail = str(exc)

    redis_check = await _check_redis()
    agent_check = _check_agent_imports()

    overall_ok = db_ok and redis_check.get("ok", False) and agent_check.get("ok", False)
    status_label = "healthy" if overall_ok else "degraded"

    return {
        "data": {
            "status": status_label,
            "ok": overall_ok,
            "schema_version": OPS_SCHEMA_VERSION,
            "checked_at": now,
            "components": {
                "database": {"ok": db_ok, "detail": db_detail},
                "redis": redis_check,
                "agents": agent_check,
            },
        },
        "error": None,
    }


async def _management_summary(db: AsyncSession, org_id: str | None = None) -> dict[str, Any]:
    """Conflict + management layer summary for ops endpoint."""
    out: dict[str, Any] = {
        "conflicts_available": False,
        "open_conflicts": 0,
        "topics": [],
        "recent_conflicts": [],
        "suggested_topics": ["cash_risk", "revenue_outlook", "headcount", "tech_risk"],
    }
    if not org_id:
        return out
    try:
        rows = await db.execute(
            select(AgentConflict.topic, AgentConflict.status, func.count())
            .where(AgentConflict.org_id == org_id, AgentConflict.status == "open")
            .group_by(AgentConflict.topic, AgentConflict.status)
        )
        items = rows.all()
        out["conflicts_available"] = True
        out["open_conflicts"] = sum(int(r[2]) for r in items)
        out["topics"] = [{"topic": str(r[0]), "count": int(r[2])} for r in items]

        recent = await db.execute(
            select(
                AgentConflict.id,
                AgentConflict.topic,
                AgentConflict.status,
                AgentConflict.consensus_score,
                AgentConflict.resolution,
                AgentConflict.created_at,
            )
            .where(AgentConflict.org_id == org_id)
            .order_by(AgentConflict.created_at.desc())
            .limit(10)
        )
        recent_conflicts: list[dict[str, Any]] = []
        for row in recent.all():
            score = row[3]
            try:
                score_f = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_f = None
            severity = "low"
            if score_f is not None:
                if score_f < 0.35:
                    severity = "critical"
                elif score_f < 0.55:
                    severity = "high"
                elif score_f < 0.75:
                    severity = "medium"
            recent_conflicts.append(
                {
                    "id": row[0],
                    "topic": row[1],
                    "status": row[2],
                    "consensus_score": score_f,
                    "severity": severity,
                    "resolution": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                }
            )
        out["recent_conflicts"] = recent_conflicts
    except Exception:
        pass
    return out


@router.get("/system/ops")
async def system_ops(
    db: AsyncSession = Depends(get_db),
    org_id: str | None = Query(default=None, description="Optional org scope for management summary"),
) -> dict[str, Any]:
    # Job status counters
    status_rows = await db.execute(
        select(AnalysisJob.status, func.count(AnalysisJob.id)).group_by(AnalysisJob.status)
    )
    status_counts = {str(status): int(count) for status, count in status_rows.all()}
    total_jobs = sum(status_counts.values())
    failed_count = int(status_counts.get("failed", 0))

    awaiting_review_count = int(
        (
            await db.execute(
                select(func.count(AnalysisJob.id)).where(AnalysisJob.awaiting_review.is_(True))
            )
        ).scalar_one()
        or 0
    )

    failed_rows = await db.execute(
        select(
            AnalysisJob.id,
            AnalysisJob.status,
            AnalysisJob.error_message,
            AnalysisJob.updated_at,
        )
        .where(AnalysisJob.status == "failed")
        .order_by(AnalysisJob.updated_at.desc())
        .limit(10)
    )
    recent_failed_jobs = [
        {
            "job_id": row.id,
            "status": row.status,
            "error_message": row.error_message,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in failed_rows.all()
    ]

    # SLA breach: jobs stuck in pending/analyzing beyond threshold.
    breach_rows = await db.execute(
        select(
            AnalysisJob.id,
            AnalysisJob.status,
            AnalysisJob.updated_at,
        ).where(
            AnalysisJob.status.in_(("pending", "analyzing"))
        )
    )
    now = datetime.now(UTC)
    sla_breaches: list[dict[str, Any]] = []
    for row in breach_rows.all():
        updated_at = as_utc(row.updated_at)
        if not updated_at:
            continue
        age_minutes = int((now - updated_at).total_seconds() // 60)
        if age_minutes >= SLA_ANALYZING_BREACH_MINUTES:
            sla_breaches.append(
                {
                    "job_id": row.id,
                    "status": row.status,
                    "age_minutes": age_minutes,
                    "threshold_minutes": SLA_ANALYZING_BREACH_MINUTES,
                }
            )

    # Completion and first-result timing metrics (recent completed window)
    completed_rows = await db.execute(
        select(
            AnalysisJob.created_at,
            AnalysisJob.completed_at,
            AnalysisJob.result_metadata,
        )
        .where(AnalysisJob.status == "completed")
        .order_by(AnalysisJob.completed_at.desc())
        .limit(200)
    )
    completion_ms_samples: list[int] = []
    first_result_ms_samples: list[int] = []
    for row in completed_rows.all():
        created_at = as_utc(row.created_at)
        completed_at = as_utc(row.completed_at)
        if created_at and completed_at:
            completion_ms_samples.append(
                int((completed_at - created_at).total_seconds() * 1000)
            )
        meta = row.result_metadata or {}
        started_iso = meta.get("analysis_started_at") if isinstance(meta, dict) else None
        if started_iso and created_at:
            try:
                started_at = as_utc(datetime.fromisoformat(str(started_iso)))
                first_result_ms_samples.append(
                    int((started_at - created_at).total_seconds() * 1000)  # type: ignore[operator]
                )
            except Exception:
                pass

    job_completion_p95_ms = _percentile(completion_ms_samples, 95.0)
    time_to_first_result_p95_ms = _percentile(first_result_ms_samples, 95.0)

    # Sync summary is optional because table may not exist in every env.
    sync_summary: dict[str, Any] = {"available": False, "by_status": {}}
    try:
        status_col = func.coalesce(SyncRun.status, "unknown")
        sync_rows = await db.execute(
            select(status_col.label("status"), func.count().label("cnt")).group_by(status_col)
        )
        sync_summary = {
            "available": True,
            "by_status": {str(row.status): int(row.cnt) for row in sync_rows},
        }
    except Exception:
        pass

    queue_depths = await _queue_depths()
    failure_rate_pct = _safe_pct(failed_count, total_jobs)
    awaiting_review_ratio_pct = _safe_pct(awaiting_review_count, total_jobs)
    management = await _management_summary(db, org_id)
    suggested_actions = _derive_actions(
        failed_count=failed_count,
        awaiting_review_count=awaiting_review_count,
        breaches=sla_breaches,
    )

    llm_cost: dict[str, Any] = {
        "available": False,
        "calls": 0,
        "total_cost_usd": 0.0,
        "saved_usd": 0.0,
        "avg_cost_usd": 0.0,
        "cache_size": 0,
    }
    try:
        from app.services.llm_router import get_llm_router

        stats = get_llm_router().get_stats()
        llm_cost = {
            "available": True,
            "calls": int(stats.get("calls") or 0),
            "total_cost_usd": float(stats.get("total_cost_usd") or 0.0),
            "saved_usd": float(stats.get("saved_usd") or 0.0),
            "avg_cost_usd": float(stats.get("avg_cost_usd") or 0.0),
            "cache_size": int(stats.get("cache_size") or 0),
        }
    except Exception:
        pass

    # Model Gateway ledger — every LLM egress call (all task types), broken
    # down by model and by org. In-process aggregate; resets on restart.
    try:
        from app.platform.model_gateway import ledger_snapshot

        gw = ledger_snapshot()
        llm_cost["gateway"] = {
            "calls": gw["calls"],
            "ok_calls": gw["ok_calls"],
            "total_cost_usd": gw["total_cost_usd"],
            "avg_cost_usd": gw["avg_cost_usd"],
            "total_input_tokens": gw["total_input_tokens"],
            "total_output_tokens": gw["total_output_tokens"],
            "by_model": gw["by_model"],
            "by_org": ({org_id: gw["by_org"].get(org_id, {})} if org_id else gw["by_org"]),
        }
        llm_cost["available"] = True
    except Exception:
        pass

    stripe_health: dict[str, Any] = {"configured": False, "ok": False}
    try:
        from app.config import get_settings

        settings = get_settings()
        key = getattr(settings, "stripe_secret_key", "") or ""
        stripe_health = {
            "configured": bool(key) and not str(key).startswith("sk_test_placeholder"),
            "ok": bool(key),
            "webhook_secret_set": bool(getattr(settings, "stripe_webhook_secret", "") or ""),
        }
    except Exception:
        pass

    regional: dict[str, Any] = {"packs": [], "country_code": None, "base_currency": None}
    if org_id:
        try:
            from app.models.organization import Organization
            from app.services.regional.packs import normalize_packs

            org = await db.get(Organization, org_id)
            if org:
                regional = {
                    "packs": normalize_packs(getattr(org, "regional_packs", None)),
                    "country_code": getattr(org, "country_code", None),
                    "base_currency": getattr(org, "base_currency", None),
                    "locale": getattr(org, "locale", None),
                }
        except Exception:
            pass

    return {
        "data": {
            "schema_version": OPS_SCHEMA_VERSION,
            "jobs": {
                "status_counts": status_counts,
                "awaiting_review": awaiting_review_count,
                "total": total_jobs,
                "failure_rate_pct": failure_rate_pct,
                "awaiting_review_ratio_pct": awaiting_review_ratio_pct,
                "recent_failed": recent_failed_jobs,
            },
            "sync": sync_summary,
            "sla": {
                "queue_depth": max(0, queue_depths.get("analysis", -1)),
                "queue_depths": queue_depths,
                "job_completion_p95_ms": job_completion_p95_ms,
                "time_to_first_result_p95_ms": time_to_first_result_p95_ms,
                "error_rate_pct": failure_rate_pct,
                "breaches": sla_breaches,
            },
            "llm_cost": llm_cost,
            "stripe": stripe_health,
            "regional": regional,
            "error_budget": ERROR_BUDGETS,
            "management": management,
            "suggested_actions": suggested_actions,
            "generated_at": now.isoformat(),
        },
        "error": None,
    }

