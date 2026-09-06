"""İlişkili taraf sicili — related-party register.

    GET    /related-parties            — sicili listele
    POST   /related-parties            — kayıt ekle
    PATCH  /related-parties/{id}       — güncelle / pasifleştir
    DELETE /related-parties/{id}       — pasifleştir (silmez)
    GET    /related-parties/suggestions — geçmiş işlemlerden aday karşı taraflar
    POST   /related-parties/check      — bir karşı tarafı sicille dene

Editing the register is an owner/admin action: it decides which transactions get
escalated to the owner for disclosure, so an analyst must not be able to quietly
remove a party and let the entries through.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.related_party import RELATIONSHIP_TYPES, RelatedParty
from app.models.transaction import Transaction
from app.models.user import User
from app.services.related_party import (
    group_counterparties,
    load_active_parties,
    match_transaction,
    normalize_name,
    normalize_tax_id,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _org_id(user: User) -> str:
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Henüz bir organizasyona üye değilsiniz.",
        )
    return str(user.org_id)


def _require_manager(user: User) -> str:
    org_id = _org_id(user)
    if user.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="İlişkili taraf sicilini yalnızca sahip/yönetici düzenleyebilir.",
        )
    return org_id


class PartyIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    relationship_type: str = "diger"
    tax_id: str | None = None
    note: str | None = None


class PartyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=300)
    relationship_type: str | None = None
    tax_id: str | None = None
    note: str | None = None
    active: bool | None = None


class CheckIn(BaseModel):
    """A counterparty as it would appear on a statement line."""
    vendor: str | None = None
    description: str | None = None
    tax_id: str | None = None


def _validate_relationship(value: str) -> str:
    if value not in RELATIONSHIP_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Geçersiz ilişki türü. Seçenekler: {', '.join(RELATIONSHIP_TYPES)}",
        )
    return value


@router.get("/related-parties")
async def list_parties(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    stmt = select(RelatedParty).where(RelatedParty.org_id == org_id)
    if not include_inactive:
        stmt = stmt.where(RelatedParty.active.is_(True))
    rows = (await db.execute(stmt.order_by(RelatedParty.name))).scalars().all()
    return {
        "data": {
            "parties": [r.to_dict() for r in rows],
            "count": len(rows),
            "relationship_types": list(RELATIONSHIP_TYPES),
        },
        "error": None,
    }


@router.post("/related-parties", status_code=status.HTTP_201_CREATED)
async def create_party(
    body: PartyIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_manager(current_user)
    _validate_relationship(body.relationship_type)

    normalized = normalize_name(body.name)
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="Ad, şirket eki çıkarıldığında boş kalıyor — ayırt edici bir ad girin.",
        )

    existing = (
        await db.execute(
            select(RelatedParty).where(
                RelatedParty.org_id == org_id,
                RelatedParty.normalized_name == normalized,
                RelatedParty.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Bu taraf zaten sicilde: {existing.name}",
        )

    party = RelatedParty(
        org_id=org_id,
        name=body.name.strip(),
        normalized_name=normalized,
        relationship_type=body.relationship_type,
        tax_id=normalize_tax_id(body.tax_id) or None,
        note=body.note,
        created_by=str(current_user.id),
    )
    db.add(party)
    await db.commit()
    await db.refresh(party)
    logger.info("İlişkili taraf eklendi: org=%s name=%s", org_id, party.name)
    return {"data": party.to_dict(), "error": None}


@router.patch("/related-parties/{party_id}")
async def update_party(
    party_id: str,
    body: PartyPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_manager(current_user)
    party = await db.get(RelatedParty, party_id)
    if party is None or party.org_id != org_id:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")

    if body.name is not None:
        normalized = normalize_name(body.name)
        if not normalized:
            raise HTTPException(status_code=422, detail="Ayırt edici bir ad girin.")
        party.name = body.name.strip()
        party.normalized_name = normalized
    if body.relationship_type is not None:
        party.relationship_type = _validate_relationship(body.relationship_type)
    if body.tax_id is not None:
        party.tax_id = normalize_tax_id(body.tax_id) or None
    if body.note is not None:
        party.note = body.note
    if body.active is not None:
        party.active = body.active
    party.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(party)
    return {"data": party.to_dict(), "error": None}


@router.delete("/related-parties/{party_id}")
async def deactivate_party(
    party_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Deactivate rather than delete.

    A party that was related during a period whose packet is already sealed must
    stay explainable: an auditor asking why an entry was escalated needs the row
    that caused it to still exist.
    """
    org_id = _require_manager(current_user)
    party = await db.get(RelatedParty, party_id)
    if party is None or party.org_id != org_id:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    party.active = False
    party.updated_at = datetime.now(UTC)
    await db.commit()
    return {"data": {"id": party_id, "active": False}, "error": None}


@router.get("/related-parties/suggestions")
async def suggest_counterparties(
    limit: int = 25,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Recurring counterparties from past transactions, not yet in the register.

    An empty register flags nothing, so the feature is dead until somebody fills
    it — and nobody sits down to list their own related parties from memory.
    This turns it around: here are the counterparties you actually pay, ranked
    by how often and how much, tell us which ones you are connected to.

    Recurrence is the signal. A one-off supplier is noise; rent paid to the same
    name every month for a year is exactly the shape of the transaction this
    register exists to surface.
    """
    org_id = _org_id(current_user)

    rows = (
        await db.execute(
            select(
                Transaction.vendor,
                func.count().label("tx_count"),
                func.sum(func.abs(Transaction.amount_kurus)).label("total_kurus"),
            )
            .join(AnalysisJob, Transaction.job_id == AnalysisJob.id)
            .where(
                AnalysisJob.org_id == org_id,
                Transaction.vendor.is_not(None),
                Transaction.vendor != "",
            )
            .group_by(Transaction.vendor)
            .order_by(func.count().desc())
        )
    ).all()

    known = {p.normalized_name for p in await load_active_parties(org_id, db)}
    suggestions = group_counterparties(
        [(v, int(c or 0), int(t or 0)) for v, c, t in rows], known, limit=limit
    )

    return {
        "data": {
            "suggestions": suggestions,
            "count": len(suggestions),
            "registry_size": len(known),
        },
        "error": None,
    }


@router.post("/related-parties/check")
async def check_counterparty(
    body: CheckIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Would this counterparty be flagged? Shows what the match keyed on.

    Lets someone see the register's behaviour on a real statement line before an
    analysis run does it silently.
    """
    org_id = _org_id(current_user)
    parties = await load_active_parties(org_id, db)
    match = match_transaction(body.model_dump(), parties)
    return {
        "data": {
            "is_related_party": match is not None,
            "match": match.to_dict() if match else None,
            "registry_size": len(parties),
        },
        "error": None,
    }
