"""Consolidated Group & Intercompany Cash Radar API (Plan v12 Faz 4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.consolidation_engine import compute_consolidated_cash_radar

router = APIRouter(prefix="/consolidation", tags=["consolidation"])


class ConsolidatedRadarRequest(BaseModel):
    org_ids: list[str] = Field(default_factory=list)
    group_name: str = "Konsolide Grup"


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


@router.post("/radar")
async def get_consolidated_radar(
    body: ConsolidatedRadarRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Compute 13-week consolidated cash radar across requested member organizations with intercompany elimination."""
    user_org = _org(user)
    target_org_ids = list(body.org_ids)
    if not target_org_ids:
        target_org_ids = [user_org]
    elif user_org not in target_org_ids:
        target_org_ids.append(user_org)

    radar = await compute_consolidated_cash_radar(
        db,
        org_ids=target_org_ids,
        group_name=body.group_name,
    )
    return {"data": radar.to_dict(), "error": None}
