"""C-Suite Ledger Intelligence API endpoints.

Derives executive metrics directly from the company ledger without requiring
separate or duplicate CSV uploads:
- GET /api/v1/csuite/chro: Workforce compensation & revenue ratio trend
- GET /api/v1/csuite/coo:  Supplier concentration (Pareto / 80-20 risk)
- GET /api/v1/csuite/cto:  SaaS and cloud infrastructure spending trend
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.csuite_ledger import (
    compute_chro_metrics,
    compute_coo_metrics,
    compute_cto_metrics,
)

router = APIRouter()


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Kullanıcının organizasyonu yok.")
    return str(user.org_id)


def _parse_anchor(anchor_str: str | None) -> date | None:
    if not anchor_str:
        return None
    try:
        return date.fromisoformat(anchor_str)
    except ValueError:
        raise HTTPException(400, "Geçersiz tarih biçimi (YYYY-AA-GG bekleniyor).") from None


@router.get(
    "/csuite/chro",
    summary="CHRO defter bazlı personel/ciro analizi",
    responses={400: {"description": "Kullanıcının organizasyonu yok."}},
)
async def get_chro_metrics(
    months: int = Query(default=6, ge=1, le=36, description="Analiz edilecek geçmiş ay sayısı"),
    anchor_date: str | None = Query(default=None, description="Referans tarihi (YYYY-AA-GG)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Calculate personnel expense ratio and monthly trend from the company ledger."""
    org_id = _org(user)
    parsed = _parse_anchor(anchor_date)
    metrics = await compute_chro_metrics(db, org_id, months=months, anchor_date=parsed)
    return {"data": metrics.to_dict(), "error": None}


@router.get(
    "/csuite/coo",
    summary="COO defter bazlı tedarikçi yoğunlaşma riski",
    responses={400: {"description": "Kullanıcının organizasyonu yok."}},
)
async def get_coo_metrics(
    days: int = Query(default=90, ge=7, le=365, description="Analiz edilecek geçmiş gün sayısı"),
    anchor_date: str | None = Query(default=None, description="Referans tarihi (YYYY-AA-GG)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Calculate Pareto supplier concentration and operational dependency risk."""
    org_id = _org(user)
    parsed = _parse_anchor(anchor_date)
    metrics = await compute_coo_metrics(db, org_id, days=days, anchor_date=parsed)
    return {"data": metrics.to_dict(), "error": None}


@router.get(
    "/csuite/cto",
    summary="CTO defter bazlı bulut ve yazılım harcama analizi",
    responses={400: {"description": "Kullanıcının organizasyonu yok."}},
)
async def get_cto_metrics(
    months: int = Query(default=6, ge=1, le=36, description="Analiz edilecek geçmiş ay sayısı"),
    anchor_date: str | None = Query(default=None, description="Referans tarihi (YYYY-AA-GG)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Calculate cloud infrastructure and SaaS subscription spend from the company ledger."""
    org_id = _org(user)
    parsed = _parse_anchor(anchor_date)
    metrics = await compute_cto_metrics(db, org_id, months=months, anchor_date=parsed)
    return {"data": metrics.to_dict(), "error": None}
