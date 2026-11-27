"""What only a person can fix, noticed by the scheduler and sent to the platform operators.

`watch()` runs at scheduler start and every 15 minutes (`scheduler._ops_watch`). Each check ends in
`operator_alerts.raise_alert`, which de-duplicates per cool-down window, so a condition that lasts for days
is a few mails, not hundreds.

* preflight warnings: the settings the server runs with (no LLM key, no proxy setting, ...), once per window
  for one set of codes;
* failing destinations: a company's destination (channel + address) with `OUTBOX_FAILURE_ALERT_THRESHOLD`
  failed outbox rows in 24 hours (operator alerts and other platform mail are not counted: an alert about
  failing mail would otherwise feed itself);
* backups: the backup cron reports to `POST /platform/ops/backup-report` (`record_backup_report`). A failed
  report alerts at once; no successful report for `BACKUP_MAX_AGE_HOURS` alerts too. Only when
  `OPS_REPORT_TOKEN` is set (the endpoint is then in use); without it nothing is checked and nothing is claimed.

* refused AI calls: masked mode failed closed (no company context, names dictionary unreadable) in the last
  24 hours, by reason (`app/platform/llm_egress/refusals.py`).

Not covered here: "readiness degraded for longer than M minutes". `/ready` is polled from outside by the
uptime monitor of the owner's choice (decision D4); the application cannot report that it is down.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.job_run import OpsState
from app.models.outbox_message import FAILED, OutboxMessage

logger = logging.getLogger(__name__)

BACKUP_KEY = "backup"
WATCH_STARTED_KEY = "ops_watch_started"
_PLATFORM_KINDS = ("operator_alert",)


async def _load(db: AsyncSession, key: str) -> dict[str, Any]:
    row = await db.get(OpsState, key)
    if row is None:
        return {}
    try:
        value = json.loads(row.value)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def _store(db: AsyncSession, key: str, value: dict[str, Any], now: datetime) -> None:
    row = await db.get(OpsState, key)
    payload = json.dumps(value, sort_keys=True)
    if row is None:
        db.add(OpsState(key=key, value=payload, updated_at=now))
    else:
        row.value, row.updated_at = payload, now


async def backup_state(db: AsyncSession) -> dict[str, Any]:
    """The last backup report, for the operator view of `/ready`: times and status, never a path."""
    state = await _load(db, BACKUP_KEY)
    return {
        "reporting": bool(get_settings().ops_report_token),
        "last_status": state.get("last_status"),
        "last_attempt_at": state.get("last_attempt_at"),
        "last_success_at": state.get("last_success_at"),
        "max_age_hours": get_settings().backup_max_age_hours,
    }


async def record_backup_report(db: AsyncSession, *, ok: bool, detail: str = "", now: datetime | None = None) -> dict[str, Any]:
    """Store what the backup cron said (the caller commits) and alert at once on a failure."""
    from app.services.operator_alerts import raise_alert

    moment = now or datetime.now(UTC)
    state = await _load(db, BACKUP_KEY)
    state["last_attempt_at"] = moment.isoformat()
    state["last_status"] = "ok" if ok else "failed"
    if ok:
        state["last_success_at"] = moment.isoformat()
    state["detail"] = " ".join(detail.split())[:200]
    await _store(db, BACKUP_KEY, state, moment)
    if not ok:
        await raise_alert(db, "backup_failed", dedupe=moment.strftime("%Y-%m-%d"), detail=state["detail"], now=moment)
    return state


async def _backup_check(db: AsyncSession, now: datetime) -> int:
    from app.services.operator_alerts import raise_alert

    settings = get_settings()
    if not settings.ops_report_token:
        return 0
    started = await _load(db, WATCH_STARTED_KEY)
    if not started:
        await _store(db, WATCH_STARTED_KEY, {"at": now.isoformat()}, now)
        started = {"at": now.isoformat()}
    limit = timedelta(hours=max(1, settings.backup_max_age_hours))
    state = await _load(db, BACKUP_KEY)
    last = state.get("last_success_at")
    reference = datetime.fromisoformat(last) if last else datetime.fromisoformat(started["at"])
    if now - reference <= limit:
        return 0
    detail = f"son başarılı yedek={last or 'hiç'} sınır={settings.backup_max_age_hours}sa"
    return await raise_alert(db, "backup_stale", dedupe="stale", detail=detail, now=now)


async def _failing_destinations(db: AsyncSession, now: datetime) -> int:
    from app.services.operator_alerts import raise_alert

    threshold = max(1, get_settings().outbox_failure_alert_threshold)
    rows = (
        await db.execute(
            select(OutboxMessage.org_id, OutboxMessage.channel, OutboxMessage.recipient, func.count())
            .where(
                OutboxMessage.status == FAILED,
                OutboxMessage.created_at > now - timedelta(hours=24),
                OutboxMessage.kind.not_in(_PLATFORM_KINDS) | OutboxMessage.kind.is_(None),
            )
            .group_by(OutboxMessage.org_id, OutboxMessage.channel, OutboxMessage.recipient)
            .having(func.count() >= threshold)
        )
    ).all()
    raised = 0
    for org_id, channel, recipient, count in rows:
        # The address is not put in the mail: a digest tells the operator it is one destination, the
        # outbox (organisation, channel) tells which company.
        digest = hashlib.sha256(f"{org_id}|{channel}|{recipient}".encode()).hexdigest()[:12]
        raised += await raise_alert(
            db, "outbox_failing", dedupe=digest, now=now,
            detail=f"org={org_id} kanal={channel} hedef#{digest} son24sa_başarısız={count}",
        )
    return raised


async def _preflight_warnings(db: AsyncSession, now: datetime) -> int:
    from app.core.preflight import WARN, check_settings
    from app.services.operator_alerts import raise_alert

    codes = sorted(f.code for f in check_settings(get_settings()) if f.severity == WARN)
    if not codes:
        return 0
    return await raise_alert(
        db, "preflight_warning", dedupe=",".join(codes), detail="kodlar: " + ", ".join(codes), now=now
    )


async def _llm_egress_refusals(db: AsyncSession, now: datetime) -> int:
    """Masked mode refused AI calls (fail closed) in the last 24 hours: tell the operators, by reason."""
    from app.models.llm_call_log import LLMCallLog
    from app.platform.llm_egress.refusals import ERROR_PREFIX
    from app.services.operator_alerts import raise_alert

    rows = (await db.execute(
        select(LLMCallLog.error, func.count()).where(
            LLMCallLog.error.like(ERROR_PREFIX + "%"), LLMCallLog.created_at > now - timedelta(hours=24)
        ).group_by(LLMCallLog.error)
    )).all()
    if not rows:
        return 0
    detail = " ".join(f"{str(e).removeprefix(ERROR_PREFIX)}={n}" for e, n in sorted(rows))
    return await raise_alert(db, "llm_egress_refused", dedupe=now.strftime("%Y-%m-%d"), detail=detail, now=now)


async def watch(now: datetime | None = None) -> int:
    """Run every check once; returns how many alert mails were addressed (0 when nothing is wrong)."""
    from app.database import engine, get_session_factory
    from app.services import outbox

    moment = now or datetime.now(UTC)
    async with get_session_factory(engine())() as db:
        total = 0
        for check in (_preflight_warnings, _failing_destinations, _backup_check, _llm_egress_refusals):
            try:
                total += await check(db, moment)
                await db.commit()
            except Exception:
                logger.exception("ops watch check %s failed", check.__name__)
                await db.rollback()
    if total:
        outbox.kick()
    return total
