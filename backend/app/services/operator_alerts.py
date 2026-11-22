"""One hook to tell the platform operators something needs a human: an e-mail through the outbox.

Nothing here sends: `raise_alert` writes an `operator_alert` immediate row per operator address
(`PLATFORM_OPERATOR_EMAILS`) and the outbox sender delivers it, retries it and records the outcome like any
other mail. Two guards keep it from becoming noise:

* de-duplicated and rate-limited by the outbox key: one alert code + subject + window per recipient is
  written once per `OPERATOR_ALERT_COOLDOWN_MINUTES`, however many times the trigger fires;
* the text is fixed per code; the only variable part is a short `detail` made of identifiers (job name,
  period, counts, organisation id), never an address, a name or a figure of a company.

Triggers: a scheduled job that failed N times, a destination whose outbox rows keep failing, a missed
briefing that the scheduler caught up, preflight warnings, a failed or stale backup (`services/ops_watch.py`).
An alert that cannot be delivered is a failed outbox row like any other (and shows on `/ready`).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.email_address import normalize_email

logger = logging.getLogger(__name__)

# code -> (subject, what it means and what to do). Turkish first, English second, like the other templates.
ALERTS: dict[str, tuple[str, str]] = {
    "job_failed": (
        "Zamanlanmış iş tekrar tekrar başarısız",
        "Zamanlanmış bir iş art arda başarısız oldu; yeniden denemeler durdu. Günlükte iş adını arayın "
        "(docs/ops/runbooks/briefing-not-sent.md).\nA scheduled job failed repeatedly and retries stopped.",
    ),
    "outbox_failing": (
        "Bir hedefe e-posta/bildirim gitmiyor",
        "Bir şirketin bir hedefine giden mesajlar tekrar tekrar başarısız. Satırların last_error alanına "
        "bakın (docs/ops/runbooks/login-and-email.md).\nMessages to one destination keep failing.",
    ),
    "briefing_caught_up": (
        "Kaçan bülten telafi edildi",
        "Zamanlayıcı kaçırılan bir bülten çalışmasını (yeniden başlatma?) sonradan çalıştırdı. Bir şey "
        "yapmanız gerekmez; zamanlayıcının neden durduğuna bakın.\nThe scheduler ran a missed briefing late.",
    ),
    "preflight_warning": (
        "Başlangıç denetimi uyarıları",
        "Sunucu çalışıyor ama bazı ayarlar eksik veya zayıf (uyarı kodları aşağıda). "
        "docs/ops/configuration.md.\nThe server runs with warnings (codes below).",
    ),
    "backup_failed": (
        "Yedekleme başarısız",
        "Yedekleme betiği başarısız olduğunu bildirdi. docs/ops/runbooks/db-restore.md.\nThe backup reported failure.",
    ),
    "backup_stale": (
        "Yedek raporu eski veya yok",
        "Son başarılı yedek raporu izin verilen süreden eski ya da hiç gelmedi. Cron çalışıyor mu?\n"
        "The newest successful backup report is too old or missing.",
    ),
}


def operators() -> list[str]:
    raw = get_settings().platform_operator_emails or ""
    return sorted({normalize_email(e) for e in raw.split(",") if e.strip()})


def _bucket(now: datetime) -> int:
    minutes = max(1, get_settings().operator_alert_cooldown_minutes)
    return int(now.timestamp() // (minutes * 60))


def _one_line(value: str, limit: int = 200) -> str:
    return " ".join(value.split())[:limit]


async def raise_alert(
    db: AsyncSession, code: str, *, dedupe: str = "", detail: str = "", now: datetime | None = None
) -> int:
    """Queue the alert for every operator (the caller commits); returns the number of operators addressed.

    `dedupe` distinguishes alerts of one code about different things (a job, a destination); the same
    code + dedupe writes nothing new inside one cool-down window (the outbox key is unique)."""
    from app.services import mail_capability, outbox_immediate

    subject, text = ALERTS[code]
    recipients = operators()
    if mail_capability.delivery() == "not_configured":
        # An alert by mail with no mail sender would only be one more failed row. It is in the log, and the
        # startup preflight and /ready already say that no mail can be sent.
        logger.error("operator alert %s (%s) not sent: no mail sender configured", code, _one_line(detail))
        return 0
    if not recipients:
        logger.warning("operator alert %s (%s) not sent: PLATFORM_OPERATOR_EMAILS is empty", code, _one_line(detail))
        return 0
    moment = now or datetime.now(UTC)
    seed = hashlib.sha256(f"{code}|{dedupe}".encode()).hexdigest()[:16]
    for address in recipients:
        key = f"operator_alert:{seed}:{_bucket(moment)}:{hashlib.sha256(address.encode()).hexdigest()[:12]}"
        await outbox_immediate.enqueue_operator_alert(
            db, key=key, email=address, subject=subject, body=f"{text}\n\n{_one_line(detail)}\n"
        )
    return len(recipients)


async def alert_in_own_session(code: str, *, dedupe: str = "", detail: str = "") -> None:
    """For callers with no session of their own (a failed job). Best effort: never raises."""
    try:
        from app.database import engine, get_session_factory
        from app.services import outbox

        async with get_session_factory(engine())() as db:
            await raise_alert(db, code, dedupe=dedupe, detail=detail)
            await db.commit()
        outbox.kick()
    except Exception as exc:  # an alert must never turn a failure into a second one
        logger.error("operator alert %s could not be written: %s", code, type(exc).__name__)
