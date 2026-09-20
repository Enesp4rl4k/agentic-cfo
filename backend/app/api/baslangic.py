"""
Başlangıç — where a new organisation stands, read from its data.

GET /api/v1/baslangic

The first-use guide used to be a slideshow whose progress lived in the
browser: it said nothing about whether the company had any data, and a person
who clicked "Atla" was "done". Each step here is a fact about the database —
the company exists, data has arrived, the first analysis finished (or is
waiting for a person's approval, or failed and why) — so the guide shows what
is actually left to do. Wording lives in the frontend; this returns facts.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.email_ingest import EmailIngestAddress
from app.models.erp_integration import ERPIntegration
from app.models.organization import Organization
from app.models.user import User

router = APIRouter()


@router.get("/baslangic")
async def baslangic(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = current_user.org_id
    org = await db.get(Organization, org_id) if org_id else None

    # A user without an organisation still owns the jobs they uploaded.
    scope = AnalysisJob.org_id == org_id if org_id else AnalysisJob.user_id == current_user.id

    analiz_sayisi = int(await db.scalar(select(func.count(AnalysisJob.id)).where(scope)) or 0)
    son = (await db.execute(
        select(AnalysisJob).where(scope).order_by(desc(AnalysisJob.created_at)).limit(1)
    )).scalar_one_or_none()
    tamamlanan = int(await db.scalar(
        select(func.count(AnalysisJob.id)).where(scope, AnalysisJob.status == "completed")
    ) or 0)

    parasut = None
    eposta = False
    if org_id:
        parasut = (await db.execute(
            select(ERPIntegration)
            .where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "parasut")
            .order_by(desc(ERPIntegration.created_at))
            .limit(1)
        )).scalar_one_or_none()
        eposta = (await db.scalar(
            select(func.count(EmailIngestAddress.id)).where(
                EmailIngestAddress.org_id == org_id, EmailIngestAddress.revoked_at.is_(None)
            )
        ) or 0) > 0

    parasut_bagli = bool(parasut is not None and parasut.status == "active")
    return {
        "data": {
            "firma": {"var": org is not None, "ad": org.name if org else None},
            "veri": {"analiz_sayisi": analiz_sayisi, "parasut_bagli": parasut_bagli},
            "son_analiz": None if son is None else {
                "id": son.id,
                "durum": str(son.status),
                "onay_bekliyor": bool(son.awaiting_review),
                "guven": float(son.min_confidence) if son.min_confidence is not None else None,
                "dosya": son.filename,
                "hata": son.error_message,
                "olusturma": son.created_at.isoformat() if son.created_at else None,
            },
            "tamamlanan_analiz": tamamlanan,
            "otomatik": {
                "eposta": eposta,
                "parasut_otomatik": bool(parasut_bagli and parasut is not None and parasut.auto_sync_enabled),
            },
        },
        "error": None,
    }
