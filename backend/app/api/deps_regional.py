"""FastAPI dependency: require Turkey regional pack."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.regional.packs import org_has_tr_pack


async def require_tr_pack(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    org = getattr(current_user, "organization", None)
    if org is None and current_user.org_id:
        from app.models.organization import Organization

        org = await db.get(Organization, str(current_user.org_id))
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization required.",
        )
    if not org_has_tr_pack(org):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turkey regional pack is not enabled for this organization.",
        )
    return current_user
