"""
Muhasebe API — MUHASEBE-5

Endpoint'ler:
  POST /muhasebe/analiz        — İşlemleri THP + double-entry ile analiz et
  GET  /muhasebe/onay-kuyrugu  — SMMM onay bekleyen kayıtları listele
  POST /muhasebe/onayla/{id}   — Kaydı onayla
  POST /muhasebe/duzelt/{id}   — Kaydı düzelt (hesap kodu değiştir)
  POST /muhasebe/reddet/{id}   — Kaydı reddet
  GET  /muhasebe/mizan/{job_id}— Job için mizan özeti
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_role
from app.api.deps_regional import require_tr_pack
from app.config import get_settings
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.organization import Organization

if TYPE_CHECKING:
    # Imported for annotations only: the service is loaded lazily inside the
    # handlers, like every other service in this module.
    from app.services.edefter_xbrl import EDefterXBRL, LedgerOwner
from app.core.http_headers import content_disposition
from app.models.report import Report, ReportFormat
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.transaction import Transaction
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

_MUHASEBE_JOURNAL_REPORT = "tr_muhasebe_journal"


async def _org_packs(db: AsyncSession, org_id: str | None) -> list[str]:
    if not org_id:
        return []
    from app.services.regional.packs import normalize_packs

    org = await db.get(Organization, str(org_id))
    return normalize_packs(getattr(org, "regional_packs", None)) if org else []


async def _enqueue_smmm_review(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str | None,
    user_id: str,
    items: list[dict[str, Any]],
    packs: list[str],
) -> int:
    """Write the review records for entries policy reserved for a human.

    Shared by both journal-producing routes. It was inline in one of them, and
    the other simply did not do it — the same shape as the two upload paths,
    where a second entry point copied part of the first.
    """
    if "tr" not in packs:
        return 0
    added = 0
    for onay_item in items:
        db.add(SMMMOnayKaydi(
            job_id=job_id,
            org_id=org_id,
            created_by_user_id=user_id,
            kayit_id=onay_item["kayit_id"],
            orijinal_kayit=onay_item,
            durum=OnayDurumu.BEKLIYOR,
            otomatik_hesap_kodu=onay_item.get("thp_hesap_kodu"),
            otomatik_confidence=onay_item.get("confidence"),
            onay_neden=onay_item.get("onay_neden"),
            tx_description=onay_item.get("tx_description"),
            tx_amount_try=onay_item.get("tx_amount_try"),
        ))
        added += 1
    return added


async def _persist_muhasebe_journal(
    db: AsyncSession, job_id: str, full_result: dict[str, Any]
) -> None:
    """Upsert the full THP journal for a job as a JSON Report — the durable
    source the defensibility packet itemises from."""
    existing = (
        await db.execute(
            select(Report)
            .where(
                Report.job_id == job_id,
                Report.report_type == _MUHASEBE_JOURNAL_REPORT,
                Report.report_format == ReportFormat.JSON,
            )
            .order_by(desc(Report.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        existing.data = full_result
    else:
        db.add(
            Report(
                job_id=job_id,
                report_type=_MUHASEBE_JOURNAL_REPORT,
                report_format=ReportFormat.JSON,
                data=full_result,
            )
        )


# ── Pydantic şemaları ─────────────────────────────────────────────────────────

class MuhasebeAnalizRequest(BaseModel):
    job_id: str
    company_name: str | None = None
    donem: str | None = Field(None, description="Dönem (ör. '2024-01')")
    use_llm_fallback: bool = True


class TRVerticalRequest(BaseModel):
    job_id: str
    company_name: str | None = None
    donem: str | None = Field(None, description="Dönem (ör. '2024-01')")


class OnayRequest(BaseModel):
    onay_notu: str | None = None


class DuzeltiRequest(BaseModel):
    yeni_hesap_kodu: str = Field(..., description="THP hesap kodu (ör. '770')")
    yeni_hesap_adi: str
    duzeltme_aciklama: str | None = None


class ReddetRequest(BaseModel):
    red_neden: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/muhasebe/analiz", status_code=status.HTTP_201_CREATED)
async def muhasebe_analiz(
    body: MuhasebeAnalizRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Bir analiz job'unun işlemlerini THP sınıflandır ve yevmiye kaydı oluştur.
    SMMM onayı gereken kayıtları otomatik olarak onay kuyruğuna ekle.
    """
    from app.agents.accounting.orchestrator import get_muhasebe_agent

    # Job kontrolü
    job = await db.get(AnalysisJob, body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    if job.org_id and job.org_id != current_user.org_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")

    # İşlemleri yükle
    tx_result = await db.execute(
        select(Transaction).where(Transaction.job_id == body.job_id)
    )
    txs = tx_result.scalars().all()

    if not txs:
        raise HTTPException(
            status_code=400,
            detail="Bu job'a ait işlem bulunamadı. Önce analiz çalıştırın.",
        )

    tx_dicts = [
        {
            "id":               tx.id,
            "amount_kurus":     tx.amount_kurus,
            "type":             tx.type,
            "description":      tx.description,
            "vendor":           tx.vendor,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
            # The column is not nullable, so a row whose date could not be read
            # already holds a placeholder. Without this flag the engine sees a
            # perfectly ordinary date and books it into the wrong period.
            "date_is_estimated": bool(tx.date_is_estimated),
        }
        for tx in txs
    ]

    # Muhasebe analizi — CoA adapter follows org regional packs
    packs: list[str] = []
    if job.org_id:
        from app.models.organization import Organization
        from app.services.regional.packs import normalize_packs

        org = await db.get(Organization, str(job.org_id))
        if org:
            packs = normalize_packs(getattr(org, "regional_packs", None))

    from app.platform.authority_matrix import load_active_rules

    authority_rules = await load_active_rules(
        str(job.org_id) if job.org_id else None, db
    )

    # İlişkili taraf sicili: eşleşen işlemler `is_related_party` ile
    # işaretlenir. Yetki matrisinin ilişkili-taraf kuralı bu bayrağı okur ama
    # bugüne kadar onu kimse doldurmuyordu, yani kural hiç ateşlenmedi.
    related_flagged = 0
    if job.org_id:
        from app.services.related_party import annotate_transactions, load_active_parties

        parties = await load_active_parties(str(job.org_id), db)
        related_flagged = annotate_transactions(tx_dicts, parties)
        if related_flagged:
            logger.info(
                "İlişkili taraf: %d işlem işaretlendi (job=%s)", related_flagged, body.job_id
            )

    agent = get_muhasebe_agent(
        use_llm_fallback=body.use_llm_fallback,
        regional_packs=packs,
    )
    sonuc = await agent.run(
        job_id=body.job_id,
        transactions=tx_dicts,
        company_name=body.company_name,
        donem=body.donem,
        authority_rules=authority_rules,
    )

    # SMMM onay kuyruğu — Turkey pack only
    onay_eklendi = await _enqueue_smmm_review(
        db,
        job_id=body.job_id,
        org_id=str(job.org_id) if job.org_id else None,
        user_id=current_user.id,
        items=sonuc.onay_kuyrugu,
        packs=packs,
    )

    # Persist the full journal (incl. auto-posted entries) so the defensibility
    # packet can itemise every decision later. Upsert the latest per job.
    await _persist_muhasebe_journal(db, body.job_id, sonuc.to_full_dict())

    await db.commit()

    result_dict = sonuc.to_dict()
    result_dict["onay_kuyruguna_eklendi"] = onay_eklendi
    result_dict["iliskili_taraf_isaretlendi"] = related_flagged
    result_dict["coa_adapter"] = "tr_thp" if "tr" in packs else "generic_gaap"

    logger.info(
        "Muhasebe analizi tamamlandı: job=%s kayıt=%d onay=%d",
        body.job_id, sonuc.kayit_sayisi, onay_eklendi,
    )

    return {"data": result_dict, "error": None}


@router.post("/muhasebe/tr-vertical", status_code=status.HTTP_201_CREATED)
async def muhasebe_tr_vertical(
    body: TRVerticalRequest,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    L3 autopilot for the TR accounting vertical: runs the uploaded file through
    the CFO pipeline → TR accounting → board deck in one unattended pass and
    returns a single consolidated approval gate. Never auto-approves.
    """
    from app.agents.tr_vertical import run_tr_vertical

    job = await db.get(AnalysisJob, body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    if (
        job.org_id
        and job.org_id != current_user.org_id
        and current_user.role not in ("admin", "owner")
    ):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")
    if not job.file_path:
        raise HTTPException(status_code=400, detail="Job'a ait dosya yolu yok.")

    from app.agents.run_ledger import agent_run
    from app.platform.authority_matrix import load_active_rules

    authority_rules = await load_active_rules(
        str(job.org_id) if job.org_id else None, db
    )

    async with agent_run(
        db,
        pipeline="tr_vertical",
        org_id=str(job.org_id) if job.org_id else None,
        job_id=body.job_id,
    ) as _run:
        result = await run_tr_vertical(
            job_id=body.job_id,
            file_path=job.file_path,
            file_type=job.file_type,
            org_id=str(job.org_id) if job.org_id else None,
            period=body.donem,
            company_name=body.company_name,
            authority_rules=authority_rules,
        )
        _run.node(result.stage)
        if any(e for e in result.errors):
            _run.row.error = "; ".join(result.errors)[:2000]
        if result.stage != "done":
            _run.row.status = "halted"
        elif result.approval_required:
            _run.row.status = "awaiting_review"
        _run.row.result_ref = {
            "stage": result.stage,
            "approval_required": result.approval_required,
            "board_deck_pdf_size": result.to_dict().get("board_deck_pdf_size"),
            "reconciliation": result.reconciliation,
            "confidence_breakdown": (result.cfo or {}).get("confidence_breakdown"),
            "min_confidence": (result.cfo or {}).get("min_confidence"),
        }

    # Persist the full THP journal for the defensibility packet.
    if result.accounting is not None:
        await _persist_muhasebe_journal(
            db,
            body.job_id,
            {**result.accounting, "yevmiye_kayitlari": result.accounting_journal or []},
        )

        # Queue the entries the authority matrix held back. The autopilot may
        # auto-post what policy lets it auto-post; it does not get to discard
        # what policy reserved for a human. This path produced the journal and
        # the sealable packet but never wrote a single review record, so the
        # related-party escalations, the low-confidence holds and the
        # owner-approval rules all evaporated — and /smmm-onay, the only place
        # a human reviews anything, stayed empty no matter what was uploaded.
        onay_eklendi = await _enqueue_smmm_review(
            db,
            job_id=body.job_id,
            org_id=str(job.org_id) if job.org_id else None,
            user_id=current_user.id,
            items=(result.accounting.get("onay_kuyrugu") or []),
            packs=await _org_packs(db, job.org_id),
        )
        await db.commit()
        if onay_eklendi:
            logger.info(
                "tr-vertical: %d kayıt SMMM onayına düştü (job=%s)",
                onay_eklendi, body.job_id,
            )

    # Record the generated board deck so it can be fetched later (GET below).
    if result.board_deck_pdf_path:
        existing = (
            await db.execute(
                select(Report)
                .where(
                    Report.job_id == body.job_id,
                    Report.report_type == "tr_board_deck",
                    Report.report_format == ReportFormat.PDF,
                )
                .order_by(desc(Report.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            existing.file_path = result.board_deck_pdf_path
        else:
            db.add(
                Report(
                    job_id=body.job_id,
                    report_type="tr_board_deck",
                    report_format=ReportFormat.PDF,
                    file_path=result.board_deck_pdf_path,
                )
            )
        await db.commit()

    logger.info(
        "TR vertical (API): job=%s stage=%s approval_required=%s",
        body.job_id, result.stage, result.approval_required,
    )
    return {
        "data": result.to_dict(),
        "error": ("; ".join(result.errors) or None) if result.errors else None,
        "meta": {"depth_level": 3, "auto_approved": False},
    }


@router.get("/muhasebe/tr-vertical/{job_id}/board-deck.pdf")
async def muhasebe_tr_vertical_board_deck(
    job_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download the board-deck PDF produced by the last TR-vertical run for this job."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    if (
        job.org_id
        and job.org_id != current_user.org_id
        and current_user.role not in ("admin", "owner")
    ):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")

    report = (
        await db.execute(
            select(Report)
            .where(
                Report.job_id == job_id,
                Report.report_type == "tr_board_deck",
                Report.report_format == ReportFormat.PDF,
            )
            .order_by(desc(Report.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not report or not report.file_path or not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="Yönetim kurulu sunumu bulunamadı.")

    return FileResponse(
        path=report.file_path,
        media_type="application/pdf",
        filename=f"yonetim-kurulu-{job_id}.pdf",
    )


@router.get("/muhasebe/{job_id}/yevmiye-dokumu.xml")
async def muhasebe_yevmiye_dokumu(
    job_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    donem: str | None = None,
) -> Response:
    """Aylık yevmiye dökümü — savunulabilirlik paketiyle aynı kayıtlardan.

    **Bu bir e-Defter değildir ve GİB'e beyan edilemez.** GİB'in e-Defteri
    XBRL GL'dir ve `edefter.xsd` ile doğrulanır; bu döküm o şemadan kök
    elemanda reddedilir. Beyan edilebilir defter için
    `GET /muhasebe/{job_id}/e-defter.xml` kullanın.

    Kaynak, `tr_muhasebe_journal` raporudur: SMMM'nin onayladığı ve paketin
    mühürlediği satırların ta kendisi.
    """
    from app.services.gib_edefter import EDefterGenerator
    from app.services.smmm_defensibility import DefensibilityError, _load_journal

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    if (
        job.org_id
        and job.org_id != current_user.org_id
        and current_user.role not in ("admin", "owner")
    ):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")

    settings = get_settings()
    if not settings.gib_vkn:
        raise HTTPException(
            status_code=503,
            detail="GİB VKN yapılandırılmamış — döküm üretilemez (GIB_VKN).",
        )

    try:
        journal = await _load_journal(db, job_id)
    except DefensibilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    org = await db.get(Organization, str(current_user.org_id)) if current_user.org_id else None
    from app.services.edefter_xbrl import EDefterError, ledger_period

    try:
        period, chosen = ledger_period(list(journal.get("yevmiye_kayitlari") or []), donem)
    except EDefterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    package = EDefterGenerator.generate_journal_xml(
        entries=[dict(e) for e in chosen],
        period=period,
        vkn=settings.gib_vkn,
        company_title=(org.name if org else "Şirket"),
    )
    if not package.is_balanced:
        # An unbalanced defter is not something to hand to the tax authority.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Yevmiye dengeli değil (borç {package.total_debit_cents} / "
                f"alacak {package.total_credit_cents}) — döküm üretilmedi."
            ),
        )

    return Response(
        content=package.journal_xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": content_disposition(f"yevmiye-dokumu-{period}-{job_id}.xml"),
            "X-Yevmiye-SHA256": package.sha256_hash,
            "X-Yevmiye-Entry-Count": str(package.entry_count),
            # Said in the response as well as the docstring: a client that only
            # reads headers must not mistake this for a filing.
            "X-Not-A-GIB-Filing": "true",
        },
    )



# ── e-Defter (XBRL GL) ───────────────────────────────────────────────────────
# The real thing: validated against the edefter.xsd GİB publishes, in the
# format its own samples use. Still unsigned — see the response headers.

async def _edefter_context(
    job_id: str, current_user: User, db: AsyncSession, donem: str | None = None
) -> tuple[list[dict], str, LedgerOwner]:
    """Shared preflight for both ledgers, so they cannot describe different books."""
    from app.core.branding import get_brand
    from app.services.edefter_xbrl import LedgerOwner
    from app.services.smmm_defensibility import DefensibilityError, _load_journal

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    if (
        job.org_id
        and job.org_id != current_user.org_id
        and current_user.role not in ("admin", "owner")
    ):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")

    settings = get_settings()
    if not settings.gib_vkn:
        raise HTTPException(
            status_code=503,
            detail="GİB VKN yapılandırılmamış — e-Defter üretilemez (GIB_VKN).",
        )

    try:
        journal = await _load_journal(db, job_id)
    except DefensibilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    org = (
        await db.get(Organization, str(current_user.org_id))
        if current_user.org_id else None
    )
    from app.services.edefter_xbrl import EDefterError, ledger_period

    # The period is the month the entries are in. It used to be read from a
    # `donem` field nothing wrote, falling back to the job's creation month.
    try:
        period, entries = ledger_period(list(journal.get("yevmiye_kayitlari") or []), donem)
    except EDefterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    brand = get_brand()

    owner = LedgerOwner(
        vkn=settings.gib_vkn,
        title=(org.name if org else "Şirket"),
        # Address, phone and accountant details are left blank rather than
        # filled with something plausible. GİB's format for the producer is
        # VKN##üretici##yazılım##sürüm.
        software_name=f"{settings.gib_vkn}##{brand.name}##{brand.name} e-Defter##1.0",
    )
    return [dict(e) for e in entries], period, owner


def _edefter_response(pkg: EDefterXBRL, job_id: str) -> Response:
    if not pkg.is_balanced:
        # An unbalanced ledger is not something to hand to the tax authority.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Defter dengeli değil (borç {pkg.total_debit_kurus} / "
                f"alacak {pkg.total_credit_kurus}) — e-Defter üretilmedi."
            ),
        )
    return Response(
        content=pkg.xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": content_disposition(f"{pkg.file_name}"),
            "X-EDefter-SHA256": pkg.sha256_hash,
            "X-EDefter-Entry-Count": str(pkg.entry_count),
            "X-EDefter-Line-Count": str(pkg.line_count),
            "X-EDefter-KDV-Unverified": str(pkg.kdv_unverified),
            # Structurally complete, legally incomplete. Said in the response
            # so a client that only reads headers cannot miss it — as a stable
            # code, because a header is latin-1 and the reason is Turkish prose.
            # The prose lives in the OpenAPI description, where it can be read.
            "X-EDefter-Filable": "false",
            "X-EDefter-Unfilable-Code": "unsigned-no-berat",
        },
    )


@router.get("/muhasebe/{job_id}/e-defter.xml")
async def muhasebe_edefter_yevmiye(
    job_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    donem: str | None = None,
) -> Response:
    """GİB e-Defter yevmiye defteri (XBRL GL) — `edefter.xsd`'den geçer.

    **Beyan edilebilir değildir.** Yükleyebilmek için mali mühür ya da nitelikli
    e-imza ile XAdES imzalanması ve beratının alınması gerekir; ikisi de bu
    sunucuda yok. Belge yapısal olarak tamdır, hukuken eksiktir — yanıt
    başlıkları bunu açıkça söyler.

    Kaynak, `tr_muhasebe_journal` raporudur: SMMM'nin onayladığı ve
    savunulabilirlik paketinin mühürlediği satırların ta kendisi. Beyan edilen
    defterin denetlenen kayıttan ayrışmaması bunun tek amacı.
    """
    from app.services.edefter_xbrl import EDefterError, EDefterXBRLGenerator

    entries, period, owner = await _edefter_context(job_id, current_user, db, donem)
    try:
        pkg = EDefterXBRLGenerator.generate_journal(
            entries, period=period, owner=owner
        )
    except EDefterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _edefter_response(pkg, job_id)


@router.get("/muhasebe/{job_id}/e-defter-kebir.xml")
async def muhasebe_edefter_kebir(
    job_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    donem: str | None = None,
) -> Response:
    """GİB e-Defter büyük defteri (kebir, XBRL GL).

    Kebir ikinci bir gerçek kaynağı değildir: aynı yevmiye satırlarının hesap
    kırılımında okunmuş hâlidir. GİB ikisinin tutmasını kontrol eder, ve tek
    kaynaktan türetmek tutmalarının tek yoludur.
    """
    from app.services.edefter_xbrl import EDefterError, EDefterXBRLGenerator

    entries, period, owner = await _edefter_context(job_id, current_user, db, donem)
    try:
        pkg = EDefterXBRLGenerator.generate_ledger(entries, period=period, owner=owner)
    except EDefterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _edefter_response(pkg, job_id)


async def _edefter_build(
    job_id: str, kind: str, current_user: User, db: AsyncSession, donem: str | None = None
) -> EDefterXBRL:
    from app.services.edefter_xbrl import EDefterError, EDefterXBRLGenerator

    if kind not in ("yevmiye", "kebir"):
        raise HTTPException(status_code=422, detail="kind yevmiye ya da kebir olmalı")
    entries, period, owner = await _edefter_context(job_id, current_user, db, donem)
    build = (
        EDefterXBRLGenerator.generate_journal if kind == "yevmiye"
        else EDefterXBRLGenerator.generate_ledger
    )
    try:
        pkg = build(entries, period=period, owner=owner)
    except EDefterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not pkg.is_balanced:
        raise HTTPException(status_code=409, detail="Defter dengeli değil — berat üretilmedi.")
    return pkg


@router.get("/muhasebe/{job_id}/e-defter-berat.xml")
async def muhasebe_edefter_berat(
    job_id: str,
    kind: str = "yevmiye",
    donem: str | None = None,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """e-Defter beratı — **önizleme**, bu sunucudaki imzasız defterden.

    Every value is derived from the defter file itself: entry count, size in
    MiB, the 391/191/600/601/602 tax detail, and the value that binds the pair.
    That last one is the defter's XAdES signature value — which an unsigned
    defter does not have. So this berat carries the defter's HashValue in its
    place and is a preview of the real one: once the taxpayer signs the defter
    with their mali mühür, the berat is regenerated from the signed file
    (`build_berat` takes it as it is) and then signed itself.

    **Beyan edilemez**, ve başlıklar bunu kod olarak söyler.
    """
    from app.services.edefter_berat import BeratError, build_berat

    pkg = await _edefter_build(job_id, kind, current_user, db, donem)
    try:
        berat = build_berat(pkg.xml.encode("utf-8"), defter_file_name=pkg.file_name)
    except BeratError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=berat.xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": content_disposition(berat.file_name),
            "X-EDefter-Berat-Of": pkg.file_name,
            # The tax detail is summed from the defter; entries booked gross
            # leave it short by their KDV.
            "X-EDefter-KDV-Unverified": str(pkg.kdv_unverified),
            "X-EDefter-Berat-Unique-ID": berat.unique_id,
            "X-EDefter-Berat-Size-MiB": berat.size_mib,
            "X-EDefter-Entry-Count": str(berat.number_of_entries or pkg.entry_count),
            "X-EDefter-Filable": "false",
            "X-EDefter-Unfilable-Code": "berat-preview-defter-unsigned",
        },
    )


@router.get("/muhasebe/{job_id}/e-defter/durum")
async def muhasebe_edefter_durum(
    job_id: str,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    donem: str | None = None,
) -> dict[str, Any]:
    """Beyana giden yolun her adımı, yapılıp yapılmadığıyla.

    A single "not filable" flag hides how far the file got. This lists the
    steps GİB's process has, in order, and marks only what actually happened
    on this server. Nothing is inferred as done because a later step would
    need it.
    """
    from app.services.edefter_berat import BeratError, build_berat

    settings = get_settings()
    steps: list[dict[str, Any]] = []
    defter_detail = ""
    berat_detail = "Defter olmadan berat olmaz."
    berat_ok = False
    try:
        pkg = await _edefter_build(job_id, "yevmiye", current_user, db, donem)
        defter_detail = f"{pkg.file_name} — {pkg.entry_count} kayıt, dengeli"
        if pkg.kdv_unverified:
            defter_detail += (
                f"; {pkg.kdv_unverified} kayıtta KDV ayrıştırılmadı — "
                "beratın vergi detayı eksik olabilir"
            )
        try:
            build_berat(pkg.xml.encode("utf-8"), defter_file_name=pkg.file_name)
            berat_ok = True
        except BeratError as exc:
            berat_detail = str(exc)
        defter_ok = True
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            raise
        defter_ok = False
        defter_detail = str(exc.detail)

    steps.append({"key": "defter", "label": "Yevmiye ve kebir üretildi",
                  "done": defter_ok, "detail": defter_detail})
    steps.append({"key": "defter_imzasi", "label": "Defter mali mühürle imzalandı",
                  "done": False,
                  "detail": "Bu sunucuda imzalayıcı yok — mükellefin mali mührü gerekir."})
    steps.append({"key": "berat", "label": "Berat üretildi",
                  "done": False,
                  "preview": berat_ok,
                  "detail": (
                      "Önizleme hazır; imzalı defterden yeniden üretilecek."
                      if berat_ok else (locals().get("berat_detail") or "Defter olmadan berat olmaz.")
                  )})
    steps.append({"key": "berat_imzasi", "label": "Berat mali mühürle imzalandı",
                  "done": False, "detail": "Defter imzasından sonra gelir."})
    steps.append({"key": "paket", "label": "Yükleme paketi (VKN-YYYYAA-YB-000000.zip)",
                  "done": False, "detail": "İki imza olmadan paket kurulmaz."})
    steps.append({"key": "gonderim", "label": "GİB'e gönderildi",
                  "done": False,
                  "detail": (
                      f"Web servis istemcisi hazır (ortam: {settings.gib_edefter_env}); "
                      "WS-Security imzalayıcısı yok, gönderim yapılmaz."
                  )})
    next_step = next((s for s in steps if not s["done"]), None)
    return {
        "data": {
            "job_id": job_id,
            "filable": False,
            "steps": steps,
            "next_step": next_step["key"] if next_step else None,
        },
        "error": None,
    }


@router.get("/muhasebe/onay-kuyrugu")
async def onay_kuyrugu_listele(
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    durum: str = "bekliyor",
) -> dict[str, Any]:
    """SMMM onay bekleyen kayıtları listele (Turkey pack)."""
    query = select(SMMMOnayKaydi).where(
        SMMMOnayKaydi.durum == durum,
    )
    if current_user.org_id:
        query = query.where(SMMMOnayKaydi.org_id == str(current_user.org_id))

    result = await db.execute(query.order_by(SMMMOnayKaydi.created_at.desc()).limit(100))
    kayitlar = result.scalars().all()

    return {
        "data": [
            {
                "id":                   k.id,
                "job_id":               k.job_id,
                "kayit_id":             k.kayit_id,
                "durum":                k.durum,
                "tx_description":       k.tx_description,
                "tx_amount_try":        float(k.tx_amount_try) if k.tx_amount_try else None,
                "otomatik_hesap_kodu":  k.otomatik_hesap_kodu,
                "otomatik_confidence":  float(k.otomatik_confidence) if k.otomatik_confidence else None,
                "onay_neden":           k.onay_neden,
                "created_at":          k.created_at.isoformat(),
            }
            for k in kayitlar
        ],
        "error": None,
    }


@router.post("/muhasebe/onayla/{onay_id}")
async def onayla(
    onay_id: str,
    body: OnayRequest,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner", "cfo")),
) -> dict[str, Any]:
    """SMMM: Kaydı onayla (Turkey pack)."""
    kayit = await db.get(SMMMOnayKaydi, onay_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı.")
    if kayit.durum != OnayDurumu.BEKLIYOR:
        raise HTTPException(status_code=409, detail=f"Kayıt zaten '{kayit.durum}' durumunda.")

    kayit.durum = OnayDurumu.ONAYLANDI
    kayit.onaylayan_user_id = current_user.id
    kayit.onay_zamani = datetime.now(UTC)
    kayit.onay_notu = body.onay_notu
    await db.commit()

    logger.info("SMMM onay: id=%s user=%s", onay_id, current_user.email)
    return {"data": {"onaylandi": True, "kayit_id": onay_id}, "error": None}


@router.post("/muhasebe/duzelt/{onay_id}")
async def duzelt(
    onay_id: str,
    body: DuzeltiRequest,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner", "cfo")),
) -> dict[str, Any]:
    """SMMM: Hesap kodunu düzelt ve onayla (Turkey pack)."""
    kayit = await db.get(SMMMOnayKaydi, onay_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı.")

    kayit.durum = OnayDurumu.DUZELTILDI
    kayit.onaylayan_user_id = current_user.id
    kayit.onay_zamani = datetime.now(UTC)
    kayit.duzeltilmis_hesap_kodu = body.yeni_hesap_kodu
    kayit.duzeltilmis_hesap_adi = body.yeni_hesap_adi
    kayit.duzeltme_aciklama = body.duzeltme_aciklama
    await db.commit()

    logger.info(
        "SMMM düzeltme: id=%s %s→%s user=%s",
        onay_id, kayit.otomatik_hesap_kodu, body.yeni_hesap_kodu, current_user.email,
    )
    return {
        "data": {
            "duzeltildi":        True,
            "eski_hesap_kodu":   kayit.otomatik_hesap_kodu,
            "yeni_hesap_kodu":   body.yeni_hesap_kodu,
        },
        "error": None,
    }


@router.post("/muhasebe/reddet/{onay_id}")
async def reddet(
    onay_id: str,
    body: ReddetRequest,
    current_user: User = Depends(require_tr_pack),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner", "cfo")),
) -> dict[str, Any]:
    """SMMM: Kaydı reddet (Turkey pack)."""
    kayit = await db.get(SMMMOnayKaydi, onay_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı.")

    kayit.durum = OnayDurumu.REDDEDILDI
    kayit.onaylayan_user_id = current_user.id
    kayit.onay_zamani = datetime.now(UTC)
    kayit.onay_notu = body.red_neden
    await db.commit()

    logger.info("SMMM red: id=%s user=%s neden=%s", onay_id, current_user.email, body.red_neden)
    return {"data": {"reddedildi": True, "kayit_id": onay_id}, "error": None}


@router.get("/muhasebe/mizan/{job_id}")
async def mizan_ozet(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Bir job için onaylanmış muhasebe kayıtlarından mizan özeti.
    Sadece onaylanmış veya düzeltilmiş kayıtları içerir.
    """
    result = await db.execute(
        select(SMMMOnayKaydi).where(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum.in_([OnayDurumu.ONAYLANDI, OnayDurumu.DUZELTILDI]),
        )
    )
    kayitlar = result.scalars().all()

    if not kayitlar:
        return {
            "data": {
                "job_id":   job_id,
                "mesaj":    "Onaylanmış muhasebe kaydı bulunamadı.",
                "mizan":    {},
                "toplam":   {"borc": 0, "alacak": 0},
            },
            "error": None,
        }

    # Mizan hesapla
    mizan: dict[str, dict[str, Any]] = {}
    for k in kayitlar:
        kayit_data = k.orijinal_kayit or {}
        # Düzeltme yapıldıysa hesap kodunu güncelle
        for satir in kayit_data.get("satirlar", []):
            kod = k.duzeltilmis_hesap_kodu or satir["hesap_kodu"]
            adi = k.duzeltilmis_hesap_adi or satir["hesap_adi"]
            if kod not in mizan:
                mizan[kod] = {"hesap_adi": adi, "borc": 0, "alacak": 0}
            mizan[kod]["borc"]   += satir.get("borc", 0)
            mizan[kod]["alacak"] += satir.get("alacak", 0)

    for h in mizan.values():
        h["bakiye"] = h["borc"] - h["alacak"]

    toplam_borc   = sum(h["borc"]   for h in mizan.values())
    toplam_alacak = sum(h["alacak"] for h in mizan.values())

    return {
        "data": {
            "job_id":        job_id,
            "kayit_sayisi":  len(kayitlar),
            "mizan":         mizan,
            "toplam": {
                "borc":    toplam_borc,
                "alacak":  toplam_alacak,
                "dengeli": toplam_borc == toplam_alacak,
            },
        },
        "error": None,
    }
