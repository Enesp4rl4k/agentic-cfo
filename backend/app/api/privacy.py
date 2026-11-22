"""Data and privacy: what personal data the product holds and where it goes.

  GET /privacy/data-map                          any signed-in member: the registry as data
  GET /privacy/operator/breach-scope?keys=a,b    platform operator: companies and categories a breach touches

The registry is `app.services.privacy.registry*`; the same facts render to `docs/kvkk/veri-envanteri-uretilen.md`
(`markdown` below). `data-map` describes the product, not a tenant's rows.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_platform_operator
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.privacy import inventory_doc
from app.services.privacy.breach_scope import scope
from app.services.privacy.registry import THIRD_PARTIES
from app.services.privacy.registry_stores import STORES
from app.services.privacy.registry_tables import TABLES

router = APIRouter()


@router.get("/privacy/data-map")
async def data_map(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "data": {
            "third_parties": [
                {"key": k.value, "name": v.name, "sends": v.sends, "masked": v.masked, "switch": v.switch}
                for k, v in THIRD_PARTIES.items()
            ],
            "tables": [
                {"table": n, "purpose": t.purpose, "subject": t.subject.value, "retention": t.retention.value,
                 "columns": {c: cat.value for c, cat in t.columns.items()}, "third_parties": [f.value for f in t.flows]}
                for n, t in sorted(TABLES.items())
            ],
            "stores": [
                {"key": s.key, "holds": s.holds, "where": s.where, "retention": s.retention.value, "lifetime": s.ttl,
                 "third_parties": [f.value for f in s.flows]}
                for s in STORES
            ],
            "markdown": inventory_doc.render(),
        },
        "error": None,
    }


@router.get("/privacy/operator/breach-scope")
async def breach_scope(
    keys: str,
    operator: User = Depends(require_platform_operator),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Which companies, categories and kinds of people a breach of these registry keys touches.

    `keys` is a comma-separated list of registry tables and stores (`outbox_messages,uploads`). Counts only; see
    `app.services.privacy.breach_scope` and docs/ops/runbooks/data-breach.md.
    """
    wanted = [k.strip() for k in keys.split(",") if k.strip()]
    try:
        return {"data": await scope(db, wanted), "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
