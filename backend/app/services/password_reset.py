"""Password reset: request a link, complete with the token.

Not a business decision, so nothing is written to `decisions`; the audit log records the
request and the completion (never the token or a password).

Request (`request_reset`): for an active account that has a password, one token is minted and
stored as a SHA-256 digest with an expiry, and the e-mail with the link is an immediate-class
outbox row. For any other address (unknown, deactivated, SSO-only) nothing is stored or sent;
the caller answers all of them identically.

Completion (`complete_reset`): the token is claimed by one conditional UPDATE (single use,
decided by the database, like the invitation accept), every other open token of the user is
closed, the password is replaced (same policy and hash as registration) and
`users.token_version` is raised, which ends every access and refresh token issued before.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.email_address import normalize_email
from app.models.audit_log import AuditLog
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services import outbox_immediate
from app.services.auth import hash_password
from app.services.secret_tokens import claim_token, hash_token, new_token

logger = logging.getLogger(__name__)

RequestOutcome = Literal["sent", "unknown_account", "inactive", "sso_only", "rate_limited", "cooldown"]
CompleteOutcome = Literal["ok", "invalid", "expired", "used"]


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _audit(
    db: AsyncSession,
    *,
    action: str,
    outcome: str,
    user: User | None,
    ip: str | None,
    user_agent: str | None,
    details: dict[str, object] | None = None,
) -> None:
    """One audit row: what happened, to whom, never a token or a password."""
    db.add(
        AuditLog(
            user_id=user.id if user is not None else None,
            action=action,
            resource="/api/v1/auth/password-reset",
            request_body={"outcome": outcome, **(details or {})},
            ip_address=ip,
            user_agent=(user_agent or "")[:500] or None,
        )
    )


async def _recently_sent(db: AsyncSession, user_id: str) -> bool:
    """A reset link minted inside the cool-down that can still be used."""
    now = datetime.now(UTC)
    since = now - timedelta(minutes=get_settings().auth_mail_cooldown_minutes)
    found = (
        await db.execute(
            select(PasswordResetToken.id)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.created_at > since,
                PasswordResetToken.expires_at > now,
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def request_reset(
    db: AsyncSession, *, email: str, ip: str | None, user_agent: str | None, rate_limited: bool
) -> RequestOutcome:
    """Mint and queue a reset link for the account at `email`, if it may have one.

    Always does the same database work shape (a lookup, a token digest) whatever the answer;
    the caller adds a response-time floor. `rate_limited` is the caller's per-address verdict:
    the request is then recorded and nothing is sent."""
    settings = get_settings()
    user = (
        await db.execute(select(User).where(User.email == normalize_email(email)))
    ).scalar_one_or_none()
    raw, digest = new_token()  # minted for every request, used or not: the same work

    outcome: RequestOutcome
    if rate_limited:
        outcome = "rate_limited"
    elif user is None:
        outcome = "unknown_account"
    elif not user.is_active:
        outcome = "inactive"
    elif not user.hashed_password:
        outcome = "sso_only"
    elif await _recently_sent(db, user.id):
        outcome = "cooldown"  # the mail already sent is still valid: do not send another
    else:
        outcome = "sent"

    if outcome == "sent" and user is not None:
        expires = datetime.now(UTC) + timedelta(minutes=settings.password_reset_expire_minutes)
        token = PasswordResetToken(user_id=user.id, token_hash=digest, expires_at=expires)
        db.add(token)
        await db.flush()
        # The fragment (#token=) is never sent to a server: not to ours, not to a proxy's log.
        link = f"{settings.frontend_url.rstrip('/')}/auth/reset-password#token={raw}"
        await outbox_immediate.enqueue_password_reset(
            db,
            token_id=str(token.id),
            org_id=str(user.org_id) if user.org_id else None,
            email=user.email,
            reset_url=link,
            expires_minutes=settings.password_reset_expire_minutes,
        )
    _audit(
        db,
        action="auth.password_reset_requested",
        outcome=outcome,
        user=user if outcome == "sent" else None,
        ip=ip,
        user_agent=user_agent,
    )
    await db.commit()
    return outcome


async def complete_reset(
    db: AsyncSession, *, token: str, new_password: str, ip: str | None, user_agent: str | None
) -> CompleteOutcome:
    """Set the new password if `token` is a live, unused reset token of an active account."""
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if row is None:
        return "invalid"
    if row.used_at is not None:
        return "used"
    if _utc(row.expires_at) <= now:
        return "expired"
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active or not user.hashed_password:
        return "invalid"

    # Single use, decided by the database: of two simultaneous completions only the one whose
    # UPDATE closes the token goes on. Nothing else is written before it.
    if not await claim_token(db, PasswordResetToken, row.id, now):
        await db.rollback()
        return "used"
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    # A reset ends every credential tied to this person: sessions (token_version, below) and their
    # personal API key. Org-level credentials (ERP/connector secrets, the org's webhook and Slack
    # URLs, the accountant portal) are not the user's and are untouched; see docs/ops/auth-abuse.md.
    api_keys_revoked = 1 if user.api_key else 0
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            api_key=None,
            hashed_password=hash_password(new_password),
            token_version=User.token_version + 1,
            password_changed_at=now,
            # Reading the reset link proves the mailbox: an address nobody had verified now is.
            email_verified_at=func.coalesce(User.email_verified_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    _audit(
        db,
        action="auth.password_reset_completed",
        outcome="ok",
        user=user,
        ip=ip,
        user_agent=user_agent,
        details={"api_keys_revoked": api_keys_revoked, "sessions_ended": "all", "other_reset_links_closed": True},
    )
    await db.commit()
    logger.info("Password reset completed for user %s", user.id)
    return "ok"
