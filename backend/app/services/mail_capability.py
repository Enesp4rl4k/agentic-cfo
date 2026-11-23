"""What the outbox can actually do with an e-mail right now, said plainly to the person who asked for one.

Every mail-dependent flow (verification, password reset, invitation) writes an outbox row and answers
"check your e-mail". That sentence is false when nothing can be sent. The state is a fact about the
deployment, not about the address, so it may be shown to anyone without telling them which accounts exist.

* `live`           a real SMTP sender is configured; the mail leaves the process.
* `dev_recorded`   development or tests: the sender is a recorded no-op, nothing leaves the process.
* `not_configured` production mode with no SMTP credentials: the mail would end as a failed outbox row.
                   Startup refuses this combination when a flow needs mail (core/preflight.py), so it is
                   only reachable by something unusual; the flows still refuse to pretend.
"""

from __future__ import annotations

from typing import Any, Literal

from app.config import get_settings

MailDelivery = Literal["live", "dev_recorded", "not_configured"]

DEV_NOTICE = (
    "Geliştirme modu: e-posta gönderilmedi, yalnızca kaydedildi (OUTBOX_TRANSPORT / SMTP ayarı yok). "
    "Development mode: the e-mail was recorded, not sent."
)
NOT_CONFIGURED_NOTICE = (
    "E-posta gönderimi yapılandırılmamış; e-posta iletilemez. "
    "Mail sending is not configured; no e-mail can be delivered."
)
INVITE_NOT_SENT = "E-posta gönderimi yapılandırılmamış; davet iletilemedi. Davet oluşturulmadı."


def delivery() -> MailDelivery:
    from app.services import outbox

    if not outbox.live():
        return "dev_recorded"
    settings = get_settings()
    return "live" if settings.smtp_user and settings.smtp_password else "not_configured"


def notice(state: MailDelivery | None = None) -> str | None:
    state = state or delivery()
    return {"live": None, "dev_recorded": DEV_NOTICE, "not_configured": NOT_CONFIGURED_NOTICE}[state]


def fields() -> dict[str, Any]:
    """The two keys every mail-dependent answer carries (identical for every caller)."""
    state = delivery()
    return {"mail_delivery": state, "mail_notice": notice(state)}
