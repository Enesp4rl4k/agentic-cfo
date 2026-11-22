"""The immediate class: outbox messages that need no human release.

A business message (a briefing, an alert) leaves only under a standing preference or after a
person's release. A few messages are different: the person asked for them a moment ago and
they hold no business data — an invitation, a password-reset link, a test of a connection the
person just configured, a reply to a signed inbound chat message. Those go out at once, but
only through this module, so the class cannot become a way to send business data unreleased:

- the allowlist `IMMEDIATE_KINDS` names every template kind; a kind not in it cannot be
  written (`ImmediateKindRefused`), and the sender re-checks it on every delivery;
- a caller never supplies text. Each `enqueue_*` below takes the few facts its template
  needs (a link, an organisation name, a role) and renders the subject and body itself, on
  one line where a header is concerned;
- the recipient rule is per kind: the invitee or the account holder; an address or destination
  the organisation already has (connection test); the person who wrote to the bot (reply).

A reply that would carry company figures is not a `bot_reply`: it must be a released message.

Kinds that carry a one-time link are scrubbed from the row once delivered (`scrub`).
E-mail verification (`email_verification`) is one of them: the address is the recipient.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbound
from app.core.email_address import normalize_email
from app.models.outbox_message import IMMEDIATE, OutboxMessage
from app.services import outbox

# Organisation id of a message that belongs to no organisation (a password reset for a person
# without one; a bot reply). No organisation's delivery list shows it.
SYSTEM_ORG = "system"


class ImmediateKindRefused(ValueError):
    """The kind, channel or recipient is not one the immediate class allows."""


@dataclass(frozen=True)
class Kind:
    channels: frozenset[str]
    scrub: bool


IMMEDIATE_KINDS: dict[str, Kind] = {
    "org_invite": Kind(frozenset({"email"}), scrub=True),
    "password_reset": Kind(frozenset({"email"}), scrub=True),
    "email_verification": Kind(frozenset({"email"}), scrub=True),
    # Sent to an address that tried to register while it already has an account: no token, only the
    # sign-in and reset pages, so there is nothing to scrub.
    "account_exists": Kind(frozenset({"email"}), scrub=False),
    "connection_test": Kind(frozenset({"email", "slack", "webhook"}), scrub=False),
    "bot_reply": Kind(frozenset({"whatsapp", "slack_bot"}), scrub=False),
}


def kind_allows(kind: str | None, channel: str) -> bool:
    spec = IMMEDIATE_KINDS.get(kind or "")
    return spec is not None and channel in spec.channels


def kind_scrubs(kind: str | None) -> bool:
    spec = IMMEDIATE_KINDS.get(kind or "")
    return spec is not None and spec.scrub


def _line(value: str, limit: int = 120) -> str:
    """One line of text: a name that reaches a subject or a sentence cannot carry a newline."""
    return " ".join(value.split())[:limit]


async def _write(
    db: AsyncSession, *, kind: str, key: str, org_id: str, channel: str, recipient: str,
    subject: str, body: str, source_ref: str,
) -> OutboxMessage:
    if not kind_allows(kind, channel):
        raise ImmediateKindRefused(f"{kind!r} may not be sent by {channel!r}")
    return await outbox.enqueue(
        db, key=key, org_id=org_id, channel=channel, recipient=recipient, subject=subject,
        body=body, source=kind, source_ref=source_ref, delivery_class=IMMEDIATE, kind=kind,
    )


async def enqueue_org_invite(
    db: AsyncSession, *, invite_id: str, org_id: str, email: str, org_name: str, role: str,
    accept_url: str, expires_at: datetime,
) -> OutboxMessage:
    """The invitation e-mail, to the address invited."""
    name = _line(org_name)
    body = (
        f"Sizi {name} şirketine {_line(role, 20)} olarak davet ettiler.\n"
        f"You have been invited to join {name} as {_line(role, 20)}.\n\n"
        f"Davete katılın / Accept: {accept_url}\n\n"
        f"Bağlantı {expires_at.date().isoformat()} tarihine kadar geçerlidir. "
        f"This invitation expires on {expires_at.date().isoformat()}."
    )
    return await _write(
        db, kind="org_invite", key=f"org_invite:{invite_id}", org_id=org_id, channel="email",
        recipient=normalize_email(email), subject=f"Davet / Invitation: {name}", body=body,
        source_ref=invite_id,
    )


async def enqueue_password_reset(
    db: AsyncSession, *, token_id: str, org_id: str | None, email: str, reset_url: str,
    expires_minutes: int,
) -> OutboxMessage:
    """The reset link, to the address of the account."""
    body = (
        "Şifrenizi sıfırlamak için bir istek aldık. Bağlantı "
        f"{expires_minutes} dakika geçerlidir ve yalnızca bir kez kullanılabilir.\n"
        f"We received a request to reset your password. The link is valid for {expires_minutes} "
        "minutes and works once.\n\n"
        f"{reset_url}\n\n"
        "Bu isteği siz yapmadıysanız bu e-postayı yok sayın; şifreniz değişmez. "
        "If you did not ask for this, ignore this e-mail: your password stays as it is."
    )
    return await _write(
        db, kind="password_reset", key=f"password_reset:{token_id}", org_id=org_id or SYSTEM_ORG,
        channel="email", recipient=normalize_email(email),
        subject="Şifre sıfırlama / Password reset", body=body, source_ref=token_id,
    )


async def enqueue_email_verification(
    db: AsyncSession, *, token_id: str, org_id: str | None, email: str, verify_url: str,
    expires_hours: int,
) -> OutboxMessage:
    """The verification link, to the address being verified."""
    body = (
        "Hesabınızı etkinleştirmek için e-posta adresinizi doğrulayın. Bağlantı "
        f"{expires_hours} saat geçerlidir ve yalnızca bir kez kullanılabilir.\n"
        f"Verify your e-mail address to activate your account. The link is valid for {expires_hours} "
        "hours and works once.\n\n"
        f"{verify_url}\n\n"
        "Bu hesabı siz açmadıysanız bu e-postayı yok sayın. "
        "If you did not create this account, ignore this e-mail."
    )
    return await _write(
        db, kind="email_verification", key=f"email_verification:{token_id}",
        org_id=org_id or SYSTEM_ORG, channel="email", recipient=normalize_email(email),
        subject="E-posta doğrulama / Verify your e-mail", body=body, source_ref=token_id,
    )


async def enqueue_account_exists(
    db: AsyncSession, *, user_id: str, org_id: str | None, email: str, login_url: str, reset_url: str,
) -> OutboxMessage:
    """The "you already have an account" mail, to the address that someone tried to register again.

    Replaces the "already registered" error of /auth/register, so the page itself cannot tell a
    stranger which addresses exist. Contains no token: the reset page proves the mailbox itself."""
    body = (
        "Bu e-posta adresiyle zaten bir hesabınız var, bu yüzden yeni bir hesap açılmadı.\n"
        "An account already exists for this e-mail address, so a new one was not created.\n\n"
        f"Giriş / Sign in: {login_url}\n"
        f"Şifrenizi mi unuttunuz? / Forgot your password? {reset_url}\n\n"
        "Bu isteği siz yapmadıysanız bu e-postayı yok sayın; hesabınızda hiçbir şey değişmedi. "
        "If this was not you, ignore this e-mail: nothing changed on your account."
    )
    return await _write(
        db, kind="account_exists", key=f"account_exists:{user_id}:{uuid.uuid4().hex}",
        org_id=org_id or SYSTEM_ORG, channel="email", recipient=normalize_email(email),
        subject="Hesabınız zaten var / You already have an account", body=body, source_ref=user_id,
    )


async def mailed_recently(db: AsyncSession, *, kind: str, email: str, minutes: int) -> bool:
    """Whether this kind of mail went (or is queued) to this address inside the cool-down."""
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    found = (
        await db.execute(
            select(OutboxMessage.id)
            .where(
                OutboxMessage.kind == kind,
                OutboxMessage.recipient == normalize_email(email),
                OutboxMessage.created_at > since,
            )
            .limit(1)
        )
    ).first()
    return found is not None


_TEST_TEXT = "Bağlantı testi: bu mesajı görüyorsanız bağlantınız çalışıyor. / Connection test: this message arrived."


async def enqueue_connection_test(
    db: AsyncSession, *, test_id: str, org_id: str, channel: str, destination: str,
) -> OutboxMessage:
    """A fixed test message to a destination the person just configured.

    An e-mail goes only to someone the organisation may be mailed (a member or a listed
    recipient); a Slack or webhook URL must pass the same check the sender applies."""
    if channel == "email":
        if normalize_email(destination) not in await outbox.allowed_email_recipients(db, org_id):
            raise ImmediateKindRefused("recipient_not_allowed")
        recipient, body = normalize_email(destination), _TEST_TEXT
    else:
        problem = await outbound.destination_problem(destination)
        if problem:
            raise ImmediateKindRefused(problem)
        recipient = outbox.destination_host(destination)
        if channel == "slack":
            body = json.dumps({"url": destination, "title": "Bağlantı testi", "message": _TEST_TEXT,
                               "severity": "info"})
        else:
            body = json.dumps({"url": destination, "event_type": "connection_test", "data": {"text": _TEST_TEXT}})
    return await _write(
        db, kind="connection_test", key=f"connection_test:{test_id}", org_id=org_id, channel=channel,
        recipient=recipient, subject="Bağlantı testi / Connection test", body=body, source_ref=test_id,
    )


async def enqueue_bot_reply(
    db: AsyncSession, *, reply_id: str, channel: str, recipient: str, text: str,
    blocks: list[dict[str, object]] | None = None,
) -> OutboxMessage:
    """The bot's reply to the person who wrote to it (their number, or their Slack channel).

    The text is the gateway's answer to a message with no company context; an answer that
    carries company figures must be a released message instead."""
    if channel == "slack_bot":
        body = json.dumps({"channel": recipient, "text": text[:3000], "blocks": blocks or []})
    else:
        body = text[:3000]
    return await _write(
        db, kind="bot_reply", key=f"bot_reply:{reply_id}", org_id=SYSTEM_ORG, channel=channel,
        recipient=recipient[:255], subject="Bot reply", body=body, source_ref=reply_id,
    )
