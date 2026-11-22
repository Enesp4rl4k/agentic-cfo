"""E-mail verification: prove the holder of an address before the account may act.

`issue` mints a token (stored as a SHA-256 digest, expiring) and queues the link as an
immediate-class outbox row. `verify` claims the token with one conditional UPDATE (single use)
and sets `users.email_verified_at`. `resend` is for the person who lost the mail: it does the same
work whatever the address, and the caller answers every address identically.

An address is also proved by accepting an invitation e-mailed to it and by a sign-in provider that
verified it: `mark_verified` is what those call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.email_address import normalize_email
from app.models.audit_log import AuditLog
from app.models.email_verification import EmailVerificationToken
from app.models.user import User
from app.services import outbox_immediate
from app.services.secret_tokens import claim_token, hash_token, new_token

logger = logging.getLogger(__name__)

VerifyOutcome = Literal["ok", "invalid", "expired", "used"]


def required() -> bool:
    return get_settings().email_verification_required


def is_verified(user: User) -> bool:
    """Whether this account may sign in and act."""
    return user.email_verified_at is not None or not required()


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def issue(db: AsyncSession, user: User) -> None:
    """Queue a verification link for `user` (the caller commits)."""
    settings = get_settings()
    raw, digest = new_token()
    token = EmailVerificationToken(
        user_id=user.id, token_hash=digest,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.email_verification_expire_hours),
    )
    db.add(token)
    await db.flush()
    # A fragment is never sent to a server (ours or a proxy's).
    link = f"{settings.frontend_url.rstrip('/')}/auth/verify-email#token={raw}"
    await outbox_immediate.enqueue_email_verification(
        db, token_id=str(token.id), org_id=str(user.org_id) if user.org_id else None, email=user.email,
        verify_url=link, expires_hours=settings.email_verification_expire_hours,
    )


async def mark_verified(db: AsyncSession, user_id: str) -> None:
    """The address is proved by another act (an invitation sent to it, a provider): close open tokens too."""
    now = datetime.now(UTC)
    await db.execute(
        update(User).where(User.id == user_id, User.email_verified_at.is_(None)).values(email_verified_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user_id, EmailVerificationToken.used_at.is_(None))
        .values(used_at=now).execution_options(synchronize_session=False)
    )


async def resend(db: AsyncSession, *, email: str, ip: str | None, rate_limited: bool) -> str:
    """Queue a new link if the address belongs to an active, unverified password account.

    Returns the outcome word (it goes to the audit row only; the caller answers every address alike)."""
    user = (await db.execute(select(User).where(User.email == normalize_email(email)))).scalar_one_or_none()
    outcome = "sent"
    if rate_limited:
        outcome = "rate_limited"
    elif user is None:
        outcome = "unknown_account"
    elif not user.is_active:
        outcome = "inactive"
    elif user.email_verified_at is not None:
        outcome = "already_verified"
    elif not user.hashed_password:
        outcome = "sso_only"
    if outcome == "sent" and user is not None:
        await issue(db, user)
    db.add(AuditLog(
        user_id=user.id if outcome == "sent" and user is not None else None,
        action="auth.email_verification_requested", resource="/api/v1/auth/email-verification",
        request_body={"outcome": outcome}, ip_address=ip,
    ))
    await db.commit()
    return outcome


async def verify(db: AsyncSession, *, token: str, ip: str | None) -> VerifyOutcome:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if row is None:
        return "invalid"
    if row.used_at is not None:
        return "used"
    if _utc(row.expires_at) <= now:
        return "expired"
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        return "invalid"
    if not await claim_token(db, EmailVerificationToken, row.id, now):
        await db.rollback()
        return "used"
    await mark_verified(db, user.id)
    db.add(AuditLog(
        user_id=user.id, action="auth.email_verified", resource="/api/v1/auth/email-verification",
        request_body={"outcome": "ok"}, ip_address=ip,
    ))
    await db.commit()
    return "ok"
