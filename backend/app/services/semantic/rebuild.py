"""Rebuild CompanySemanticSnapshot from CompanyContext + canonical transactions."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.semantic.brief import build_from_snapshot, enrich_brief_from_ceo_synthesis
from app.services.semantic.conflicts import (
    detect_metric_conflicts,
    load_open_conflicts,
    persist_metric_conflicts,
)
from app.services.semantic.projectors import (
    merge_metrics,
    project_from_canonical_rows,
    project_from_cfo,
    project_from_chro,
    project_from_cmo,
    project_from_coo,
    project_from_cto,
    project_from_kernel,
    project_from_risk,
)
from app.services.semantic.store import (
    period_date_bounds,
    resolve_period_key,
    save_semantic_snapshot,
)
from app.services.semantic.types import CompanySemanticSnapshot, DriverLink, EvidenceRef

logger = logging.getLogger(__name__)

DEFAULT_DRIVERS = [
    DriverLink("finance.revenue", "finance.runway_months", "influences", 0.4),
    DriverLink("growth.blended_cac", "finance.operating_cashflow", "influences", 0.3),
    DriverLink("people.headcount", "finance.operating_cashflow", "influences", 0.5),
    DriverLink("tech.debt_score", "tech.health_score", "composed_of", 0.6),
]


async def _org_locale_currency(org_id: str, db: AsyncSession | None) -> tuple[str, str]:
    currency, locale = "USD", "en-US"
    if not db:
        return currency, locale
    try:
        from app.models.organization import Organization

        org = await db.get(Organization, str(org_id))
        if org:
            currency = getattr(org, "base_currency", None) or currency
            locale = getattr(org, "locale", None) or locale
    except Exception as exc:
        logger.debug("org locale load failed: %s", exc)
    return currency, locale


async def _load_canonical(
    org_id: str,
    db: AsyncSession | None,
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[list[Any], float | None]:
    if not db:
        return [], None
    try:
        from app.models.canonical_transaction import CanonicalTransaction

        stmt = select(CanonicalTransaction).where(
            CanonicalTransaction.org_id == str(org_id)
        )
        if period_start is not None:
            stmt = stmt.where(CanonicalTransaction.transaction_date >= period_start)
        if period_end is not None:
            stmt = stmt.where(CanonicalTransaction.transaction_date <= period_end)
        stmt = stmt.limit(5000)

        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        quality = None
        confs = [r.confidence for r in rows if r.confidence is not None]
        if confs:
            quality = (
                sum(confs) / (100.0 * len(confs)) if max(confs) > 1 else sum(confs) / len(confs)
            )
        elif rows:
            quality = 0.8
        return rows, quality
    except Exception as exc:
        logger.debug("canonical load failed: %s", exc)
        return [], None


async def _latest_sync_quality(org_id: str, db: AsyncSession | None) -> float | None:
    if not db:
        return None
    try:
        from app.models.sync_run import SyncRun

        result = await db.execute(
            select(SyncRun.quality_score)
            .where(
                SyncRun.org_id == str(org_id),
                SyncRun.status == "success",
            )
            .order_by(SyncRun.completed_at.desc())
            .limit(1)
        )
        score = result.scalar_one_or_none()
        return float(score) if score is not None else None
    except Exception as exc:
        logger.debug("latest sync quality load failed: %s", exc)
        return None


async def rebuild_semantic_snapshot(
    org_id: str,
    db: AsyncSession | None = None,
    *,
    include_brief: bool = True,
    conflicts: list[dict[str, Any]] | None = None,
    strict: bool = False,
) -> CompanySemanticSnapshot | None:
    """
    Reproject metrics from CompanyContext + canonical txs, build DecisionBrief, persist.

    Default is non-fatal (returns None on hard failure). Pass strict=True in
    tests / explicit rebuild APIs that must not swallow errors.
    """
    try:
        from app.services.company_context import get_company_context, save_company_context

        ctx = await get_company_context(org_id, db)
        currency, locale = await _org_locale_currency(org_id, db)
        period = resolve_period_key(ctx.reporting_period)
        p_start, p_end = period_date_bounds(period)

        if conflicts is None:
            conflicts = await load_open_conflicts(org_id, db)

        cfo_job = ctx.active_cfo_job_id
        metrics = merge_metrics(
            project_from_cfo(ctx.last_cfo_result, currency=currency, job_id=cfo_job),
            project_from_cmo(ctx.last_cmo_result, currency=currency, job_id=ctx.active_cmo_job_id),
            project_from_cto(ctx.last_cto_result, job_id=ctx.active_cto_job_id),
            project_from_chro(ctx.last_chro_result, job_id=ctx.active_chro_job_id),
            project_from_coo(ctx.last_coo_result, job_id=ctx.active_coo_job_id),
            project_from_risk(ctx.last_risk_result),
        )

        # Kernel overlays (optional)
        try:
            from app.services.company_context import get_cached_kernel_result

            for agent in ("cto", "cmo", "chro", "coo"):
                k = await get_cached_kernel_result(org_id, agent)
                if k:
                    metrics = merge_metrics(metrics, project_from_kernel(k, agent=agent))
        except Exception:
            pass

        rows, quality = await _load_canonical(
            org_id, db, period_start=p_start, period_end=p_end
        )
        sync_quality = await _latest_sync_quality(org_id, db)
        if sync_quality is not None:
            quality = sync_quality if quality is None else max(quality, sync_quality)
        metrics = merge_metrics(
            metrics,
            project_from_canonical_rows(rows, currency=currency, quality_score=quality),
        )

        metric_conflicts = detect_metric_conflicts(metrics)
        if metric_conflicts and db is not None:
            await persist_metric_conflicts(org_id, metric_conflicts, db)
        merged_conflicts: list[dict[str, Any]] = list(conflicts or [])
        seen_keys = {
            (
                str(c.get("topic") or ""),
                str(c.get("agent_a") or c.get("agent_a") or ""),
                str(c.get("agent_b") or c.get("agent_b") or ""),
            )
            for c in merged_conflicts
        }
        for extra in metric_conflicts:
            key = (
                str(extra.get("topic") or ""),
                str(extra.get("agent_a") or extra.get("agent_a") or ""),
                str(extra.get("agent_b") or extra.get("agent_b") or ""),
            )
            if key in seen_keys:
                continue
            merged_conflicts.append(extra)
            seen_keys.add(key)
        conflicts = merged_conflicts

        job_ids = [
            j
            for j in (
                ctx.active_cfo_job_id,
                ctx.active_cto_job_id,
                ctx.active_cmo_job_id,
                ctx.active_coo_job_id,
                ctx.active_chro_job_id,
            )
            if j
        ]

        evidence = [
            EvidenceRef(source_type="company_context", source_id=org_id, preview="rebuild"),
        ]
        if rows:
            evidence.append(
                EvidenceRef(
                    source_type="canonical_transactions",
                    preview=f"count={len(rows)}",
                )
            )

        snapshot = CompanySemanticSnapshot(
            org_id=str(org_id),
            period=period,
            currency=currency,
            locale=locale,
            metrics=metrics,
            drivers=list(DEFAULT_DRIVERS),
            evidence=evidence,
            source_job_ids=job_ids,
        )
        if p_start:
            snapshot.period.start = p_start.date().isoformat()
        if p_end:
            snapshot.period.end = p_end.date().isoformat()

        if include_brief:
            brief = build_from_snapshot(snapshot, conflicts=conflicts)
            brief = enrich_brief_from_ceo_synthesis(brief, ctx.last_ceo_result)
            snapshot.brief = brief

        await save_semantic_snapshot(snapshot, db)

        # Mirror brief onto last_ceo_result for FE compat
        if include_brief and snapshot.brief and db is not None:
            try:
                ceo = dict(ctx.last_ceo_result or {})
                ceo["decision_brief"] = snapshot.brief.to_dict()
                ctx.last_ceo_result = ceo
                await save_company_context(ctx, db)
            except Exception as exc:
                logger.debug("mirror decision_brief failed: %s", exc)

        # Index semantic snapshot for RAG (non-fatal).
        #
        # `index_job_text` deletes and re-inserts chunk rows and deliberately
        # does not commit — "caller manages the transaction boundary". This is
        # that caller, and it never did: every rebuild left an open write
        # transaction behind. On SQLite that holds a RESERVED lock on the whole
        # file, so a rebuild running on a session that outlives the request
        # (the trailing rebuild task, auto-chain) wedged the instance: every
        # later INSERT anywhere failed with "database is locked" until restart.
        try:
            await index_semantic_for_rag(org_id, snapshot, db)
            if db is not None:
                await db.commit()
        except Exception as exc:
            if db is not None:
                await db.rollback()
            logger.debug("semantic RAG index skipped: %s", exc)

        logger.info(
            "Semantic snapshot rebuilt org=%s period=%s metrics=%d brief=%s",
            org_id,
            period.key,
            len(metrics),
            bool(snapshot.brief),
        )
        return snapshot
    except Exception as exc:
        logger.warning("rebuild_semantic_snapshot failed org=%s: %s", org_id, exc)
        if strict:
            raise
        return None


async def index_semantic_for_rag(
    org_id: str,
    snapshot: CompanySemanticSnapshot,
    db: AsyncSession | None,
) -> None:
    if not db or not snapshot.metrics:
        return
    from app.services.rag_service import index_job_text

    lines = [
        f"Semantic snapshot period={snapshot.period.key} currency={snapshot.currency}",
    ]
    for m in snapshot.metrics:
        lines.append(f"{m.metric_id}={m.value} unit={m.unit} conf={m.confidence:.2f}")
    job_id = snapshot.source_job_ids[0] if snapshot.source_job_ids else f"semantic:{org_id}"
    await index_job_text(
        db,
        org_id=str(org_id),
        job_id=str(job_id),
        source_type="semantic_snapshot",
        raw_text="\n".join(lines)[:40_000],
    )
