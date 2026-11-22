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
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ask for a reset link. The answer never depends on the account."""
    settings = get_settings()
    started = time.monotonic()
    address = normalize_email(str(body.email))
    digest = hashlib.sha256(address.encode("utf-8")).hexdigest()[:32]
    allowed = await consume(f"pwreset:{digest}", settings.password_reset_per_email_per_hour, 3600)
    outcome = await request_reset(
        db, email=address, ip=_client_ip(request), user_agent=request.headers.get("User-Agent"),
        rate_limited=not allowed,
    )
    if outcome == "sent":
        outbox.kick()
    remaining = settings.password_reset_response_floor_seconds - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
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
