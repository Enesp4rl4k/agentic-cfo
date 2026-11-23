"""The company export as a job: request -> queued -> running -> ready (time-limited download) -> expired.

* `request_export` records the ask (and the decision record), refuses a second one while one is live, and queues the
  build on the maintenance queue; with no queue the build runs in-process when the inline fallback is allowed, and in
  every case the hourly sweeper (`build_pending`) builds whatever is still `queued`, so a lost message is a delay,
  never a lost export.
* `build_export` claims the row with one conditional UPDATE (two workers cannot both build it), writes the bundle to
  `<storage root>/exports/<id>.zip.part`, renames it when complete, and records size and per-dataset counts.
  A failure leaves a fixed error code, no exception text, and no partial file.
* The file is served only to an owner of the company through an authenticated route, until `expires_at`
  (DATA_EXPORT_TTL_HOURS); `purge_expired` deletes the file and the path.
* `member_export` is the small, synchronous personal export (KVKK Md. 11/b): the person's own rows only.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.decision import DecidedVia, Decision, DecisionKind
from app.models.organization import Organization, OrgMembership
from app.models.privacy_records import DataExport, TermsAcceptance
from app.models.user import User
from app.services.decisions import record_decision
from app.services.privacy import export_bundle

logger = logging.getLogger(__name__)

LIVE = ("queued", "running", "ready")
STALE_RUNNING = timedelta(hours=1)
STALE_QUEUED = timedelta(minutes=2)


def storage_root() -> Path:
    from app.config import get_settings

    return Path(get_settings().storage_local_path)


def export_path(export_id: str) -> Path:
    """The ONLY place an export file lives: built from the stored id under the fixed export root, never from a
    path read back out of a row."""
    return storage_root() / "exports" / f"{export_id}.zip"


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def active_export(db: AsyncSession, org_id: str, now: datetime | None = None) -> DataExport | None:
    now = now or datetime.now(UTC)
    rows = (await db.execute(
        select(DataExport).where(DataExport.org_id == org_id, DataExport.status.in_(LIVE)).order_by(DataExport.created_at.desc())
    )).scalars().all()
    for row in rows:
        if row.status != "ready" or (row.expires_at is not None and _aware(row.expires_at) > now):
            return row
    return None


async def request_export(db: AsyncSession, user: User, org_id: str, role: str) -> tuple[DataExport, bool]:
    """Record an export request: (the export, created). A live one for the company is returned instead of a second."""
    await purge_expired(db)
    existing = await active_export(db, org_id)
    if existing is not None:
        return existing, False
    row = DataExport(org_id=org_id, requested_by=str(user.id), status="queued")
    db.add(row)
    await db.flush()
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.DATA_EXPORT, target_type="data_export", target_id=row.id,
        outcome="requested", decided_via=DecidedVia.HUMAN, decided_by=str(user.id), after={"acting_role": role},
    )
    await db.commit()
    return row, True


async def enqueue(export_id: str) -> bool:
    """Queue the build on the maintenance queue. False when there is no queue (the sweeper will build it)."""
    try:
        from app.config import get_settings
        from app.worker import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job("run_data_export", export_id, _job_id=f"data-export-{export_id}",
                               _queue_name=get_settings().arq_maintenance_queue_name)
        return True
    except Exception as exc:
        logger.info("data export %s not queued (%s); the hourly sweeper builds it", export_id, type(exc).__name__)
        return False


async def build_export(db: AsyncSession, export_id: str, now: datetime | None = None) -> str:
    """Build one queued export. Returns the status it ended in; safe to call twice."""
    from app.config import get_settings

    now = now or datetime.now(UTC)
    claimed = await db.execute(
        update(DataExport).where(DataExport.id == export_id, DataExport.status == "queued").values(status="running")
    )
    await db.commit()
    row = await db.get(DataExport, export_id)
    if row is None or not getattr(claimed, "rowcount", 0):
        return row.status if row else "missing"
    settings = get_settings()
    root = storage_root()
    final = export_path(row.id)
    part = final.with_name(final.name + ".part")
    org_id = str(row.org_id)
    if await org_is_erasing(db, org_id):  # fail closed: nothing is written for a company that is being erased
        row.status, row.error_code = "failed", "org_erasing"
        await db.commit()
        return "failed"
    try:
        part.parent.mkdir(parents=True, exist_ok=True)
        manifest = await export_bundle.build(db, row.org_id, part, root, settings.data_export_max_mb * 1024 * 1024)
        part.replace(final)
        if await org_is_erasing(db, org_id):  # the erasure began while the bundle was written: it must not survive
            raise OrgErasingError
        row.file_path, row.size_bytes = str(final), final.stat().st_size
        row.summary = {k: {"rows": d["rows"], "truncated": d["truncated"]} for k, d in manifest["datasets"].items()}
        row.summary["files"] = {"included": manifest["files"]["included"], "omitted": len(manifest["files"]["omitted"])}
        row.status, row.ready_at = "ready", now
        row.expires_at = now + timedelta(hours=settings.data_export_ttl_hours)
    except Exception as exc:
        erasing = isinstance(exc, OrgErasingError)
        if not erasing:
            logger.exception("data export %s failed", export_id)
        await db.rollback()
        part.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        fresh = await db.get(DataExport, export_id)  # None when the erasure already deleted the row
        if fresh is None:
            return "missing"
        fresh.status, fresh.error_code, fresh.file_path = "failed", "org_erasing" if erasing else "build_failed", None
        row = fresh
    try:
        await db.commit()
    except Exception:  # the row vanished under an erasure: the file is already gone
        await db.rollback()
        final.unlink(missing_ok=True)
        return "missing"
    return str(row.status)


class OrgErasingError(RuntimeError):
    pass


async def org_is_erasing(db: AsyncSession, org_id: str) -> bool:
    """True when the company is gone, erased, or an erasure request for it is executing right now."""
    from app.models.erasure_record import OrgErasureRequest
    from app.services.org_erasure import ERASED

    org = (await db.execute(select(Organization.name).where(Organization.id == org_id))).scalar_one_or_none()
    if org is None or org == ERASED:
        return True
    running = (await db.execute(select(OrgErasureRequest.id).where(
        OrgErasureRequest.target_org_id == org_id, OrgErasureRequest.status == "executing").limit(1))).first()
    return running is not None


async def build_pending(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """The sweeper: build exports still queued after the queue should have had them; re-queue a stuck `running`."""
    now = now or datetime.now(UTC)
    counts = {"built": 0, "failed": 0, "requeued": 0}
    for row in (await db.execute(select(DataExport).where(DataExport.status == "running"))).scalars().all():
        if _aware(row.created_at) < now - STALE_RUNNING:
            row.status = "queued"
            counts["requeued"] += 1
    await db.commit()
    for eid, created in (await db.execute(select(DataExport.id, DataExport.created_at).where(DataExport.status == "queued"))).all():
        if _aware(created) < now - STALE_QUEUED:
            counts["built" if await build_export(db, eid, now) == "ready" else "failed"] += 1
    return counts


async def purge_expired(db: AsyncSession, now: datetime | None = None) -> int:
    """Delete the file of every export whose download window is over; keep the row without the path.

    Not a retention policy: it is the promised download lifetime, so it does not depend on RETENTION_DRY_RUN. Files
    are located from the stored id (`export_path`), never from `file_path`.
    """
    now = now or datetime.now(UTC)
    n = 0
    rows = (await db.execute(select(DataExport).where(
        (DataExport.status == "ready") | (DataExport.status.in_(("failed", "expired")) & DataExport.file_path.is_not(None))
    ))).scalars().all()
    for row in rows:
        if row.status == "ready":
            if row.expires_at is None or _aware(row.expires_at) > now:
                continue
            row.status, n = "expired", n + 1
        _delete_export_files(row.id)
        row.file_path = None
    await db.commit()
    return n


def _delete_export_files(export_id: str) -> None:
    final = export_path(export_id)
    final.unlink(missing_ok=True)
    final.with_name(final.name + ".part").unlink(missing_ok=True)


def to_dict(row: DataExport) -> dict[str, Any]:
    return {
        "export_id": row.id, "status": row.status, "size_bytes": row.size_bytes, "summary": row.summary,
        "error_code": row.error_code, "created_at": _aware(row.created_at).isoformat(),
        "ready_at": _aware(row.ready_at).isoformat() if row.ready_at else None,
        "expires_at": _aware(row.expires_at).isoformat() if row.expires_at else None,
        "download": f"/api/v1/privacy/exports/{row.id}/download" if row.status == "ready" else None,
    }


async def member_export(db: AsyncSession, user: User) -> dict[str, Any]:
    """Everything this product holds about the person themselves: profile, memberships, their own audit entries, the
    decisions they made (what, not the payload), the notices they accepted. Never another person's data, never a secret."""
    uid = str(user.id)
    orgs = (await db.execute(
        select(OrgMembership.org_id, OrgMembership.role, OrgMembership.created_at, Organization.name)
        .join(Organization, Organization.id == OrgMembership.org_id).where(OrgMembership.user_id == uid)
    )).all()
    audit = (await db.execute(
        select(AuditLog.created_at, AuditLog.action, AuditLog.resource, AuditLog.user_role, AuditLog.ip_address, AuditLog.user_agent)
        .where(AuditLog.user_id == uid).order_by(AuditLog.created_at.desc()).limit(5000)
    )).all()
    decisions = (await db.execute(
        select(Decision.decided_at, Decision.kind, Decision.target_type, Decision.target_id, Decision.outcome, Decision.org_id)
        .where(Decision.decided_by == uid).order_by(Decision.decided_at.desc()).limit(5000)
    )).all()
    notices = (await db.execute(
        select(TermsAcceptance.document, TermsAcceptance.version, TermsAcceptance.accepted_at)
        .where(TermsAcceptance.user_id == uid).order_by(TermsAcceptance.accepted_at)
    )).all()
    iso = export_bundle._plain
    return {
        "format": "tiphys-personal-export/1", "generated_at": datetime.now(UTC).isoformat(),
        "profile": {"user_id": uid, "email": user.email, "full_name": user.full_name, "role": str(getattr(user.role, "value", user.role)),
                    "sso_provider": user.sso_provider, "email_verified_at": iso(user.email_verified_at),
                    "last_login_at": iso(user.last_login_at or user.last_login), "created_at": iso(user.created_at)},
        "memberships": [{"organisation_id": o, "organisation_name": n, "role": r, "since": iso(c)} for o, r, c, n in orgs],
        "audit_entries": [{"at": iso(t), "action": a, "resource": res, "role": role, "ip_address": ip, "user_agent": ua}
                          for t, a, res, role, ip, ua in audit],
        "decisions_made": [{"at": iso(t), "kind": k, "target_type": tt, "target_id": ti, "outcome": o, "organisation_id": org}
                           for t, k, tt, ti, o, org in decisions],
        "notices_accepted": [{"document": d, "version": v, "at": iso(t)} for d, v, t in notices],
        "not_included": ["password hash", "API key", "tokens", "other people's data",
                         "the company's records (use the company export, owner only)"],
    }
