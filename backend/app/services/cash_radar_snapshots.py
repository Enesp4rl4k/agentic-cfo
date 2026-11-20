"""Persistence and lookup for immutable cash radar forecast snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_radar_snapshot import CashRadarSnapshot
from app.services.cash_radar import CashRadar


def _snapshot_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_cash_radar_snapshot(
    db: AsyncSession,
    org_id: str,
    radar: CashRadar,
) -> CashRadarSnapshot:
    """Store a radar result once for identical inputs; changed forecasts append."""
    payload = radar.to_dict()
    snapshot_hash = _snapshot_hash(payload)
    query = select(CashRadarSnapshot).where(
        CashRadarSnapshot.org_id == org_id,
        CashRadarSnapshot.anchor_date == date.fromisoformat(radar.anchor_date),
        CashRadarSnapshot.snapshot_hash == snapshot_hash,
    )
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is not None:
        return existing

    snapshot = CashRadarSnapshot(
        org_id=org_id,
        anchor_date=date.fromisoformat(radar.anchor_date),
        snapshot_hash=snapshot_hash,
        snapshot_json=payload,
    )
    try:
        async with db.begin_nested():
            db.add(snapshot)
            await db.flush()
    except IntegrityError:
        # Concurrent identical radar requests race on the content uniqueness key.
        existing = (await db.execute(query)).scalar_one_or_none()
        if existing is None:
            raise
        return existing
    return snapshot


async def find_radar_snapshot_for_target(
    db: AsyncSession,
    org_id: str,
    *,
    target_date: date,
    lookback_weeks: int,
) -> tuple[CashRadarSnapshot | None, int | None]:
    """Find the saved forecast ending exactly on target_date."""
    if not 1 <= lookback_weeks <= 13:
        raise ValueError("lookback_weeks must be between 1 and 13")

    # Week N ends anchor + (7*N - 1) days in the radar's documented contract.
    anchor_date = date.fromordinal(target_date.toordinal() - (7 * lookback_weeks - 1))
    result = await db.execute(
        select(CashRadarSnapshot)
        .where(
            CashRadarSnapshot.org_id == org_id,
            CashRadarSnapshot.anchor_date == anchor_date,
        )
        .order_by(CashRadarSnapshot.created_at.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return None, None

    weeks = snapshot.snapshot_json.get("weeks") or []
    if len(weeks) < lookback_weeks:
        return snapshot, None
    week = weeks[lookback_weeks - 1]
    if week.get("end_date") != target_date.isoformat():
        return snapshot, None
    return snapshot, int(week["end_balance_cents"])
