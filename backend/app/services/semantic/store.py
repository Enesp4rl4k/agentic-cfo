"""Persistence for CompanySemanticSnapshot (DB + Redis mirror)."""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.services.semantic.types import CompanySemanticSnapshot, DecisionBrief, Period

logger = logging.getLogger(__name__)

REDIS_TTL = 1800


def _redis_key(org_id: str, period_key: str) -> str:
    return f"semantic:{org_id}:{period_key}"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        return json.loads(raw) if raw else None
    return raw


async def _get_redis() -> Any | None:
    try:
        from app.services.company_context import _get_redis as ctx_redis

        return await ctx_redis()
    except Exception:
        return None


def row_to_snapshot(row: CompanySemanticSnapshotRow) -> CompanySemanticSnapshot:
    metrics = _loads(row.metrics_json) or []
    drivers = _loads(row.drivers_json) or []
    evidence = _loads(row.evidence_json) or []
    brief_raw = _loads(row.brief_json)
    job_ids = _loads(row.source_job_ids) or []
    return CompanySemanticSnapshot.from_dict(
        {
            "org_id": row.org_id,
            "period": {
                "key": row.period_key,
                "start": row.period_start,
                "end": row.period_end,
                "grain": "month",
            },
            "currency": row.currency,
            "locale": row.locale,
            "metrics": metrics,
            "drivers": drivers,
            "evidence": evidence,
            "brief": brief_raw,
            "source_job_ids": job_ids,
            "schema_version": row.schema_version,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    )


async def get_semantic_snapshot(
    org_id: str,
    period_key: str,
    db: AsyncSession | None = None,
) -> CompanySemanticSnapshot | None:
    redis = await _get_redis()
    if redis is not None:
        try:
            cached = await redis.get(_redis_key(org_id, period_key))
            if cached:
                return CompanySemanticSnapshot.from_dict(json.loads(cached))
        except Exception as exc:
            logger.debug("semantic redis get failed: %s", exc)

    if db is None:
        return None

    result = await db.execute(
        select(CompanySemanticSnapshotRow).where(
            CompanySemanticSnapshotRow.org_id == org_id,
            CompanySemanticSnapshotRow.period_key == period_key,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    snap = row_to_snapshot(row)
    if redis is not None:
        try:
            await redis.setex(_redis_key(org_id, period_key), REDIS_TTL, _dumps(snap.to_dict()))
        except Exception:
            pass
    return snap


async def approve_semantic_brief(
    org_id: str,
    period_key: str,
    db: AsyncSession,
) -> CompanySemanticSnapshot | None:
    """Human approval — clear awaiting_review on the stored DecisionBrief."""
    snap = await get_semantic_snapshot(org_id, period_key, db)
    if snap is None or snap.brief is None:
        return None
    if not snap.brief.awaiting_review:
        return snap
    snap.brief.awaiting_review = False
    return await save_semantic_snapshot(snap, db)


async def get_latest_semantic_snapshot(
    org_id: str,
    db: AsyncSession | None = None,
) -> CompanySemanticSnapshot | None:
    if db is None:
        return None
    result = await db.execute(
        select(CompanySemanticSnapshotRow)
        .where(CompanySemanticSnapshotRow.org_id == org_id)
        .order_by(CompanySemanticSnapshotRow.updated_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    return row_to_snapshot(row)


async def list_semantic_snapshots(
    org_id: str,
    db: AsyncSession | None = None,
    *,
    limit: int = 12,
) -> list[CompanySemanticSnapshot]:
    """Recent period snapshots for org (newest first)."""
    if db is None:
        return []
    limit = max(1, min(limit, 24))
    result = await db.execute(
        select(CompanySemanticSnapshotRow)
        .where(CompanySemanticSnapshotRow.org_id == org_id)
        .order_by(CompanySemanticSnapshotRow.updated_at.desc())
        .limit(limit)
    )
    return [row_to_snapshot(row) for row in result.scalars().all()]


async def save_semantic_snapshot(
    snapshot: CompanySemanticSnapshot,
    db: AsyncSession | None = None,
) -> CompanySemanticSnapshot:
    snapshot.updated_at = datetime.now(UTC).isoformat()
    period_key = snapshot.period.key

    if db is not None:
        result = await db.execute(
            select(CompanySemanticSnapshotRow).where(
                CompanySemanticSnapshotRow.org_id == snapshot.org_id,
                CompanySemanticSnapshotRow.period_key == period_key,
            )
        )
        row = result.scalar_one_or_none()
        payload_metrics = [m.to_dict() for m in snapshot.metrics]
        payload_drivers = [d.to_dict() for d in snapshot.drivers]
        payload_evidence = [e.to_dict() for e in snapshot.evidence]
        brief_payload = snapshot.brief.to_dict() if snapshot.brief else None

        if row is None:
            row = CompanySemanticSnapshotRow(
                org_id=snapshot.org_id,
                period_key=period_key,
                period_start=snapshot.period.start,
                period_end=snapshot.period.end,
                currency=snapshot.currency,
                locale=snapshot.locale,
                schema_version=snapshot.schema_version,
                metrics_json=_dumps(payload_metrics),
                drivers_json=_dumps(payload_drivers),
                evidence_json=_dumps(payload_evidence),
                brief_json=_dumps(brief_payload) if brief_payload else None,
                source_job_ids=_dumps(snapshot.source_job_ids),
            )
            db.add(row)
        else:
            row.period_start = snapshot.period.start
            row.period_end = snapshot.period.end
            row.currency = snapshot.currency
            row.locale = snapshot.locale
            row.schema_version = snapshot.schema_version
            row.metrics_json = _dumps(payload_metrics)
            row.drivers_json = _dumps(payload_drivers)
            row.evidence_json = _dumps(payload_evidence)
            row.brief_json = _dumps(brief_payload) if brief_payload else None
            row.source_job_ids = _dumps(snapshot.source_job_ids)
            row.updated_at = datetime.now(UTC)
        await db.commit()

    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.setex(
                _redis_key(snapshot.org_id, period_key),
                REDIS_TTL,
                _dumps(snapshot.to_dict()),
            )
        except Exception as exc:
            logger.debug("semantic redis set failed: %s", exc)

    return snapshot


def resolve_period_key(reporting_period: str | None) -> Period:
    """Prefer explicit reporting_period; else current YYYY-MM."""
    if reporting_period and str(reporting_period).strip():
        key = str(reporting_period).strip()[:64]
        grain = "month"
        if re.match(r"^\d{4}-Q[1-4]$", key, re.I):
            grain = "quarter"
        elif re.match(r"^\d{4}$", key):
            grain = "year"
        return Period(key=key, grain=grain)
    now = datetime.now(UTC)
    key = f"{now.year:04d}-{now.month:02d}"
    return Period(key=key, grain="month")


def period_date_bounds(period: Period) -> tuple[datetime | None, datetime | None]:
    """Map period.key to UTC inclusive start/end for canonical tx filtering."""
    key = (period.key or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})$", key)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return None, None
        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
        else:
            end = datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
        return start, end

    m = re.match(r"^(\d{4})-Q([1-4])$", key, re.I)
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        start_month = (quarter - 1) * 3 + 1
        start = datetime(year, start_month, 1, tzinfo=UTC)
        end_month = start_month + 3
        if end_month > 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
        else:
            end = datetime(year, end_month, 1, tzinfo=UTC) - timedelta(microseconds=1)
        return start, end

    m = re.match(r"^(\d{4})$", key)
    if m:
        year = int(m.group(1))
        start = datetime(year, 1, 1, tzinfo=UTC)
        end = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
        return start, end

    return None, None


# Re-export helpers used by rebuild
__all__ = [
    "CompanySemanticSnapshot",
    "DecisionBrief",
    "Period",
    "get_latest_semantic_snapshot",
    "get_semantic_snapshot",
    "list_semantic_snapshots",
    "period_date_bounds",
    "resolve_period_key",
    "save_semantic_snapshot",
]
