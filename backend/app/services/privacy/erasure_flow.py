"""The life of an erasure request: pending -> scheduled (cooling-off) -> executed | cancelled | expired | blocked.

`pending`    a person asked; nothing is touched; the owner has `REQUEST_TTL` to confirm.
`scheduled`  confirmed; the destructive step waits until `execute_after` (ERASURE_COOLING_OFF_DAYS, default 7) and
             anyone with the right to cancel can still stop it.
`executed`   the erasure ran; only hashes remain on the request.
`cancelled`  stopped during the cooling-off window.
`blocked`    the window passed but the erasure may not run (a sole owner); `blocked_reason` is a fixed code.

The executor (`execute_due`, run by the scheduler) acts on exactly the request rows it loads: the organisation or
person it erases is the one named on the request, never a value computed elsewhere, so it cannot touch another
tenant. Running it twice does nothing the second time (the status moved on).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.erasure_record import OrgErasureRequest
from app.services.decisions import record_decision
from app.services.org_erasure import erase_org, hash_id

logger = logging.getLogger(__name__)

REQUEST_TTL = timedelta(days=7)
PENDING, SCHEDULED, EXECUTED, CANCELLED, EXPIRED, BLOCKED = (
    "pending", "scheduled", "executed", "cancelled", "expired", "blocked")


def cooling_off(initiated_by: str) -> timedelta:
    """The window; an operator-initiated erasure always waits at least a day, even when the setting is 0."""
    from app.config import get_settings

    days = max(int(get_settings().erasure_cooling_off_days), 0)
    return timedelta(days=max(days, 1) if initiated_by == "operator" else days)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def schedule(
    db: AsyncSession, req: OrgErasureRequest, *, confirmed_by_hash: str, decided_by: str | None, role: str,
    now: datetime | None = None,
) -> bool:
    """Confirm a request: returns True when it must run NOW (no cooling-off), False when it is scheduled.

    Writes the decision record (organisation scope) in the caller's transaction; the caller commits.
    """
    now = now or datetime.now(UTC)
    window = cooling_off(req.initiated_by)
    req.confirmed_by_hash, req.confirmed_at = confirmed_by_hash, now
    immediate = window == timedelta(0)
    if not immediate:
        req.status, req.execute_after = SCHEDULED, now + window
    if req.scope == "org" and req.target_org_id:
        await record_decision(
            db, org_id=str(req.target_org_id), kind=DecisionKind.ERASURE, target_type="org_erasure_request",
            target_id=req.id, outcome="executed" if immediate else "scheduled",
            decided_via=DecidedVia.HUMAN if decided_by else DecidedVia.SYSTEM, decided_by=decided_by,
            after={"mode": req.mode, "initiated_by": req.initiated_by, "acting_role": role,
                   "execute_after": req.execute_after.isoformat() if req.execute_after else None},
        )
    return immediate


async def cancel(db: AsyncSession, req: OrgErasureRequest, *, by_hash: str, decided_by: str | None, role: str) -> None:
    """Stop a pending or scheduled request. Raises ValueError when it already ran or ended."""
    if req.status not in (PENDING, SCHEDULED):
        raise ValueError(req.status)
    req.status, req.cancelled_at, req.cancelled_by_hash = CANCELLED, datetime.now(UTC), by_hash
    if req.scope == "org" and req.target_org_id:
        await record_decision(
            db, org_id=str(req.target_org_id), kind=DecisionKind.ERASURE, target_type="org_erasure_request",
            target_id=req.id, outcome="cancelled",
            decided_via=DecidedVia.HUMAN if decided_by else DecidedVia.SYSTEM, decided_by=decided_by,
            after={"mode": req.mode, "initiated_by": req.initiated_by, "acting_role": role},
        )


async def run_request(db: AsyncSession, req: OrgErasureRequest) -> dict[str, Any]:
    """Execute one confirmed request now. Commits. Returns what happened (counts only)."""
    now = datetime.now(UTC)
    if req.scope == "member":
        from app.services.privacy.member_erasure import erase_member

        uid = str(req.target_user_id)
        try:
            res = await erase_member(db, uid, requested_by_hash=req.requested_by_hash, confirmed_by_hash=req.confirmed_by_hash)
        except ValueError as exc:
            await db.refresh(req)
            req.status, req.blocked_reason = BLOCKED, str(exc)[:40]
            await db.commit()
            return {"status": BLOCKED, "reason": req.blocked_reason}
        await db.refresh(req)
        req.status, req.target_user_id, req.requested_by_user_id = EXECUTED, None, None
        await db.commit()
        return {"status": EXECUTED, "already_erased": res.already_erased}
    from app.config import get_settings

    if req.mode == "hard_delete" and not get_settings().org_erasure_hard_delete_enabled:
        req.status, req.blocked_reason = BLOCKED, "hard_delete_disabled"  # switched off after it was scheduled
        await db.commit()
        return {"status": BLOCKED, "reason": req.blocked_reason}
    org_id = str(req.target_org_id)
    result = await erase_org(db, org_id, mode=req.mode, requested_by_hash=req.requested_by_hash,
                             confirmed_by_hash=req.confirmed_by_hash)
    await db.refresh(req)  # erase_org committed and cleared the raw ids
    req.status, req.record_id = EXECUTED, result.record.id
    req.target_org_id = req.requested_by_user_id = None
    req.confirmed_at = req.confirmed_at or now
    await db.commit()
    return {"status": EXECUTED, "already_erased": result.already_erased, "record_id": result.record.id}


async def execute_due(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """The scheduler's step: run every scheduled request whose cooling-off is over; expire stale pending ones."""
    now = now or datetime.now(UTC)
    counts = {"executed": 0, "blocked": 0, "failed": 0, "expired": 0}
    ids = [r.id for r in (await db.execute(
        select(OrgErasureRequest).where(OrgErasureRequest.status == SCHEDULED).order_by(OrgErasureRequest.execute_after)
    )).scalars() if r.execute_after is not None and _aware(r.execute_after) <= now]
    for rid in ids:
        req = await db.get(OrgErasureRequest, rid)
        if req is None or req.status != SCHEDULED:
            continue
        try:
            outcome = await run_request(db, req)
        except Exception:
            await db.rollback()
            logger.exception("erasure request %s failed; it stays scheduled and is retried", rid)
            counts["failed"] += 1
            continue
        counts["blocked" if outcome["status"] == BLOCKED else "executed"] += 1
    stale = (await db.execute(select(OrgErasureRequest).where(OrgErasureRequest.status == PENDING))).scalars().all()
    for req in stale:
        if _aware(req.expires_at) < now:
            req.status = EXPIRED
            counts["expired"] += 1
    await db.commit()
    return counts


async def reapply_erased(db: AsyncSession, erased: dict[str, str]) -> dict[str, int]:
    """After a restore from a backup older than an erasure: erase again whatever the restore brought back.

    `erased` maps the hashes the operator kept OUTSIDE the database (the `org_hash` column of
    `org_erasure_records`, exported before the restore) to their mode: "anonymise" / "hard_delete" for an organisation
    hash, `member_anonymise` for a person's. The ids in the restored database are hashed the same way and compared, so
    nobody has to keep a list of raw ids. Idempotent: whatever is already erased is skipped.
    """
    from app.models.organization import Organization
    from app.models.user import User
    from app.services.privacy.member_erasure import MEMBER_MODE, erase_member, is_tombstone

    counts = {"organisations": 0, "members": 0, "skipped": 0}
    for org_id in (await db.execute(select(Organization.id))).scalars().all():
        mode = erased.get(hash_id("org", str(org_id)))
        if mode in ("anonymise", "hard_delete"):
            res = await erase_org(db, str(org_id), mode=mode)
            counts["skipped" if res.already_erased else "organisations"] += 1
    for uid, email in (await db.execute(select(User.id, User.email))).all():
        if erased.get(hash_id("member", str(uid))) == MEMBER_MODE and not is_tombstone(email):
            try:
                await erase_member(db, str(uid))
                counts["members"] += 1
            except ValueError:
                counts["skipped"] += 1  # a sole owner whose company is erased above goes with it
    return counts


__all__ = ["BLOCKED", "CANCELLED", "EXECUTED", "EXPIRED", "PENDING", "REQUEST_TTL", "SCHEDULED", "cancel",
           "cooling_off", "execute_due", "hash_id", "reapply_erased", "run_request", "schedule"]
