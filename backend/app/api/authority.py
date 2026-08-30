"""Yetki Matrisi API — the org's Delegation-of-Authority policy.

    GET  /authority/policy            — active policy (or the engine default)
    PUT  /authority/policy            — replace rules → new version, activates it (owner/admin)
    POST /authority/evaluate          — dry-run a request against the active policy
    GET  /authority/policy/versions   — version history (audit trail)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.authority_policy import AuthorityPolicy
from app.models.user import User
from app.platform.authority_matrix import (
    DEFAULT_POLICY_RULES,
    AuthorityRequest,
    evaluate,
    load_active_rules,
    validate_rules,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _org_id(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    return str(user.org_id)


class PolicyPut(BaseModel):
    rules: list[dict[str, Any]]
    note: str | None = None


class EvaluateBody(BaseModel):
    domain: str = "journal_entry"
    amount_kurus: int = 0
    category: str | None = None
    counterparty: str | None = None
    is_related_party: bool = False
    is_fixed_asset: bool = False
    confidence: float | None = None
    classification_method: str | None = None
    requested_by_role: str | None = None


@router.get("/authority/policy")
async def get_policy(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    row = (
        await db.execute(
            select(AuthorityPolicy)
            .where(AuthorityPolicy.org_id == org_id, AuthorityPolicy.active.is_(True))
            .order_by(AuthorityPolicy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {
            "data": {"is_default": True, "version": 0, "rules": DEFAULT_POLICY_RULES},
            "error": None,
        }
    return {
        "data": {
            "is_default": False,
            "id": row.id,
            "version": row.version,
            "rules": row.rules,
            "note": row.note,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
        "error": None,
    }


@router.put("/authority/policy")
async def put_policy(
    body: PolicyPut,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403, detail="Yetki matrisini yalnızca sahip/yönetici değiştirebilir."
        )
    org_id = _org_id(current_user)
    errors = validate_rules(body.rules)
    if errors:
        raise HTTPException(status_code=422, detail={"policy_errors": errors})

    current = (
        await db.execute(
            select(AuthorityPolicy)
            .where(AuthorityPolicy.org_id == org_id)
            .order_by(AuthorityPolicy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_version = (current.version + 1) if current else 1

    # Deactivate all prior versions for this org.
    for row in (
        await db.execute(
            select(AuthorityPolicy).where(
                AuthorityPolicy.org_id == org_id, AuthorityPolicy.active.is_(True)
            )
        )
    ).scalars():
        row.active = False

    policy = AuthorityPolicy(
        org_id=org_id,
        version=next_version,
        active=True,
        rules=body.rules,
        note=body.note,
        created_by_user_id=str(current_user.id),
    )
    db.add(policy)
    await db.commit()
    logger.info("Authority policy v%d activated for org=%s", next_version, org_id)
    return {"data": {"id": policy.id, "version": next_version, "active": True}, "error": None}


@router.post("/authority/evaluate")
async def evaluate_request(
    body: EvaluateBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rules = await load_active_rules(_org_id(current_user), db)
    decision = evaluate(rules, AuthorityRequest(**body.model_dump()))
    return {"data": decision.to_dict(), "error": None}


@router.get("/authority/policy/versions")
async def list_versions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    rows = (
        await db.execute(
            select(AuthorityPolicy)
            .where(AuthorityPolicy.org_id == org_id)
            .order_by(AuthorityPolicy.version.desc())
        )
    ).scalars().all()
    return {
        "data": {
            "versions": [
                {
                    "id": r.id, "version": r.version, "active": r.active,
                    "note": r.note, "rule_count": len(r.rules or []),
                    "created_by": r.created_by_user_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        },
        "error": None,
    }
