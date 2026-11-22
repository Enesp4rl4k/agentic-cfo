"""E-mail verification — POST /auth/verify-email and POST /auth/resend-verification (both public).

resend-verification answers the same body and status, after at least the same minimum time, for any
address; limited per IP (middleware) and per normalised address (here). verify-email takes the token
in the body and answers a state the page can show: invalid, expired or used.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.password_reset import _client_ip, address_allowed, hold_to_floor
from app.core.email_address import normalize_email
from app.database import get_db
from app.services import email_verification, outbox

router = APIRouter()


class ResendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=8, max_length=128)


_STATE_MESSAGES = {
    "invalid": "Bu doğrulama bağlantısı geçersiz.",
    "expired": "Bu doğrulama bağlantısının süresi dolmuş.",
    "used": "Bu doğrulama bağlantısı daha önce kullanılmış.",
}


@router.post("/auth/resend-verification")
async def resend_verification(
    body: ResendRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Ask for the verification link again. The answer never depends on the account."""
    started = time.monotonic()
    address = normalize_email(str(body.email))
    allowed = await address_allowed("emailverify", address)
    outcome = await email_verification.resend(
        db, email=address, ip=_client_ip(request), rate_limited=not allowed
    )
    if outcome == "sent":
        outbox.kick()
    await hold_to_floor(started)
    return {"data": {"accepted": True}, "error": None}


@router.post("/auth/verify-email", response_model=None)
async def verify_email(
    body: VerifyRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any] | JSONResponse:
    """Verify the address with the e-mailed single-use token."""
    outcome = await email_verification.verify(db, token=body.token, ip=_client_ip(request))
    if outcome != "ok":
        return JSONResponse(
            status_code=400,
            content={"data": {"state": outcome}, "error": _STATE_MESSAGES[outcome]},
            headers={"Cache-Control": "no-store"},
        )
    return {"data": {"state": "ok"}, "error": None}
