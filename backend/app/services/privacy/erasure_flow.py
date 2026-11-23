"""The life of an erasure request: pending -> scheduled (cooling-off) -> executed | cancelled | expired | blocked.

`pending`    a person asked; nothing is touched; the owner has `REQUEST_TTL` to confirm.
`scheduled`  confirmed; the destructive step waits until `execute_after` (ERASURE_COOLING_OFF_DAYS, default 7) and
             anyone with the right to cancel can still stop it.
`executing`  the executor claimed it (one conditional UPDATE) and keeps renewing the claim; cancel is refused.
`failed`     the erasure transaction was rolled back whole (no file touched); `failure_code` says why (fixed code);
             the executor retries it hourly up to MAX_ATTEMPTS, then `blocked: retries_exhausted` + operator alert.
`cleanup_pending`  the rows are gone (committed together with a durable cleanup plan); files, caches and Redis are
             still being cleared, retried hourly. Never cancellable.
`executed`   the erasure ran; only hashes remain on the request.
`cancelled`  stopped during the cooling-off window.
`blocked`    the window passed but the erasure may not run (a sole owner); `blocked_reason` is a fixed code.

The executor (`execute_due`, run by the scheduler) acts on exactly the request rows it loads: the organisation or
person it erases is the one named on the request, never a value computed elsewhere, so it cannot touch another
tenant. Running it twice does nothing the second time (the status moved on). Cancel and the executor meet only in
conditional UPDATEs on the status column, so exactly one of them wins and the loser changes nothing.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.decision import DecidedVia, DecisionKind
from app.models.erasure_record import OrgErasureRecord, OrgErasureRequest
from app.services.decisions import record_decision
from app.services.org_erasure import erase_org, hash_id
from app.services.privacy import erasure_cleanup

logger = logging.getLogger(__name__)

REQUEST_TTL = timedelta(days=7)
PENDING, SCHEDULED, EXECUTED, CANCELLED, EXPIRED, BLOCKED = (
    "pending", "scheduled", "executed", "cancelled", "expired", "blocked")
FAILED = "failed"
CLEANUP_PENDING = erasure_cleanup.CLEANUP_PENDING
EXECUTING = erasure_cleanup.EXECUTING
STOPPABLE = (PENDING, SCHEDULED, FAILED)  # `executing` is deliberately absent: once claimed, it cannot be cancelled
STALE_CLAIM = timedelta(hours=2)  # a claim not renewed for this long belongs to a dead worker
HEARTBEAT = timedelta(minutes=20)  # a live run renews its claim this often
CLEANUP_LEASE = timedelta(minutes=15)
MAX_ATTEMPTS = 24  # about a day of hourly retries


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
    """Stop a pending, scheduled or failed-and-waiting request. Raises ValueError(status) when it cannot be stopped.

    One conditional UPDATE decides: it matches only a row that is still stoppable, so it cannot overwrite a request the
    executor has already claimed (`executing`) or finished. The caller reports success only when this returns.
    """
    result: Any = await db.execute(
        update(OrgErasureRequest)
        .where(OrgErasureRequest.id == req.id, OrgErasureRequest.status.in_(STOPPABLE))
        .values(status=CANCELLED, cancelled_at=datetime.now(UTC), cancelled_by_hash=by_hash)
        .execution_options(synchronize_session="fetch")
    )
    await db.refresh(req)  # the instance may be stale (expire_on_commit=False): show what the database says
    if result.rowcount != 1:
        raise ValueError(req.status)
    if req.scope == "org" and req.target_org_id:
        await record_decision(
            db, org_id=str(req.target_org_id), kind=DecisionKind.ERASURE, target_type="org_erasure_request",
            target_id=req.id, outcome="cancelled",
            decided_via=DecidedVia.HUMAN if decided_by else DecidedVia.SYSTEM, decided_by=decided_by,
            after={"mode": req.mode, "initiated_by": req.initiated_by, "acting_role": role},
        )


async def _claim(db: AsyncSession, rid: str, now: datetime) -> bool:
    """Atomically take a request for execution. Commits. False means someone else got there first (cancelled, running,
    done) and NOTHING destructive may happen."""
    due = and_(OrgErasureRequest.status.in_((SCHEDULED, FAILED)), OrgErasureRequest.execute_after <= now)
    immediate = and_(OrgErasureRequest.status == PENDING, OrgErasureRequest.confirmed_at.is_not(None),
                     OrgErasureRequest.execute_after.is_(None))  # confirmed with no cooling-off window
    result: Any = await db.execute(
        update(OrgErasureRequest).where(OrgErasureRequest.id == rid, or_(due, immediate))
        .values(status=EXECUTING, claimed_at=now, failure_code=None, attempts=OrgErasureRequest.attempts + 1)
        .execution_options(synchronize_session="fetch")
    )
    await db.commit()
    return bool(result.rowcount == 1)


async def _finish(db: AsyncSession, rid: str, status: str, **values: Any) -> None:
    """Leave `executing` for a final state; only a row still `executing` moves. Commits."""
    await db.execute(
        update(OrgErasureRequest).where(OrgErasureRequest.id == rid, OrgErasureRequest.status == EXECUTING)
        .values(status=status, **values).execution_options(synchronize_session="fetch")
    )
    await db.commit()


async def _alert(rid: str, reason: str) -> None:
    """Tell the operators (the existing operator-alert mechanism; ids and a fixed reason only, never personal data)."""
    from app.services import operator_alerts

    await operator_alerts.alert_in_own_session(
        "job_failed", dedupe=f"erasure:{rid}:{reason}", detail=f"iş=erasure_executor talep={rid} neden={reason}")


def _failure_code(exc: BaseException) -> str:
    from app.services.privacy.ephemeral import AgentMemoryDeleteError

    return "agent_memory_delete_failed" if isinstance(exc, AgentMemoryDeleteError) else "erase_failed"


async def _heartbeat(bind: Any, rid: str) -> None:
    """While the erasure runs, renew the claim so the executor never takes a LIVE run for a dead one."""
    maker = async_sessionmaker(bind, expire_on_commit=False)
    while True:
        await asyncio.sleep(HEARTBEAT.total_seconds())
        try:
            async with maker() as s:
                await s.execute(update(OrgErasureRequest).where(
                    OrgErasureRequest.id == rid, OrgErasureRequest.status == EXECUTING).values(claimed_at=datetime.now(UTC)))
                await s.commit()
        except Exception:
            logger.warning("erasure heartbeat for %s could not be written", rid)


async def run_request(db: AsyncSession, req: OrgErasureRequest, *, now: datetime | None = None) -> dict[str, Any]:
    """Execute one confirmed request now. Commits. Returns what happened (counts only).

    Claims the request first (`_claim`); when the claim is lost it returns `{"claimed": False, "status": <current>}`
    and does nothing. The erasure is ONE transaction that also stores the cleanup plan (`erase_org`): a failure
    rolls everything back, touches no file, leaves the request `failed` with a fixed `failure_code` and re-raises; the
    hourly executor retries it (`MAX_ATTEMPTS`, then `blocked: retries_exhausted` and an operator alert). After the
    commit the request is `cleanup_pending`, no longer cancellable, and `run_cleanup_step` finishes it.
    """
    from app.services.privacy.erasure_cleanup import InvalidTargetError

    now = now or datetime.now(UTC)
    rid = req.id
    if not await _claim(db, rid, now):
        await db.refresh(req)
        return {"claimed": False, "status": req.status}
    await db.refresh(req)
    bind = db.bind
    beat = asyncio.create_task(_heartbeat(bind, rid)) if bind is not None else None
    try:
        outcome = await _execute(db, req, rid, now)
    except InvalidTargetError:
        await db.rollback()
        await _finish(db, rid, BLOCKED, blocked_reason="invalid_target")
        await _alert(rid, "invalid_target")
        return {"status": BLOCKED, "reason": "invalid_target"}
    except Exception as exc:
        await db.rollback()
        await _finish(db, rid, FAILED, failure_code=_failure_code(exc))
        raise
    finally:
        if beat is not None:
            beat.cancel()
    if outcome.get("status") == CLEANUP_PENDING:
        return await run_cleanup_step(db, rid, now, outcome)
    return outcome


async def _execute(db: AsyncSession, req: OrgErasureRequest, rid: str, now: datetime) -> dict[str, Any]:
    if req.scope == "member":
        from app.services.privacy.member_erasure import erase_member

        uid = str(req.target_user_id)
        try:
            res = await erase_member(db, uid, requested_by_hash=req.requested_by_hash, confirmed_by_hash=req.confirmed_by_hash)
        except ValueError as exc:
            await db.rollback()
            code = str(exc)[:40]
            await _finish(db, rid, BLOCKED, blocked_reason=code)
            return {"status": BLOCKED, "reason": code}
        await _finish(db, rid, EXECUTED, target_user_id=None, requested_by_user_id=None)
        return {"status": EXECUTED, "already_erased": res.already_erased}
    from app.config import get_settings

    if req.mode == "hard_delete" and not get_settings().org_erasure_hard_delete_enabled:
        await _finish(db, rid, BLOCKED, blocked_reason="hard_delete_disabled")  # switched off after it was scheduled
        return {"status": BLOCKED, "reason": "hard_delete_disabled"}
    if req.target_org_id is None:
        # The id is gone because an erasure of this company already committed (this request or another one): never
        # run anything for a missing id. Finish from the proof record when there is one.
        rec = (await db.execute(select(OrgErasureRecord).where(OrgErasureRecord.org_hash == req.org_hash)
                                .order_by(OrgErasureRecord.seq.desc()).limit(1))).scalar_one_or_none()
        if rec is None:
            await _finish(db, rid, BLOCKED, blocked_reason="no_target")
            await _alert(rid, "no_target")
            return {"status": BLOCKED, "reason": "no_target"}
        await _finish(db, rid, EXECUTED, record_id=rec.id)
        return {"status": EXECUTED, "already_erased": True, "record_id": rec.id}
    result = await erase_org(db, str(req.target_org_id), mode=req.mode, requested_by_hash=req.requested_by_hash,
                             confirmed_by_hash=req.confirmed_by_hash, request_id=rid)
    if result.already_erased:
        await _finish(db, rid, EXECUTED, record_id=result.record.id, target_org_id=None, requested_by_user_id=None)
        return {"status": EXECUTED, "already_erased": True, "record_id": result.record.id}
    return {"status": CLEANUP_PENDING, "already_erased": False, "record_id": result.record.id}


async def run_cleanup_step(db: AsyncSession, rid: str, now: datetime, outcome: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the durable cleanup plan of a `cleanup_pending` request (files, caches, Redis). Idempotent; commits.

    A lease (`claimed_at`) keeps two runners off one plan. A failure leaves the plan in place for the next hourly try
    and alerts the operators once; after `MAX_ATTEMPTS` the request is finished with what could be done (Redis keys
    expire by their own time-to-live) and the counts say what was left.
    """
    from app.services.privacy.erasure_cleanup import InvalidTargetError, is_incomplete, run_cleanup

    taken: Any = await db.execute(
        update(OrgErasureRequest).where(
            OrgErasureRequest.id == rid, OrgErasureRequest.status == CLEANUP_PENDING,
            or_(OrgErasureRequest.claimed_at.is_(None), OrgErasureRequest.claimed_at < now - CLEANUP_LEASE))
        .values(claimed_at=now, attempts=OrgErasureRequest.attempts + 1).execution_options(synchronize_session="fetch"))
    await db.commit()
    base = dict(outcome or {})
    if taken.rowcount != 1:
        return {**base, "claimed": False, "status": CLEANUP_PENDING}
    req = await db.get(OrgErasureRequest, rid)
    if req is None:
        return {**base, "status": CLEANUP_PENDING, "claimed": False}
    await db.refresh(req)
    plan, attempts = dict(req.cleanup_plan or {}), int(req.attempts)
    record_id = req.record_id
    try:
        counts = await run_cleanup(plan)
    except InvalidTargetError:
        await db.execute(update(OrgErasureRequest).where(OrgErasureRequest.id == rid, OrgErasureRequest.status == CLEANUP_PENDING)
                         .values(status=BLOCKED, blocked_reason="invalid_target", cleanup_plan=None))
        await db.commit()
        await _alert(rid, "invalid_target")
        return {"status": BLOCKED, "reason": "invalid_target"}
    except Exception:
        logger.exception("erasure cleanup %s failed; it stays cleanup_pending and is retried", rid)
        await db.rollback()
        await db.execute(update(OrgErasureRequest).where(OrgErasureRequest.id == rid, OrgErasureRequest.status == CLEANUP_PENDING)
                         .values(claimed_at=None, failure_code="cleanup_failed"))
        await db.commit()
        await _alert(rid, "cleanup_failed")
        return {**base, "status": CLEANUP_PENDING, "cleanup_failed": True, "record_id": record_id}
    if is_incomplete(counts) and attempts < MAX_ATTEMPTS:
        await db.execute(update(OrgErasureRequest).where(OrgErasureRequest.id == rid, OrgErasureRequest.status == CLEANUP_PENDING)
                         .values(claimed_at=None, failure_code="cleanup_incomplete", post_commit_counts=counts))
        await db.commit()
        return {**base, "status": CLEANUP_PENDING, "record_id": record_id}
    await db.execute(update(OrgErasureRequest).where(OrgErasureRequest.id == rid, OrgErasureRequest.status == CLEANUP_PENDING)
                     .values(status=EXECUTED, cleanup_plan=None, failure_code=None, claimed_at=None,
                             post_commit_counts=counts))
    await db.commit()
    return {**base, "status": EXECUTED, "record_id": record_id}


async def execute_due(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """The scheduler's step: run every request whose cooling-off is over, finish pending cleanups, expire stale pending ones.

    * `failed` requests are retried here, up to `MAX_ATTEMPTS`, then `blocked: retries_exhausted` and an operator alert.
    * A claim whose heartbeat stopped for `STALE_CLAIM` (the worker is dead) is released to `failed`; the erasure is one
      transaction, so nothing is half done and a retry is safe. A live run keeps renewing its claim and is never released.
    * `cleanup_pending` requests (rows already gone) only ever run their stored plan, for the org id stored in it.
    """
    now = now or datetime.now(UTC)
    counts = {"executed": 0, "blocked": 0, "failed": 0, "expired": 0, "skipped": 0, "cleanup_pending": 0}
    await db.execute(
        update(OrgErasureRequest)
        .where(OrgErasureRequest.status == EXECUTING, OrgErasureRequest.claimed_at < now - STALE_CLAIM)
        .values(status=FAILED, failure_code="interrupted").execution_options(synchronize_session="fetch")
    )
    await db.commit()
    spent = (await db.execute(select(OrgErasureRequest.id).where(
        OrgErasureRequest.status == FAILED, OrgErasureRequest.attempts >= MAX_ATTEMPTS))).scalars().all()
    for rid in spent:
        await db.execute(update(OrgErasureRequest).where(OrgErasureRequest.id == rid, OrgErasureRequest.status == FAILED)
                         .values(status=BLOCKED, blocked_reason="retries_exhausted"))
        counts["blocked"] += 1
    await db.commit()
    for rid in spent:
        await _alert(rid, "retries_exhausted")
    # Cleanups already waiting when this run began; one a due request leaves behind now waits for the next hour.
    pending = (await db.execute(select(OrgErasureRequest.id).where(OrgErasureRequest.status == CLEANUP_PENDING))).scalars().all()
    ids = [r.id for r in (await db.execute(
        select(OrgErasureRequest).where(OrgErasureRequest.status.in_((SCHEDULED, FAILED)))
        .order_by(OrgErasureRequest.execute_after)
    )).scalars() if r.execute_after is not None and _aware(r.execute_after) <= now]
    for rid in ids:
        req = await db.get(OrgErasureRequest, rid)
        if req is None:
            continue
        try:
            outcome = await run_request(db, req, now=now)
        except Exception:
            await db.rollback()
            logger.exception("erasure request %s failed; it is marked failed and retried", rid)
            counts["failed"] += 1
            continue
        _tally(counts, outcome)
    for rid in pending:
        _tally(counts, await run_cleanup_step(db, rid, now))
    stale = (await db.execute(select(OrgErasureRequest).where(OrgErasureRequest.status == PENDING))).scalars().all()
    for req in stale:
        if _aware(req.expires_at) < now:
            req.status = EXPIRED
            counts["expired"] += 1
    await db.commit()
    return counts


def _tally(counts: dict[str, int], outcome: dict[str, Any]) -> None:
    status = outcome.get("status")
    if outcome.get("claimed") is False:
        counts["skipped"] += 1  # cancelled or taken meanwhile: nothing was touched
    elif status == BLOCKED:
        counts["blocked"] += 1
    elif status == CLEANUP_PENDING:
        counts["cleanup_pending"] += 1
    else:
        counts["executed"] += 1


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
            try:
                res = await erase_org(db, str(org_id), mode=mode)
            except erasure_cleanup.InvalidTargetError:
                counts["skipped"] += 1
                continue
            counts["skipped" if res.already_erased else "organisations"] += 1
    for uid, email in (await db.execute(select(User.id, User.email))).all():
        if erased.get(hash_id("member", str(uid))) == MEMBER_MODE and not is_tombstone(email):
            try:
                await erase_member(db, str(uid))
                counts["members"] += 1
            except ValueError:
                counts["skipped"] += 1  # a sole owner whose company is erased above goes with it
    return counts


__all__ = ["BLOCKED", "CANCELLED", "CLEANUP_PENDING", "EXECUTED", "EXECUTING", "EXPIRED", "FAILED", "PENDING", "REQUEST_TTL", "SCHEDULED", "cancel",
           "cooling_off", "execute_due", "hash_id", "reapply_erased", "run_request", "schedule"]
