"""Tetikleyici API (P4-4) — create, manage and audit trigger rules.

The engine (P4-1) and its five actions (P4-2) only ever see rows; this router
is how a user gets one in and answers "why didn't my rule fire?". Every write
round-trips through the ``TriggerDefinition`` contract, so a stored row always
rehydrates for the engine — the API never persists a shape the engine would
choke on.

Endpoints (prefix /api/v1):

    GET    /tetikler/meta           catalogs for the UI form (kinds, ops, metrics)
    GET    /tetikler                list the org's rules
    POST   /tetikler                create a rule (contract-validated)
    GET    /tetikler/runs           audit trail (optional ?trigger_id=)
    POST   /tetikler/dry-run        evaluate a condition — no action fires
    GET    /tetikler/{id}           fetch one rule
    PATCH  /tetikler/{id}           partial update: merge, re-validate, store
    DELETE /tetikler/{id}           delete a rule (its audit rows survive)
"""
from __future__ import annotations

import json
import logging
from typing import Any, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.database import get_db
from app.models.trigger import TriggerDefinitionRow, TriggerRunRow
from app.models.user import User
from app.services.semantic.catalog import METRIC_CATALOG
from app.services.triggers import (
    ActionKind,
    EventKind,
    TriggerDefinition,
    condition_to_dict,
    evaluate,
    parse_condition,
    unknown_metrics,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_EVENT_KINDS: tuple[str, ...] = tuple(get_args(EventKind))
_ACTION_KINDS: tuple[str, ...] = tuple(get_args(ActionKind))
_OPERATORS: tuple[str, ...] = ("gt", "gte", "lt", "lte", "eq", "ne", "abs_gt")
# The contract fields a row carries — the merge surface for PATCH, kept in one
# place so row metadata (id/org_id/timestamps) can never leak into validation.
_CONTRACT_FIELDS = (
    "name",
    "events",
    "condition",
    "action_kind",
    "action_params",
    "cooldown_minutes",
    "enabled",
)


class _RuleBody(BaseModel):
    """Create/update payload — loose types on purpose; the contract validates."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    events: list[str] | None = None
    condition: dict[str, Any] | list[Any] | None = None
    action_kind: str | None = None
    action_params: dict[str, Any] | None = None
    cooldown_minutes: int | None = None
    enabled: bool | None = None


class _DryRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: dict[str, Any] | list[Any]
    values: dict[str, Any] = Field(default_factory=dict)


def _org_id(user: User) -> str:
    """The org a caller's rows live under (solo users fall back to their id)."""
    return str(user.org_id) if user.org_id else str(user.id)


def _validated(payload: dict[str, Any]) -> TriggerDefinition:
    """Contract-validate a rule payload; translate failures to HTTP 400."""
    events = payload.get("events")
    if events:
        unknown = [e for e in events if e not in _EVENT_KINDS]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Bilinmeyen olay türü: {', '.join(unknown)} — "
                    f"geçerli: {', '.join(_EVENT_KINDS)}"
                ),
            )
    action_kind = payload.get("action_kind")
    if action_kind and action_kind not in _ACTION_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Bilinmeyen aksiyon türü: {action_kind} — "
                f"geçerli: {', '.join(_ACTION_KINDS)}"
            ),
        )
    try:
        parse_condition(payload.get("condition"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Geçersiz koşul: {exc}") from exc
    try:
        return TriggerDefinition(**payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz tetikleyici ({'.'.join(str(p) for p in first['loc'])}): {first['msg']}",
        ) from exc


async def _owned_row(
    db: AsyncSession, trigger_id: str, user: User
) -> TriggerDefinitionRow:
    row = await db.get(TriggerDefinitionRow, trigger_id)
    # ensure_tenant reports a foreign rule as missing, never as forbidden — the
    # caller learns nothing about ids outside their org. Rows carry only an org
    # (solo users' rows are keyed by their user id, written into org_id).
    if row is None:
        raise HTTPException(status_code=404, detail="Tetikleyici bulunamadı.")
    ensure_tenant(user, org_id=row.org_id)
    return row


@router.get("/tetikler/meta")
async def tetikleyici_meta(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Catalogs the UI form needs: kinds, operators, metrics, cascade triggers."""
    from app.services.cascade_simulator import TriggerType

    return {
        "data": {
            "action_kinds": list(_ACTION_KINDS),
            "event_kinds": list(_EVENT_KINDS),
            "operators": list(_OPERATORS),
            "metrics": [
                {
                    "id": m.metric_id,
                    "label": m.label,
                    "unit": m.unit,
                    "owner_role": m.owner_role,
                }
                for m in METRIC_CATALOG.values()
            ],
            "cascade_triggers": [t.value for t in TriggerType],
            "cooldown_default_minutes": 60,
        },
        "error": None,
    }


@router.get("/tetikler")
async def list_triggers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(TriggerDefinitionRow)
            .where(TriggerDefinitionRow.org_id == _org_id(user))
            .order_by(desc(TriggerDefinitionRow.created_at))
        )
    ).scalars().all()
    triggers = [{**r.to_dict(), "org_id": r.org_id} for r in rows]
    return {"data": {"triggers": triggers}, "error": None}


@router.post("/tetikler", status_code=status.HTTP_201_CREATED)
async def create_trigger(
    body: _RuleBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    missing = [f for f in ("name", "events", "condition", "action_kind")
               if getattr(body, f) is None]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Zorunlu alanlar eksik: {', '.join(missing)}",
        )
    definition = _validated({
        "name": body.name,
        "events": body.events,
        "condition": body.condition,
        "action_kind": body.action_kind,
        "action_params": body.action_params or {},
        "cooldown_minutes": body.cooldown_minutes
        if body.cooldown_minutes is not None else 60,
        "enabled": body.enabled if body.enabled is not None else True,
    })
    row = TriggerDefinitionRow(
        org_id=_org_id(user),
        name=definition.name,
        events=json.dumps(definition.events),
        condition=json.dumps(condition_to_dict(definition.condition)),
        action_kind=definition.action_kind,
        action_params=json.dumps(definition.action_params),
        cooldown_minutes=definition.cooldown_minutes,
        enabled=definition.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"data": {**row.to_dict(), "org_id": row.org_id}, "error": None}


@router.get("/tetikler/runs")
async def list_trigger_runs(
    trigger_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The audit trail — every evaluation with its decision and result."""
    q = select(TriggerRunRow).where(TriggerRunRow.org_id == _org_id(user))
    if trigger_id:
        q = q.where(TriggerRunRow.trigger_id == trigger_id)
    rows = (
        await db.execute(q.order_by(desc(TriggerRunRow.created_at)).limit(limit))
    ).scalars().all()
    return {"data": {"runs": [r.to_dict() for r in rows]}, "error": None}


@router.post("/tetikler/dry-run")
async def dry_run_condition(
    body: _DryRunBody,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Evaluate a condition against sample values — no action fires, no row writes."""
    try:
        condition = parse_condition(body.condition)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Geçersiz koşul: {exc}") from exc
    return {
        "data": {
            "would_fire": evaluate(condition, body.values),
            # Metrics the tree references that the frozen catalog lacks — the
            # usual reason a live run sits at condition_false forever.
            "unknown_metrics": unknown_metrics(condition),
            "condition": condition_to_dict(condition),
        },
        "error": None,
    }


@router.get("/tetikler/{trigger_id}")
async def get_trigger(
    trigger_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_row(db, trigger_id, user)
    return {"data": {**row.to_dict(), "org_id": row.org_id}, "error": None}


@router.patch("/tetikler/{trigger_id}")
async def update_trigger(
    trigger_id: str,
    body: _RuleBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Partial update: merge onto the stored rule, then re-validate the whole.

    Re-validating the merge (not just the patched fields) is what keeps the
    invariant the engine depends on: every stored row is a valid contract.
    """
    row = await _owned_row(db, trigger_id, user)
    current = row.to_dict()
    merged: dict[str, Any] = {f: current[f] for f in _CONTRACT_FIELDS}
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            merged[key] = value
    definition = _validated(merged)
    row.name = definition.name
    row.events = json.dumps(definition.events)
    row.condition = json.dumps(condition_to_dict(definition.condition))
    row.action_kind = definition.action_kind
    row.action_params = json.dumps(definition.action_params)
    row.cooldown_minutes = definition.cooldown_minutes
    row.enabled = definition.enabled
    await db.commit()
    await db.refresh(row)
    return {"data": {**row.to_dict(), "org_id": row.org_id}, "error": None}


@router.delete("/tetikler/{trigger_id}")
async def delete_trigger(
    trigger_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_row(db, trigger_id, user)
    await db.delete(row)
    await db.commit()
    return {"data": {"deleted": True, "trigger_id": trigger_id}, "error": None}
