"""Who is on the other end of a WebSocket.

A browser cannot set an Authorization header on a WebSocket, so the access
token arrives as `?token=`. Both WebSocket routes used to treat it as optional:
`/ws/alerts/{org_id}` let a caller with no token subscribe to any
organisation's live alerts, and `/ws/chat` took no token at all and built its
prompt from whatever `job_id` / `org_id` the client named. The route walk in
`tests/test_route_access.py` only looked at HTTP routes, so neither showed up.

The rules here are the HTTP ones from `api/auth.get_current_user`: an *access*
token (not a refresh token), a user that exists and is active.
"""
from __future__ import annotations

from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import session_factory
from app.models.user import User
from app.services import email_verification
from app.services.auth import decode_token, token_is_current

# RFC 6455 "policy violation": the server will not talk to this client.
REFUSED = 1008


async def user_for_token(db: AsyncSession, token: str | None) -> User | None:
    """The active user an access token names, or None."""
    if not token:
        return None
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = await db.get(User, str(user_id))
    if (
        user is None or not user.is_active or not token_is_current(payload, user.token_version)
        or not email_verification.is_verified(user)
    ):
        return None
    return user


async def still_acting_in(user_id: str, org_id: str) -> bool:
    """Whether `user_id` is still active, still acting in `org_id` and still a member of it.

    A socket authenticates once, at connect. Leaving the company (removal) or
    switching to another must end the live feed, so long-lived sockets ask again.
    """
    from sqlalchemy import select

    from app.models.organization import OrgMembership

    async with session_factory()() as db:
        user = await db.get(User, str(user_id))
        if user is None or not user.is_active or not user.org_id or str(user.org_id) != str(org_id):
            return False
        has_row = (
            await db.execute(
                select(OrgMembership.id).where(
                    OrgMembership.user_id == str(user_id), OrgMembership.org_id == str(org_id)
                )
            )
        ).first()
        has_any = (await db.execute(select(OrgMembership.id).where(OrgMembership.user_id == str(user_id)))).first()
        # A user with no membership rows at all is a pre-membership account: their column is all there is.
        return has_row is not None or has_any is None


async def websocket_caller(token: str | None) -> User | None:
    """`user_for_token` on a short-lived session.

    Not a `Depends(get_db)`: a dependency's session would stay open for as long
    as the socket does, holding a pooled connection per idle browser tab.
    """
    if not token:
        return None
    async with session_factory()() as db:
        user = await user_for_token(db, token)
        if user is not None:
            db.expunge(user)
        return user
