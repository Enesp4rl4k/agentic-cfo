"""Password reset — POST /auth/forgot-password and POST /auth/reset-password.

Both are public (the person has no session). The flow is in `app.services.password_reset`.

forgot-password answers the same body and status, after at least the same minimum time,
whether or not the account exists, is deactivated or signs in with SSO only; limits apply per IP
(middleware) and per normalised address (here), and exceeding the per-address one is
answered the same way, so the limit cannot be used to probe an address.

reset-password takes the token in the body (never in a URL that logs keep) and answers a state the
page can show: invalid, expired or used.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.email_address import normalize_email
from app.database import get_db
from app.middleware.rate_limit import consume
from app.services import outbox
from app.services.password_reset import complete_reset, request_reset

router = APIRouter()


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=8, max_length=128)
    # The registration policy (api/auth.RegisterRequest): at least 8 characters.
    new_password: str = Field(min_length=8, max_length=200)


_STATE_MESSAGES = {
    "invalid": "Bu sıfırlama bağlantısı geçersiz.",
    "expired": "Bu sıfırlama bağlantısının süresi dolmuş.",
    "used": "Bu sıfırlama bağlantısı daha önce kullanılmış.",
}


def _client_ip(request: Request) -> str | None:
    from app.core.client_ip import UNKNOWN, client_ip

    address = client_ip(request)
    return None if address == UNKNOWN else address


async def address_allowed(scope: str, address: str, ip: str | None) -> bool:
    """Count one request against the hourly limit of this address FROM this IP (both hashed in the key).

    Keyed on the pair so one IP cannot use up the allowance of an address for everyone else; the
    flood of mail itself is stopped by the per-address cool-down (settings.auth_mail_cooldown_minutes)."""
    digest = hashlib.sha256(address.encode("utf-8")).hexdigest()[:32]
    where = hashlib.sha256((ip or "unknown").encode("utf-8")).hexdigest()[:16]
    return await consume(f"{scope}:{digest}:{where}", get_settings().password_reset_per_email_per_hour, 3600)


async def hold_to_floor(started: float) -> None:
    """Every answer takes at least the floor, whether or not the account exists."""
    remaining = get_settings().password_reset_response_floor_seconds - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


@router.post("/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ask for a reset link. The answer never depends on the account."""
    started = time.monotonic()
    address = normalize_email(str(body.email))
    ip = _client_ip(request)
    allowed = await address_allowed("pwreset", address, ip)
    outcome = await request_reset(
        db, email=address, ip=ip, user_agent=request.headers.get("User-Agent"),
        rate_limited=not allowed,
    )
    if outcome == "sent":
        outbox.kick()
    await hold_to_floor(started)
    return {"data": {"accepted": True}, "error": None}


@router.post("/auth/reset-password", response_model=None)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """Set a new password with the e-mailed token; every earlier session ends."""
    outcome = await complete_reset(
        db, token=body.token, new_password=body.new_password, ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    if outcome != "ok":
        return JSONResponse(
            status_code=400,
            content={"data": {"state": outcome}, "error": _STATE_MESSAGES[outcome]},
            headers={"Cache-Control": "no-store"},
        )
    return {"data": {"state": "ok"}, "error": None}
