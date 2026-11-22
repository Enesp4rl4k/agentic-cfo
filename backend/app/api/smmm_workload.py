"""The accountant's workload across the companies they serve.

GET /api/v1/smmm/workload     one row per organisation where the caller holds an `smmm` membership

A person may be the accountant of several small companies and act in one at a time; this is the list
that tells them where something waits (`services/accountant`). It reads memberships, so it answers the
same whichever organisation the caller is acting in, and it contains nothing of an organisation the
caller is not an accountant of. Counts only: opening a company's data still means switching into it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import accountant

router = APIRouter()


@router.get("/smmm/workload")
async def smmm_workload(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return {"data": await accountant.workload(db, str(current_user.id)), "error": None}
