"""Data freshness — the "as of" behind every number, from source columns.

Split out of `decision_packet` so three consumers read ONE definition:

  1. decision packet strip  → `collect_freshness(db, job)`
  2. org-level endpoint     → `org_overview_freshness(db, org_id)`
  3. OKR confidence input   → `org_age_summary(db, org_id)`

Every value comes from a column the source itself maintains — nothing is
estimated, because a freshness signal that guesses is worse than none: it
manufactures trust. Timestamps are UTC; SQLite hands datetimes back naive,
so `_as_utc` normalises before any age maths.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob

# Freshness verdicts for the strip. A decision made on a 45-day-old sync
# is a different decision than one made on yesterday's — the manager must
# see which.
FRESH_WITHIN_DAYS = 7
AGING_WITHIN_DAYS = 30

# A source older than this drops the org-level quality to "low" (the old
# OKR agent hard-coded 14 as its high/low cut — same threshold, one place).
OKR_QUALITY_MAX_DAYS = 14


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite round-trip drops tzinfo
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _age_days(as_of: datetime | None) -> int | None:
    norm = _as_utc(as_of)
    if norm is None:
        return None
    delta = datetime.now(UTC) - norm
    return max(0, delta.days)


def _state(as_of: datetime | None, *, never_label: str = "never") -> str:
    """fresh | aging | stale | never | unknown — the chip the UI colours."""
    if as_of is None:
        return never_label
    age = _age_days(as_of)
    if age is None:
        return "unknown"
    if age <= FRESH_WITHIN_DAYS:
        return "fresh"
    if age <= AGING_WITHIN_DAYS:
        return "aging"
    return "stale"


def _item(
    source: str,
    label: str,
    as_of: datetime | None,
    detail: str | None = None,
) -> dict[str, Any]:
    norm = _as_utc(as_of)
    return {
        "source": source,
        "label": label,
        "as_of": norm.isoformat() if norm else None,
        "age_days": _age_days(as_of),
        "state": _state(as_of),
        "detail": detail,
    }


async def job_freshness(db: AsyncSession, job: AnalysisJob) -> list[dict[str, Any]]:
    """The job's own inputs: when the file arrived + what date range it held."""
    from app.models.transaction import Transaction

    items: list[dict[str, Any]] = []

    # 1. The uploaded file itself — when these numbers were born.
    items.append(
        _item(
            "analysis_file",
            "Analiz dosyası",
            _as_utc(job.created_at),
            detail=job.filename,
        )
    )

    # 2. Business-date coverage of what the analysis actually ingested.
    cov = (
        await db.execute(
            select(
                func.max(Transaction.transaction_date),
                func.count(Transaction.id),
            ).where(Transaction.job_id == job.id)
        )
    ).one()
    max_date, tx_count = cov
    items.append(
        _item(
            "coverage",
            "Analizin veri kapsamı",
            max_date,
            detail=(
                f"{tx_count} işlem"
                + (f", en yeni {max_date.date().isoformat()}" if max_date else "")
            ),
        )
    )
    return items


async def org_freshness(db: AsyncSession, org_id: str | None) -> list[dict[str, Any]]:
    """Org-wide sources: connector syncs, ERP integrations, scheduled runs."""
    from app.models.connector_connection import ConnectorConnection
    from app.models.erp_integration import ERPIntegration, ERPSyncLog
    from app.models.sync_run import SyncRun

    if not org_id:
        return []

    items: list[dict[str, Any]] = []

    # 3. Connector syncs (org-wide) — one chip per connected source.
    conns = (
        await db.execute(
            select(ConnectorConnection)
            .where(ConnectorConnection.org_id == org_id)
            .order_by(ConnectorConnection.connector)
        )
    ).scalars().all()
    for c in conns:
        items.append(
            _item(
                f"connector:{c.connector}",
                f"Bağlantı: {c.display_name or c.connector}",
                _as_utc(c.last_sync_at),
                detail=c.last_status,
            )
        )

    # 4. ERP integrations — provider sync timestamps (Pararaşüt/Logo/...).
    erps = (
        await db.execute(
            select(ERPIntegration).where(ERPIntegration.org_id == org_id)
        )
    ).scalars().all()
    for e in erps:
        items.append(
            _item(
                f"erp:{e.provider}",
                f"ERP: {e.provider}",
                _as_utc(e.last_sync_at),
                detail=e.last_sync_status,
            )
        )
    if not erps:
        # Fall back to the ERP sync log when the integration row was pruned.
        log = (
            await db.execute(
                select(ERPSyncLog)
                .where(ERPSyncLog.org_id == org_id)
                .order_by(desc(ERPSyncLog.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if log is not None:
            items.append(
                _item("erp:log", "ERP senkron kaydı", _as_utc(log.started_at),
                      detail=log.status)
            )

    # 5. Scheduled sync runs (DQ pipelines) — the most recent one.
    run = (
        await db.execute(
            select(SyncRun)
            .where(SyncRun.org_id == org_id)
            .order_by(desc(SyncRun.started_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is not None:
        items.append(
            _item("sync_run", "Planlı senkron (son çalıştırma)",
                  _as_utc(run.started_at), detail=run.status)
        )

    return items


async def collect_freshness(db: AsyncSession, job: AnalysisJob) -> list[dict[str, Any]]:
    """Real as-of per source feeding this decision (job inputs + org sources)."""
    items = await job_freshness(db, job)
    if job.org_id:
        items += await org_freshness(db, job.org_id)
    return items


async def org_overview_freshness(
    db: AsyncSession, org_id: str | None
) -> list[dict[str, Any]]:
    """Org-level strip: latest job's file + coverage, then the org sources."""
    if not org_id:
        return []
    job = (
        await db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.org_id == org_id)
            .order_by(desc(AnalysisJob.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    items: list[dict[str, Any]] = []
    if job is not None:
        items += await job_freshness(db, job)
    items += await org_freshness(db, org_id)
    return items


def age_from_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """One measured age for a freshness strip — the OKR confidence input.

    `days` = the WORST (oldest) age among dated sources: one 45-day-stale
    connector means part of the picture is 45 days old. `quality`:
      high    = every source within OKR_QUALITY_MAX_DAYS and no gaps
      low     = something old, or a source that never synced
      unknown = no sources at all (nothing to be fresh *about*)
    """
    ages = [i["age_days"] for i in items if i["age_days"] is not None]
    has_gap = any(i["age_days"] is None for i in items)
    days = max(ages) if ages else None
    if days is None:
        quality = "unknown"
    elif has_gap or days > OKR_QUALITY_MAX_DAYS:
        quality = "low"
    else:
        quality = "high"
    return {"days": days, "quality": quality, "sources": len(items)}


async def org_age_summary(db: AsyncSession, org_id: str | None) -> dict[str, Any]:
    """Org-wide age summary (see `age_from_items` for the semantics)."""
    return age_from_items(await org_overview_freshness(db, org_id))
