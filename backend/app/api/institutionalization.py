"""Kurumsallaşma Endeksi API.

    POST /institutionalization/compute  — compute + store a snapshot
    GET  /institutionalization          — latest snapshot (computes one if none)
    GET  /institutionalization/history  — score trend
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.institutionalization_snapshot import InstitutionalizationSnapshot
from app.models.user import User
from app.services.institutionalization import compute_index

router = APIRouter()
logger = logging.getLogger(__name__)


def _org_id(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    return str(user.org_id)


def _row_dict(r: InstitutionalizationSnapshot) -> dict[str, Any]:
    return {
        "id": r.id,
        "overall_score": r.overall_score,
        "grade": r.grade,
        "dimensions": r.dimensions,
        "recommendations": r.recommendations,
        "signals": r.signals,
        "computed_at": r.computed_at.isoformat() if r.computed_at else None,
    }


async def _store(org_id: str, result: dict[str, Any], db: AsyncSession) -> InstitutionalizationSnapshot:
    row = InstitutionalizationSnapshot(
        org_id=org_id,
        overall_score=result["overall_score"],
        grade=result["grade"],
        dimensions=result["dimensions"],
        recommendations=result["recommendations"],
        signals=result["signals"],
        computed_at=datetime.fromisoformat(result["computed_at"]),
    )
    db.add(row)
    await db.commit()
    return row


@router.post("/institutionalization/compute", status_code=201)
async def compute_snapshot(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    result = await compute_index(org_id, db)
    row = await _store(org_id, result, db)
    return {"data": _row_dict(row), "error": None}


@router.get("/institutionalization")
async def get_latest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    row = (
        await db.execute(
            select(InstitutionalizationSnapshot)
            .where(InstitutionalizationSnapshot.org_id == org_id)
            .order_by(desc(InstitutionalizationSnapshot.computed_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        result = await compute_index(org_id, db)
        row = await _store(org_id, result, db)
    return {"data": _row_dict(row), "error": None}


@router.get("/institutionalization/history")
async def get_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(24, ge=1, le=120),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    rows = (
        await db.execute(
            select(InstitutionalizationSnapshot)
            .where(InstitutionalizationSnapshot.org_id == org_id)
            .order_by(desc(InstitutionalizationSnapshot.computed_at))
            .limit(limit)
        )
    ).scalars().all()
    return {
        "data": {
            "points": [
                {"overall_score": r.overall_score, "grade": r.grade,
                 "computed_at": r.computed_at.isoformat() if r.computed_at else None}
                for r in reversed(rows)
            ]
        },
        "error": None,
    }
