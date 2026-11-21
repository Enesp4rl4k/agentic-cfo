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
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.contract import Envelope
from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.email_ingest import EmailIngestAddress
from app.models.erp_integration import ERPIntegration
from app.models.organization import Organization
from app.models.user import User

router = APIRouter()


class Firma(BaseModel):
    var: bool
    ad: str | None


class Veri(BaseModel):
    analiz_sayisi: int
    parasut_bagli: bool


class SonAnaliz(BaseModel):
    id: str
    durum: str
    onay_bekliyor: bool
    guven: float | None
    dosya: str
    hata: str | None
    olusturma: str | None
    # Where every row of the upload went: read, saved, waiting, skipped (app.services.ingest.summary).
    ingest: dict[str, Any] | None = None


class Otomatik(BaseModel):
    eposta: bool
    parasut_otomatik: bool


class Analizler(BaseModel):
    """Every analysis of the company by what became of it, not only the latest one."""

    calisan: int
    onay_bekleyen: int
    tamamlanan: int
    basarisiz: int


class BekleyenAnaliz(BaseModel):
    id: str
    dosya: str
    guven: float | None
    # Reason codes with their numbers (app.services.held_analysis); the screen words them.
    nedenler: list[dict[str, Any]]
    # The run read a statement whose running balances chain: approving it gives the radar its start.
    bakiye_kanitli: bool
    olusturma: str | None


class Baslangic(BaseModel):
    firma: Firma
    veri: Veri
    son_analiz: SonAnaliz | None
    tamamlanan_analiz: int
    analizler: Analizler
    onay_bekleyen: list[BekleyenAnaliz]
    otomatik: Otomatik


@router.get("/baslangic", response_model=Envelope[Baslangic])
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

    by_status: dict[str, int] = {
        str(status): int(n)
        for status, n in (await db.execute(
            select(AnalysisJob.status, func.count(AnalysisJob.id)).where(scope).group_by(AnalysisJob.status)
        )).all()
    }

    def count(*names: JobStatus) -> int:
        return sum(by_status.get(str(n.value), 0) for n in names)

    from app.services import held_analysis

    held = await held_analysis.list_held(db, org_id, current_user.id)

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
                "ingest": (son.result_metadata or {}).get("ingest"),
            },
            "tamamlanan_analiz": tamamlanan,
            "analizler": {
                "calisan": count(JobStatus.PENDING, JobStatus.INGESTING, JobStatus.ANALYZING),
                "onay_bekleyen": len(held),
                "tamamlanan": tamamlanan,
                "basarisiz": count(JobStatus.FAILED),
            },
            "onay_bekleyen": [
                {
                    "id": j.id,
                    "dosya": j.filename,
                    "guven": float(j.min_confidence) if j.min_confidence is not None else None,
                    "nedenler": held_analysis.why_held(j),
                    "bakiye_kanitli": held_analysis.proves_balance(j),
                    "olusturma": j.created_at.isoformat() if j.created_at else None,
                }
                for j in held
            ],
            "otomatik": {
                "eposta": eposta,
                "parasut_otomatik": bool(parasut_bagli and parasut is not None and parasut.auto_sync_enabled),
            },
        },
        "error": None,
    }
