"""The radar's forecast log (Plan v10 O5 foundation).

Every day the radar is written down as it stands. Four weeks later its week-4 end
balance can be set against the balance the bank statement proved, and that is the
forecast error O5 grades. Grading itself is not here; this module only makes sure the
forecast exists, unaltered, when the grading needs it.

One rule carries the weight: a radar anchored on a past day is hindsight (it already
knows what happened since) and is never written as a forecast.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_radar_snapshot import CashRadarSnapshot
from app.services.cash_radar import CashRadar, compute_cash_radar

logger = logging.getLogger(__name__)


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def knows_something(radar: CashRadar) -> bool:
    """A radar with no balance and no open items forecasts nothing worth keeping."""
    return (
        radar.starting_cash_cents is not None
        or any(w.receivables or w.payables for w in radar.weeks)
        or bool(radar.overdue_receivables)
        or radar.overdue_payables_cents > 0
        or radar.undated_receivables_cents > 0
        or radar.undated_payables_cents > 0
    )


async def record_forecast(
    db: AsyncSession, org_id: str, radar: CashRadar, *, today: date
) -> CashRadarSnapshot | None:
    """Write the radar once; an identical one is not written twice.

    Returns None for a radar not anchored on `today`: that is hindsight, not a forecast.
    """
    anchor = date.fromisoformat(radar.anchor_date)
    if anchor != today:
        return None
    payload = radar.to_dict()
    digest = _content_hash(payload)
    query = select(CashRadarSnapshot).where(
        CashRadarSnapshot.org_id == org_id,
        CashRadarSnapshot.anchor_date == anchor,
        CashRadarSnapshot.snapshot_hash == digest,
    )
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is not None:
        return existing
    snap = CashRadarSnapshot(
        org_id=org_id, anchor_date=anchor, snapshot_hash=digest, snapshot_json=payload
    )
    try:
        async with db.begin_nested():
            db.add(snap)
            await db.flush()
    except IntegrityError:
        # Two identical requests raced on the content key; the other one wrote it.
        existing = (await db.execute(query)).scalar_one_or_none()
        if existing is None:
            raise
        return existing
    return snap


@dataclass(frozen=True)
class Forecast:
    anchor_date: str
    made_at: str
    end_balance_cents: int


async def forecast_for_target(
    db: AsyncSession, org_id: str, *, target: date, weeks: int
) -> Forecast | None:
    """The forecast made `weeks` weeks before `target` for the balance at its end.

    Week N of a radar anchored on A ends on A + 7N - 1, so the forecast for `target`
    is the radar anchored on target - (7N - 1). The last one written that day wins:
    it is what the owner saw last.
    """
    if not 1 <= weeks <= 13:
        raise ValueError("weeks must be between 1 and 13")
    anchor = target - timedelta(days=7 * weeks - 1)
    snap = (
        await db.execute(
            select(CashRadarSnapshot)
            .where(CashRadarSnapshot.org_id == org_id, CashRadarSnapshot.anchor_date == anchor)
            .order_by(CashRadarSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if snap is None:
        return None
    radar_weeks = snap.snapshot_json.get("weeks") or []
    if len(radar_weeks) < weeks:
        return None
    week = radar_weeks[weeks - 1]
    if week.get("end_date") != target.isoformat():
        return None
    return Forecast(
        anchor_date=anchor.isoformat(),
        made_at=snap.created_at.isoformat(),
        end_balance_cents=int(week["end_balance_cents"]),
    )


async def record_daily_forecasts(db: AsyncSession, *, today: date) -> int:
    """Write today's forecast for every organisation the radar knows something about."""
    from app.models.organization import Organization

    org_ids = (await db.execute(select(Organization.id))).scalars().all()
    written = 0
    for org_id in org_ids:
        try:
            radar = await compute_cash_radar(db, org_id, anchor_date=today)
            if not knows_something(radar):
                continue
            if await record_forecast(db, org_id, radar, today=today) is not None:
                written += 1
        except Exception:
            # One company's broken data must not stop the others' forecasts; it is logged.
            logger.exception("radar forecast log failed for org %s", org_id)
    return written
