"""Retention: configurable, conservative, idempotent, dry-run first, and bound to one organisation at a time.

What it does NOT do: it never deletes the books. Transactions, the ledger, the journal, open items, approvals and
decisions are kept (Turkish commercial and tax law has long statutory periods: lawyer questions Q2/Q3 in
`docs/kvkk/avukata-sorular.md`). What it purges, each with a conservative default (setting, `RETENTION_*`):

  per company (the owner may shorten these for their own company, never below `FLOOR_DAYS`)
    uploads            raw file, `transactions.raw_text` and text chunks of a processed upload   default: keep (0)
    outbox_bodies      body of a delivered message; recipient, status and times stay               90 days after delivery
    notifications      in-app notifications                                                         180 days
    alert_history      fired-alert history                                                          365 days
  platform-wide (settings only)
    tokens             password-reset / e-mail-verification tokens, spent or expired invitations    30 days after expiry
    audit_ip           audit-log IP address truncated (/24, /48), browser string removed; row stays 365 days
    checkpoints        LangGraph agent-run checkpoints (PostgreSQL), 3 days after the run's last step (nothing reads
                       them back); threads not namespaced by an organisation, and threads of an organisation that is
                       erased or gone, at once, whatever their age; org erasure deletes the org's at once
                       (privacy.ephemeral)
    erasure_leftovers  what a run in flight wrote for an organisation erased in the last ERASURE_SWEEP_DAYS days
                       (privacy.tombstone.sweep_erased_org)

Dry run, and what is enforced anyway: `registry_stores.PURGES` says, for every key above, whether the purge is
ENFORCED (runs whatever RETENTION_DRY_RUN says: the checkpoints and the erasure leftovers, which nothing reads, so
there is no report to review first) or DRY_RUN_DEFAULT (counted only until the operator sets RETENTION_DRY_RUN=false
after reading the first report). This module reads that registry (`ENFORCED_ALWAYS`), so the KVKK inventory rendered
from it and the behaviour cannot disagree. Every run logs one line per key: what was due and what was done.
  not here: expired export bundles (the 24-hour download lifetime, its own hourly job `export_expiry`, never gated
  by the dry-run flag), demo guest workspaces (their own hourly job, `DEMO_GUEST_TTL_HOURS`), chat history (Redis, 7 days),
  LLM prompts and responses (never stored by this product; the provider's own retention is Q1), soft-deleted rows
  (no table has a soft-delete column).

Safety: `purge_org` takes ONE organisation id and every statement it issues is filtered by it (directly or through a
job id selected under it). `run_retention` visits active organisations one by one, skipping erased ones, the demo
template and guest workspaces. `dry_run` (the default of RETENTION_DRY_RUN) only counts. Each run writes a
`RetentionRun` with counts and day numbers, never row content. Running twice purges nothing the second time.
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_rule import AlertHistory
from app.models.analysis_job import AnalysisJob
from app.models.audit_log import AuditLog
from app.models.email_verification import EmailVerificationToken
from app.models.in_app_notification import InAppNotification
from app.models.organization import Organization, OrgInvite
from app.models.outbox_message import SENT, OutboxMessage
from app.models.password_reset import PasswordResetToken
from app.models.privacy_records import RetentionRun
from app.models.rag_chunk import RagChunk
from app.models.transaction import Transaction
from app.services.org_erasure import ERASED, hash_id
from app.services.outbox import SCRUBBED
from app.services.privacy.registry import Enforcement
from app.services.privacy.registry_stores import PURGES

logger = logging.getLogger(__name__)

# The purges that run whatever RETENTION_DRY_RUN says: read from the registry the KVKK inventory is rendered from.
ENFORCED_ALWAYS = frozenset(k for k, p in PURGES.items() if p.enforcement == Enforcement.ENFORCED)
# How far back the retention run sweeps erased organisations for what a run in flight wrote after the erasure.
ERASURE_SWEEP_DAYS = 30

FLOOR_DAYS = 30
ORG_KEYS = ("upload_days", "outbox_body_days", "notification_days", "alert_history_days")
PLATFORM_KEYS = ("token_days", "audit_ip_days", "checkpoint_days")
AUDIT_PAGE = 1000


def platform_policy() -> dict[str, int]:
    from app.config import get_settings

    s = get_settings()
    return {"upload_days": s.retention_upload_days, "outbox_body_days": s.retention_outbox_body_days,
            "notification_days": s.retention_notification_days, "alert_history_days": s.retention_alert_history_days,
            "token_days": s.retention_token_days, "audit_ip_days": s.retention_audit_ip_days,
            "checkpoint_days": s.retention_checkpoint_days}


def effective_policy(org: Organization | None) -> dict[str, int]:
    """The platform default with the company's own choices laid over the per-company keys."""
    policy = platform_policy()
    chosen = (org.retention_policy if org is not None else None) or {}
    for key in ORG_KEYS:
        value = chosen.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            policy[key] = clamp(key, value, policy[key])
    return policy


def clamp(key: str, value: int, platform: int) -> int:
    """A company may only SHORTEN: between the floor and the platform default. Where the platform keeps a thing
    (0, uploads) the company may choose to purge it, from the floor up; it can never lengthen or switch a purge off."""
    if platform <= 0:
        return value if value >= FLOOR_DAYS else platform
    return min(max(value, FLOOR_DAYS), platform) if platform >= FLOOR_DAYS else platform


def validate_choice(choice: dict[str, Any]) -> dict[str, int]:
    """Whole days, only the per-company keys, in [FLOOR_DAYS, the platform default]: a company may shorten, never lengthen.
    (0 = keep, allowed for uploads only while the platform default is also keep.)"""
    clean: dict[str, int] = {}
    for key, value in choice.items():
        if key not in ORG_KEYS:
            raise ValueError(f"not a company setting: {key}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be a whole number of days")
        platform = platform_policy()[key]
        if value == 0 and key == "upload_days":
            if platform > 0:
                raise ValueError(f"{key} cannot be switched off: the platform default is {platform} days")
            clean[key] = 0
        elif value < FLOOR_DAYS:
            raise ValueError(f"{key} must be at least {FLOOR_DAYS} days" + (" (or 0 to keep)" if key == "upload_days" else ""))
        elif platform > 0 and value > platform:
            raise ValueError(f"{key} cannot be longer than the platform default of {platform} days")
        else:
            clean[key] = value
    return clean


def truncate_ip(raw: str | None) -> str | None:
    """IPv4 to its /24, IPv6 to its /48; anything that is not an address is dropped."""
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    prefix = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False).network_address)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def _count(db: AsyncSession, stmt: Any) -> int:
    return int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())


async def purge_org(db: AsyncSession, org_id: str, policy: dict[str, int], *, dry_run: bool, now: datetime) -> dict[str, int]:
    """One organisation's purge. Every statement below carries `org_id`; nothing here can reach another company."""
    out = {"uploads": 0, "outbox_bodies": 0, "notifications": 0, "alert_history": 0}

    days = policy["outbox_body_days"]
    if days > 0:
        where: tuple[ColumnElement[bool], ...] = (OutboxMessage.org_id == org_id, OutboxMessage.status == SENT, OutboxMessage.sent_at.is_not(None),
                 OutboxMessage.sent_at < now - timedelta(days=days), OutboxMessage.body != SCRUBBED)
        out["outbox_bodies"] = await _count(db, select(OutboxMessage.id).where(*where))
        if not dry_run and out["outbox_bodies"]:
            await db.execute(update(OutboxMessage).where(*where).values(body=SCRUBBED, last_error=None))

    days = policy["notification_days"]
    if days > 0:
        where = (InAppNotification.org_id == org_id, InAppNotification.created_at < now - timedelta(days=days))
        out["notifications"] = await _count(db, select(InAppNotification.id).where(*where))
        if not dry_run and out["notifications"]:
            await db.execute(delete(InAppNotification).where(*where))

    days = policy["alert_history_days"]
    if days > 0:
        where = (AlertHistory.org_id == org_id, AlertHistory.created_at < now - timedelta(days=days))
        out["alert_history"] = await _count(db, select(AlertHistory.id).where(*where))
        if not dry_run and out["alert_history"]:
            await db.execute(delete(AlertHistory).where(*where))

    days = policy["upload_days"]
    if days > 0:
        out["uploads"] = await _purge_uploads(db, org_id, now - timedelta(days=days), dry_run)
    return out


async def _purge_uploads(db: AsyncSession, org_id: str, cutoff: datetime, dry_run: bool) -> int:
    """Raw files of processed uploads older than the cutoff. The ledger rows stay; only the document goes."""
    jobs = (await db.execute(
        select(AnalysisJob.id, AnalysisJob.file_path).where(
            AnalysisJob.org_id == org_id, AnalysisJob.status == "completed", AnalysisJob.created_at < cutoff,
            AnalysisJob.file_path != "")
    )).all()
    if dry_run or not jobs:
        return len(jobs)
    from app.config import get_settings

    ids = [j.id for j in jobs]
    root = Path(get_settings().storage_local_path).resolve()
    for job in jobs:
        _remove_raw_file(root, job.file_path)
    await db.execute(update(AnalysisJob).where(AnalysisJob.org_id == org_id, AnalysisJob.id.in_(ids)).values(file_path=""))
    await db.execute(update(Transaction).where(Transaction.job_id.in_(ids), Transaction.raw_text.is_not(None)).values(raw_text=None))
    await db.execute(delete(RagChunk).where(RagChunk.org_id == org_id, RagChunk.job_id.in_(ids)))
    return len(jobs)


def _remove_raw_file(root: Path, recorded: str) -> None:
    """Delete exactly the uploaded raw file a job recorded: one regular file under the storage root. Reports, board
    decks, data-source files and every other file of the job are NOT touched (they are other retention classes)."""
    try:
        path = (Path(recorded) if Path(recorded).is_absolute() else Path.cwd() / recorded).resolve()
        path.relative_to(root)
    except (ValueError, OSError):
        return
    if path != root and path.is_file():
        path.unlink()


async def purge_platform(db: AsyncSession, policy: dict[str, int], *, dry_run: bool, now: datetime) -> dict[str, int]:
    """Platform-wide: tokens and invitations past their time, audit-log IP addresses past theirs (these follow
    `dry_run`), and the checkpoints (ENFORCED: deleted whatever `dry_run` says, see `ENFORCED_ALWAYS`)."""
    out = {"tokens": 0, "invitations": 0, "audit_ip": 0}
    days = policy["token_days"]
    if days > 0:
        cutoff = now - timedelta(days=days)
        for model in (PasswordResetToken, EmailVerificationToken):
            where = (model.expires_at < cutoff,)
            out["tokens"] += await _count(db, select(model.id).where(*where))
            if not dry_run:
                await db.execute(delete(model).where(*where))
        inv = ((OrgInvite.expires_at < cutoff) | (OrgInvite.accepted.is_(True) & (OrgInvite.created_at < cutoff)),)
        out["invitations"] = await _count(db, select(OrgInvite.id).where(*inv))
        if not dry_run and out["invitations"]:
            await db.execute(delete(OrgInvite).where(*inv))
    days = policy["audit_ip_days"]
    if days > 0:
        out["audit_ip"] = await _audit_ip(db, now - timedelta(days=days), dry_run)
    days = policy.get("checkpoint_days", 0)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        from app.services.checkpoint_data import (
            purge_old_checkpoints,
            purge_orphaned_checkpoints,
            purge_unscoped_checkpoints,
        )

        # ENFORCED (registry_stores.PURGES): nothing reads a checkpoint back, so `dry_run` does not apply to them.
        if days > 0:
            # The langgraph library stamps a checkpoint's `ts` with the wall clock (third-party code is not on the
            # app clock, app/core/clock.py): its age is measured against the wall clock, never a pinned instant.
            from app.core.clock import wall_now

            out["checkpoints"] = await purge_old_checkpoints(
                db, days=days, dry_run=_dry("checkpoints", dry_run), now=wall_now())
        # Whatever the age and even with checkpoint_days = 0: a thread without its organisation is an orphan, and so
        # is one whose organisation is erased or gone.
        out["checkpoints_unscoped"] = await purge_unscoped_checkpoints(db, dry_run=_dry("checkpoints_unscoped", dry_run))
        out["checkpoints_orphaned"] = await purge_orphaned_checkpoints(db)
    return out


def _dry(key: str, dry_run: bool) -> bool:
    """The dry-run flag as it applies to one purge: never to an ENFORCED one."""
    return dry_run and key not in ENFORCED_ALWAYS


async def sweep_erasure_leftovers(db: AsyncSession, now: datetime) -> int:
    """ENFORCED: run the final sweep (`tombstone.sweep_erased_org`) again for every organisation erased (anonymised,
    so its row and id remain) in the last `ERASURE_SWEEP_DAYS` days. Matched by the proof record's hash, never by
    the name `[erased]` a company could type. Returns the rows and threads removed. Commits per organisation."""
    from app.models.erasure_record import OrgErasureRecord
    from app.services.privacy.tombstone import ORG_MODES, sweep_erased_org

    since = now - timedelta(days=ERASURE_SWEEP_DAYS)
    recent = set((await db.execute(select(OrgErasureRecord.org_hash).where(
        OrgErasureRecord.mode.in_(ORG_MODES), OrgErasureRecord.executed_at >= since))).scalars().all())
    if not recent:
        return 0
    inactive = (await db.execute(select(Organization.id).where(Organization.is_active.is_(False)))).scalars().all()
    await db.commit()
    removed = 0
    for org_id in inactive:
        if hash_id("org", str(org_id)) in recent:
            removed += sum((await sweep_erased_org(db, str(org_id))).values())
    return removed


async def _audit_ip(db: AsyncSession, cutoff: datetime, dry_run: bool) -> int:
    """Truncate IPs and clear browser strings of old audit rows, page by page (keyset on id). Counts rows that change."""
    changed, last = 0, ""
    while True:
        rows = (await db.execute(
            select(AuditLog.id, AuditLog.ip_address, AuditLog.user_agent)
            .where(AuditLog.created_at < cutoff, AuditLog.id > last, (AuditLog.ip_address.is_not(None)) | (AuditLog.user_agent.is_not(None)))
            .order_by(AuditLog.id).limit(AUDIT_PAGE)
        )).all()
        if not rows:
            return changed
        for row in rows:
            new_ip = truncate_ip(row.ip_address)
            if new_ip == row.ip_address and row.user_agent is None:
                continue
            changed += 1
            if not dry_run:
                await db.execute(update(AuditLog).where(AuditLog.id == row.id).values(ip_address=new_ip, user_agent=None))
        last = rows[-1].id
        if not dry_run:
            await db.flush()


def _runnable(org: Organization) -> bool:
    from app.services.demo_template import GOLDEN_SLUG

    return bool(org.is_active) and org.name != ERASED and org.slug != GOLDEN_SLUG and not org.is_demo_guest


async def run_retention(
    db: AsyncSession, *, dry_run: bool | None = None, org_id: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Run the policy over every active company (or the one given) and the platform tables; record counts.

    The ENFORCED purges (`ENFORCED_ALWAYS`) delete whatever `dry_run` says; the others only count while it is true.
    One log line per key says what was due and what was done (the observable dry-run report)."""
    from app.config import get_settings
    now = now or datetime.now(UTC)
    dry = get_settings().retention_dry_run if dry_run is None else dry_run
    leftovers: int | None = None
    if org_id is None:
        try:
            leftovers = await sweep_erasure_leftovers(db, now)
        except Exception:
            logger.exception("retention: the erasure-leftovers sweep failed; it runs again tomorrow")
            await db.rollback()
    stmt = select(Organization)
    if org_id is not None:
        stmt = stmt.where(Organization.id == org_id)
    orgs = [o for o in (await db.execute(stmt)).scalars().all() if _runnable(o)]
    run = RetentionRun(dry_run=dry, scope=hash_id("org", org_id) if org_id else "all", organisations=len(orgs),
                       policy=platform_policy(), counts={}, started_at=now)
    db.add(run)
    await db.flush()
    totals: dict[str, int] = {}
    try:
        for org in orgs:
            for key, n in (await purge_org(db, str(org.id), effective_policy(org), dry_run=dry, now=now)).items():
                totals[key] = totals.get(key, 0) + n
        if org_id is None:
            for key, n in (await purge_platform(db, platform_policy(), dry_run=dry, now=now)).items():
                totals[key] = totals.get(key, 0) + n
            if leftovers is not None:
                totals["erasure_leftovers"] = leftovers
        run.counts, run.status = totals, "done"
    except Exception:
        logger.exception("retention run failed")
        run.status = "failed"
        await db.rollback()
        run = RetentionRun(dry_run=dry, scope=run.scope, organisations=len(orgs), policy=platform_policy(), counts={}, status="failed", started_at=now)
        db.add(run)
        await db.flush()
    run.finished_at = datetime.now(UTC)
    await db.commit()
    report = {"run_id": run.id, "dry_run": dry, "status": run.status, "organisations": len(orgs), "counts": totals,
              "policy": platform_policy(), "enforced_always": sorted(ENFORCED_ALWAYS),
              "actions": {key: action(key, dry) for key in totals}}
    log_report(report)
    return report


def action(key: str, dry_run: bool) -> str:
    """What the run did with the rows a key counted: `deleted` or `counted` (dry run, kept)."""
    return "deleted" if key in ENFORCED_ALWAYS or not dry_run else "counted"


def log_report(report: dict[str, Any]) -> None:
    """The dry-run report in the log: one line for the run, one per key (counts and key names only, no content)."""
    logger.info("retention run %s: dry_run=%s status=%s organisations=%d enforced_always=%s",
                report["run_id"], report["dry_run"], report["status"], report["organisations"],
                ",".join(report["enforced_always"]))
    for key in sorted(report["counts"]):
        logger.info("retention report: store=%s due=%d action=%s", key, report["counts"][key], report["actions"][key])
    if report["dry_run"]:
        logger.warning("retention: RETENTION_DRY_RUN=true, the stores marked `counted` were kept; review this report "
                       "(table retention_runs) and set RETENTION_DRY_RUN=false (docs/ops/first-deploy-checklist.md)")
