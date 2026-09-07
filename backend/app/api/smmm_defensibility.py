"""SMMM Defensibility Packet API (differentiator #4).

    POST /smmm/defensibility/{job_id}/build       — (re)generate a draft packet
    GET  /smmm/defensibility                       — list packets for the org
    GET  /smmm/defensibility/{packet_id}           — one packet (full payload)
    POST /smmm/defensibility/{packet_id}/finalize  — freeze + seal with the SMMM's statement
    GET  /smmm/defensibility/{packet_id}/export    — human-readable document (PDF/text)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps_regional import require_tr_pack
from app.core.http_headers import content_disposition
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.defensibility_packet import DefensibilityPacket
from app.models.user import User
from app.services.smmm_defensibility import (
    DefensibilityError,
    build_packet,
    finalize_packet,
)
from app.services.smmm_defensibility_pdf import render_packet

router = APIRouter(dependencies=[Depends(require_tr_pack)])
logger = logging.getLogger(__name__)


def _org_id(user: User) -> str | None:
    return str(user.org_id) if user.org_id else None


def _packet_brief(p: DefensibilityPacket) -> dict[str, Any]:
    return {
        "id": p.id,
        "job_id": p.job_id,
        "period": p.period,
        "status": p.status,
        "content_hash": p.content_hash,
        "summary": p.summary,
        "finalized_at": p.finalized_at.isoformat() if p.finalized_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


class FinalizeRequest(BaseModel):
    statement: str = Field(..., min_length=1, description="Mali müşavir beyanı / imza metni")


@router.post("/smmm/defensibility/{job_id}/build", status_code=status.HTTP_201_CREATED)
async def build_defensibility_packet(
    job_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    period: str | None = Query(None),
) -> dict[str, Any]:
    job = await db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    org_id = _org_id(current_user)
    if job.org_id and org_id and str(job.org_id) != org_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")
    try:
        packet = await build_packet(
            db=db, job_id=job_id, org_id=org_id,
            period=period or (job.created_at.strftime("%Y-%m") if job.created_at else None),
        )
    except DefensibilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"data": _packet_brief(packet), "error": None}


@router.get("/smmm/defensibility")
async def list_defensibility_packets(
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    period: str | None = Query(None),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    stmt = select(DefensibilityPacket).where(DefensibilityPacket.org_id == org_id)
    if period:
        stmt = stmt.where(DefensibilityPacket.period == period)
    rows = (await db.execute(stmt.order_by(desc(DefensibilityPacket.created_at)).limit(100))).scalars().all()
    return {"data": {"packets": [_packet_brief(p) for p in rows]}, "error": None}


async def _load_owned(packet_id: str, user: User, db: AsyncSession) -> DefensibilityPacket:
    packet = await db.get(DefensibilityPacket, packet_id)
    org_id = _org_id(user)
    if packet is None or (packet.org_id and org_id and packet.org_id != org_id):
        raise HTTPException(status_code=404, detail="Paket bulunamadı.")
    return packet


@router.get("/smmm/defensibility/{packet_id}")
async def get_defensibility_packet(
    packet_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    packet = await _load_owned(packet_id, current_user, db)
    return {
        "data": {**_packet_brief(packet), "payload": packet.payload,
                 "smmm_statement": packet.smmm_statement},
        "error": None,
    }


@router.post("/smmm/defensibility/{packet_id}/finalize")
async def finalize_defensibility_packet(
    packet_id: str,
    body: FinalizeRequest,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    packet = await _load_owned(packet_id, current_user, db)
    try:
        packet = await finalize_packet(
            db=db, packet_id=packet.id, user_id=str(current_user.id),
            statement=body.statement,
        )
    except DefensibilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"data": _packet_brief(packet), "error": None}


@router.get("/smmm/defensibility/{packet_id}/export")
async def export_defensibility_packet(
    packet_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
) -> Response:
    packet = await _load_owned(packet_id, current_user, db)
    body, media_type = render_packet(packet)
    ext = "pdf" if media_type == "application/pdf" else "txt"
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(f"savunulabilirlik-{packet.job_id}.{ext}"),
            "Content-Length": str(len(body)),
        },
    )
