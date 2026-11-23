"""The pilot invitation: how the first owner of a brand-new company gets in.

The one supported flow, end to end:

1. a platform operator (`PLATFORM_OPERATOR_EMAILS`) issues an invite for an e-mail address and a company
   name (`POST /pilot/invite/generate`, or `scripts/issue_pilot_invite.py` on the host for the very first
   operator account). A random token is e-mailed to that address through the outbox; only its SHA-256 digest
   is stored, so the operator never sees it and a database copy does not hold a usable link.
2. the invitee opens `/auth/pilot-invite?token=...` and chooses a name and a password
   (`POST /auth/register` with `invite_token`). The address is the one the invite names: the token was
   e-mailed there, so holding it proves the mailbox and no verification mail is needed.
3. in one transaction the invite is claimed (a conditional UPDATE: of two simultaneous requests one wins),
   the account is created as owner of a NEW organisation named after the invite, and the membership and a
   decision record are written.
4. the owner invites the team from the workspace screen (`POST /org/invite`, the existing flow).

Nothing else creates a company in `invite_only` and `closed` modes (`POST /org/create` is refused for
everyone but operators), so every company in the system is one an operator invited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.email_address import normalize_email
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.pilot import PilotInvite
from app.models.user import User, UserRole
from app.services import mail_capability, outbox_immediate
from app.services.decisions import record_decision
from app.services.org_membership import ensure_membership
from app.services.org_provisioning import create_organisation
from app.services.secret_tokens import hash_token, new_token


class PilotInviteError(Exception):
    """A refusal with the HTTP status and the sentence to show."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def state(invite: PilotInvite | None) -> str:
    """`valid`, `used`, `expired`, or `unknown` (no such invite, revoked, or one from before tokens)."""
    if invite is None or invite.token_hash is None:
        return "unknown"
    if invite.used:
        return "used"
    if invite.expires_at is not None and _utc(invite.expires_at) < datetime.now(UTC):
        return "expired"
    return "valid"


async def find(db: AsyncSession, token: str) -> PilotInvite | None:
    return (
        await db.execute(select(PilotInvite).where(PilotInvite.token_hash == hash_token(token)))
    ).scalar_one_or_none()


async def issue(
    db: AsyncSession, *, operator_id: str, email: str, company_name: str, note: str | None = None,
    expire_days: int | None = None,
) -> PilotInvite:
    """Write the invite and its e-mail (the caller commits). Refuses when no mail can leave.

    An invite whose link nobody can receive is a dead invite: with no mail sender it is not created."""
    if mail_capability.delivery() == "not_configured":
        raise PilotInviteError(503, mail_capability.INVITE_NOT_SENT)
    settings = get_settings()
    address = normalize_email(email)
    # One open invite per address: a new one replaces the old (its link stops working).
    for old in (
        await db.execute(select(PilotInvite).where(PilotInvite.email == normalize_email(email), PilotInvite.used.is_(False)))
    ).scalars().all():
        await db.delete(old)
    raw, digest = new_token()
    expires = datetime.now(UTC) + timedelta(days=expire_days or settings.pilot_invite_expire_days)
    invite = PilotInvite(
        code=f"pi-{uuid.uuid4().hex[:12]}", token_hash=digest, email=address, company_name=company_name.strip(),
        note=note, expires_at=expires, issued_by=operator_id,
    )
    db.add(invite)
    await db.flush()
    await outbox_immediate.enqueue_pilot_invite(
        db, invite_id=str(invite.id), email=address, company_name=invite.company_name or "",
        register_url=f"{settings.frontend_url.rstrip('/')}/auth/pilot-invite?token={raw}", expires_at=expires,
    )
    return invite


async def redeem(
    db: AsyncSession, token: str, *, email: str, hashed_password: str, full_name: str | None
) -> tuple[User, Organization]:
    """Turn a valid invite into an owner and a new company (the caller commits).

    Raises `PilotInviteError`; every refusal of an invalid, used, expired or mismatching token is the same
    400 sentence, so the endpoint cannot be used to probe invites."""
    from app.services import registration

    invite = await find(db, token)
    generic = PilotInviteError(400, "Geçersiz veya süresi dolmuş davet bağlantısı.")
    if state(invite) != "valid" or invite is None:
        raise generic
    if registration.mode() == "closed":
        raise PilotInviteError(403, registration.refusal_message())
    address = normalize_email(email)
    if normalize_email(invite.email or "") != address:
        raise generic
    if (await db.execute(select(User.id).where(User.email == normalize_email(email)))).first() is not None:
        raise PilotInviteError(
            409, "Bu adres için zaten bir hesap var; giriş yapın. Şirket için platform yöneticisine başvurun."
        )
    now = datetime.now(UTC)
    claimed = cast(
        CursorResult[Any],
        await db.execute(
            update(PilotInvite).where(PilotInvite.id == invite.id, PilotInvite.used.is_(False))
            .values(used=True, used_at=now).execution_options(synchronize_session=False)
        ),
    )
    if claimed.rowcount != 1:
        raise PilotInviteError(400, "Bu davet daha önce kullanılmış.")
    org = await create_organisation(db, name=invite.company_name or address.split("@")[0])
    user = User(
        email=address, hashed_password=hashed_password, full_name=full_name, role=UserRole.OWNER,
        org_id=org.id, email_verified_at=now,  # the invite was e-mailed to this address
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        raise PilotInviteError(409, "Bu adres için bir hesap az önce oluşturuldu; lütfen yeniden deneyin.") from None
    await db.execute(
        update(PilotInvite).where(PilotInvite.id == invite.id).values(used_by_user_id=str(user.id))
        .execution_options(synchronize_session=False)
    )
    membership = await ensure_membership(db, user_id=str(user.id), org_id=str(org.id), role=UserRole.OWNER.value)
    await record_decision(
        db, org_id=str(org.id), kind=DecisionKind.MEMBER_CHANGE, target_type="org_membership",
        target_id=str(membership.id), outcome="joined", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        evidence_refs=[{"type": "pilot_invite", "id": str(invite.id)}], after={"role": membership.role},
    )
    return user, org
