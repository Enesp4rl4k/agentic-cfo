"""Veri ve gizlilik: export, retention choices, notices, and the one call the settings screen needs.

  GET  /privacy/overview                       what the screen shows (role-aware)
  GET  /privacy/my-data                        the caller's own personal data, as a JSON download (any member)
  POST /privacy/exports                        owner: build the company-wide export (a job; returns at once)
  GET  /privacy/exports/{id}                   owner: its state
  GET  /privacy/exports/{id}/download          owner: the bundle, until its download window closes
  GET  /privacy/retention/preview              owner/admin: what the retention job would purge for THIS company now
  PUT  /privacy/retention                      owner: this company's own (shorter) retention choices, never below the floor
  GET  /privacy/notices, POST /privacy/notices/accept    versioned acceptance of the privacy notice and the terms
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.config import get_settings
from app.core.background import spawn
from app.core.http_headers import content_disposition
from app.database import get_db
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.privacy_records import DataExport, RetentionRun
from app.models.user import User
from app.services.acting_role import acting_role
from app.services.decisions import record_decision
from app.services.privacy import export_flow, notices, retention
from app.services.privacy.registry import THIRD_PARTIES
from app.services.privacy.registry_stores import STORES
from app.services.privacy.registry_tables import TABLES

router = APIRouter()
NOT_FOUND = "Kayıt bulunamadı."
CHUNK = 1024 * 1024


async def _role(db: AsyncSession, user: User) -> str | None:
    return await acting_role(db, user) if user.org_id else None


async def _owner_org(db: AsyncSession, user: User) -> str:
    if await _role(db, user) != "owner":
        raise HTTPException(status_code=403, detail="Bu işlem için owner rolü gerekli.")
    return str(user.org_id)


class RetentionBody(BaseModel):
    # day numbers per company setting; null removes the company's choice (the platform default applies again)
    policy: dict[str, int | None]


class NoticeBody(BaseModel):
    privacy_notice: str | None = None
    terms: str | None = None


@router.get("/privacy/overview")
async def overview(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    role = await _role(db, current_user)
    org = await db.get(Organization, str(current_user.org_id)) if current_user.org_id else None
    settings = get_settings()
    data: dict[str, Any] = {
        "role": role,
        "third_parties": [{"key": k.value, "name": v.name, "sends": v.sends, "masked": v.masked, "switch": v.switch,
                           "reaches_from": sorted([n for n, t in TABLES.items() if k in t.flows] + [s.key for s in STORES if k in s.flows])}
                          for k, v in THIRD_PARTIES.items()],
        "notices": await notices.status(db, str(current_user.id)),
        "cooling_off_days": settings.erasure_cooling_off_days,
        "retention": {
            "platform": retention.platform_policy(), "effective": retention.effective_policy(org),
            "company_choice": (org.retention_policy if org is not None else None) or {},
            "floor_days": retention.FLOOR_DAYS, "company_keys": list(retention.ORG_KEYS),
            "dry_run": settings.retention_dry_run, "can_edit": role == "owner",
        },
        "export": None,
    }
    if role == "owner" and org is not None:
        live = await export_flow.active_export(db, str(org.id))
        data["export"] = export_flow.to_dict(live) if live else None
    return {"data": data, "error": None}


@router.get("/privacy/my-data")
async def my_data(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    body = json.dumps(await export_flow.member_export(db, current_user), ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(iter([body]), media_type="application/json", headers={
        "Content-Disposition": content_disposition(f"my-data-{str(current_user.id)[:8]}.json"),
        "Content-Length": str(len(body))})


@router.post("/privacy/exports")
async def request_export(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    org_id = await _owner_org(db, current_user)
    row, created = await export_flow.request_export(db, current_user, org_id, "owner")
    if created:
        if not await export_flow.enqueue(row.id) and get_settings().allow_inline_job_fallback:
            spawn(_build_inline(row.id), name=f"data-export-{row.id}")
    return {"data": {**export_flow.to_dict(row), "created": created}, "error": None}


async def _build_inline(export_id: str) -> None:
    from app.database import engine, get_session_factory

    async with get_session_factory(engine())() as db:
        await export_flow.build_export(db, export_id)


async def _own_export(db: AsyncSession, user: User, export_id: str) -> DataExport:
    org_id = await _owner_org(db, user)
    row = await db.get(DataExport, export_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    ensure_tenant(user, org_id=row.org_id)
    if row.org_id != org_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row


@router.get("/privacy/exports/{export_id}")
async def export_status(export_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"data": export_flow.to_dict(await _own_export(db, current_user, export_id)), "error": None}


@router.get("/privacy/exports/{export_id}/download")
async def export_download(export_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    row = await _own_export(db, current_user, export_id)
    expires = row.expires_at if row.expires_at is None or row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    if row.status != "ready" or not row.file_path or expires is None or expires <= datetime.now(UTC):
        raise HTTPException(status_code=410 if row.status in ("expired", "ready") else 409,
                            detail="Dışa aktarım indirilemez: hazır değil ya da indirme süresi doldu; yenisini isteyin.")
    path = Path(row.file_path)
    try:
        path.resolve().relative_to(export_flow.storage_root().resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from exc
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Dışa aktarım dosyası artık yok; yenisini isteyin.")
    row.downloads += 1
    await db.commit()

    def chunks() -> Iterator[bytes]:
        with path.open("rb") as fh:
            while block := fh.read(CHUNK):
                yield block

    return StreamingResponse(chunks(), media_type="application/zip", headers={
        "Content-Disposition": content_disposition(f"company-export-{row.id[:8]}.zip"),
        "Content-Length": str(path.stat().st_size), "Cache-Control": "private, no-store"})


@router.get("/privacy/retention/preview")
async def retention_preview(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if await _role(db, current_user) not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Bu görünüm için owner veya admin rolü gerekli.")
    org = await db.get(Organization, str(current_user.org_id))
    if org is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    counts = await retention.purge_org(db, str(org.id), retention.effective_policy(org), dry_run=True, now=datetime.now(UTC))
    last = (await db.execute(select(RetentionRun).where(RetentionRun.scope == "all", RetentionRun.status == "done")
                             .order_by(RetentionRun.started_at.desc()).limit(1))).scalar_one_or_none()
    return {"data": {"would_purge": counts, "job_dry_run": get_settings().retention_dry_run,
                     "last_run_at": last.started_at.isoformat() if last else None}, "error": None}


@router.put("/privacy/retention")
async def set_retention(body: RetentionBody, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    org_id = await _owner_org(db, current_user)
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    try:
        choice = retention.validate_choice({k: v for k, v in body.policy.items() if v is not None})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    unknown = [k for k, v in body.policy.items() if v is None and k not in retention.ORG_KEYS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"not a company setting: {unknown}")
    before = dict(org.retention_policy or {})
    after = {**{k: v for k, v in before.items() if k not in body.policy}, **choice}
    org.retention_policy = after or None
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.RETENTION_POLICY_CHANGE, target_type="organization", target_id=org_id,
        outcome="changed", decided_via=DecidedVia.HUMAN, decided_by=str(current_user.id), before=before, after=after,
    )
    await db.commit()
    return {"data": {"company_choice": after, "effective": retention.effective_policy(org)}, "error": None}


@router.get("/privacy/notices")
async def notice_status(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"data": await notices.status(db, str(current_user.id)), "error": None}


@router.post("/privacy/notices/accept")
async def accept_notices(body: NoticeBody, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    versions = {k: v for k, v in body.model_dump().items() if v}
    if not versions:
        raise HTTPException(status_code=422, detail="En az bir belge sürümü gerekli.")
    try:
        recorded = await notices.accept(db, str(current_user.id), versions)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"data": {"recorded": recorded, "notices": await notices.status(db, str(current_user.id))}, "error": None}

