"""Connector Platform API (Faz 13).

    GET    /connectors                     — registered connectors + this org's status
    POST   /connectors/{name}/connect      — store credentials (health-checked first)
    POST   /connectors/{name}/sync         — pull now; optionally re-run the fed kernel
    GET    /connectors/{name}/status       — last sync / watermark
    DELETE /connectors/{name}              — disconnect (keeps canonical rows)
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.connectors import get_connector, has_connector, list_connectors, run_connector_sync
from app.connectors.crypto import encrypt_secret
from app.database import get_db
from app.models.connector_connection import ConnectorConnection
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _org_id(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    return str(user.org_id)


def _known(name: str) -> None:
    if not has_connector(name):
        raise HTTPException(status_code=404, detail=f"Bilinmeyen connector: {name}")


class ConnectRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)   # non-secret (owner, repo, …)
    secret: dict[str, Any] = Field(default_factory=dict)   # token / credentials
    display_name: str | None = None


class SyncRequest(BaseModel):
    run_kernel: bool = True   # re-run the connector's kernel_role view after sync


@router.get("/connectors")
async def list_connector_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    rows = {
        r.connector: r
        for r in (
            await db.execute(
                select(ConnectorConnection).where(ConnectorConnection.org_id == org_id)
            )
        ).scalars()
    }
    out = []
    for c in list_connectors():
        row = rows.get(c.name)
        out.append({
            "name": c.name,
            "domain": c.domain,
            "kernel_role": c.kernel_role,
            "connected": row is not None and row.status != "disconnected",
            "status": row.status if row else "not_connected",
            "last_sync_at": row.last_sync_at.isoformat() if row and row.last_sync_at else None,
            "last_record_count": row.last_record_count if row else None,
            "last_error": row.last_error if row else None,
        })
    return {"data": {"connectors": out}, "error": None}


@router.post("/connectors/{name}/connect", status_code=status.HTTP_201_CREATED)
async def connect_connector(
    name: str,
    body: ConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _known(name)
    org_id = _org_id(current_user)
    connector = get_connector(name)

    health = await connector.health(config=body.config, secret=body.secret)
    if not health.ok:
        raise HTTPException(status_code=400, detail=f"Bağlantı doğrulanamadı: {health.detail}")

    row = (
        await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.org_id == org_id,
                ConnectorConnection.connector == name,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = ConnectorConnection(org_id=org_id, connector=name)
        db.add(row)
    row.config_json = json.dumps(body.config)
    row.secret_enc = encrypt_secret(json.dumps(body.secret)) if body.secret else None
    row.display_name = body.display_name or health.account or name
    row.status = "active"
    row.last_error = None
    row.updated_at = now
    await db.commit()

    return {
        "data": {"connector": name, "status": "active", "account": health.account,
                 "detail": health.detail},
        "error": None,
    }


@router.post("/connectors/{name}/sync")
async def sync_connector(
    name: str,
    body: SyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _known(name)
    org_id = _org_id(current_user)

    result = await run_connector_sync(connector_name=name, org_id=org_id, db=db)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error or "sync başarısız")

    kernel: dict[str, Any] | None = None
    connector = get_connector(name)
    if body.run_kernel and connector.kernel_role == "cto":
        try:
            from app.agents.cto.cto_kernel import run_cto_kernel
            from app.services.eng_signals import cto_existing_data_from_signals

            existing = await cto_existing_data_from_signals(org_id, db)
            kernel = await run_cto_kernel(existing_cto_data=existing)
        except Exception as exc:
            logger.warning("post-sync CTO kernel failed for org=%s: %s", org_id, exc)

    return {
        "data": {"sync": result.to_dict(), "kernel": kernel},
        "error": None,
        "meta": {"connector": name, "kernel_role": connector.kernel_role},
    }


@router.get("/connectors/{name}/status")
async def connector_status(
    name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _known(name)
    org_id = _org_id(current_user)
    row = (
        await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.org_id == org_id,
                ConnectorConnection.connector == name,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"data": {"connector": name, "status": "not_connected"}, "error": None}
    return {
        "data": {
            "connector": name,
            "status": row.status,
            "display_name": row.display_name,
            "config": json.loads(row.config_json) if row.config_json else {},
            "watermark_since": row.watermark_since.isoformat() if row.watermark_since else None,
            "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
            "last_status": row.last_status,
            "last_record_count": row.last_record_count,
            "last_error": row.last_error,
        },
        "error": None,
    }


@router.delete("/connectors/{name}")
async def disconnect_connector(
    name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _known(name)
    org_id = _org_id(current_user)
    row = (
        await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.org_id == org_id,
                ConnectorConnection.connector == name,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        row.status = "disconnected"
        row.secret_enc = None
        row.updated_at = datetime.now(UTC)
        await db.commit()
    return {"data": {"connector": name, "status": "disconnected"}, "error": None}
