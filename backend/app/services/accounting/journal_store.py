"""Saving what the TR accounting pipeline produced: the journal and its review rows.

`POST /muhasebe/tr-vertical` did this inline; `POST /runs/{id}/resume` re-drove
the same pipeline and did none of it, so a resumed run had a result nobody
could open: no journal for the e-Defter or the defensibility packet, and no
review rows for /smmm-onay. Both now call `persist_tr_vertical_result`.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.report import Report, ReportFormat
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi

logger = logging.getLogger(__name__)

MUHASEBE_JOURNAL_REPORT = "tr_muhasebe_journal"


async def org_packs(db: AsyncSession, org_id: str | None) -> list[str]:
    if not org_id:
        return []
    from app.services.regional.packs import normalize_packs

    org = await db.get(Organization, str(org_id))
    return normalize_packs(getattr(org, "regional_packs", None)) if org else []


async def persist_journal(db: AsyncSession, job_id: str, full_result: dict[str, Any]) -> None:
    """Upsert the full THP journal for a job as a JSON Report — the durable
    source the defensibility packet and the e-Defter itemise from."""
    existing = (
        await db.execute(
            select(Report)
            .where(
                Report.job_id == job_id,
                Report.report_type == MUHASEBE_JOURNAL_REPORT,
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
                report_type=MUHASEBE_JOURNAL_REPORT,
                report_format=ReportFormat.JSON,
                data=full_result,
            )
        )


async def enqueue_review(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str | None,
    user_id: str,
    items: list[dict[str, Any]],
    packs: list[str],
) -> int:
    """Write the review records for entries policy reserved for a human.

    A re-run of the pipeline produces a new journal with new entry ids, so the
    rows still waiting from the previous run point at entries that no longer
    exist. They are replaced, not left to pile up as duplicates in the queue.
    Decided rows (approved / corrected / rejected) are history and stay.
    """
    if "tr" not in packs:
        return 0
    await db.execute(
        delete(SMMMOnayKaydi).where(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
        )
    )
    added = 0
    for onay_item in items:
        db.add(
            SMMMOnayKaydi(
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
            )
        )
        added += 1
    return added


async def persist_tr_vertical_result(
    db: AsyncSession, *, job_id: str, org_id: str | None, user_id: str, result: Any
) -> int:
    """Journal + review rows for a `TRVerticalResult`. Returns rows queued."""
    if result.accounting is None:
        return 0
    await persist_journal(
        db, job_id, {**result.accounting, "yevmiye_kayitlari": result.accounting_journal or []}
    )
    # The autopilot may auto-post what policy lets it auto-post; it does not get
    # to discard what policy reserved for a human.
    queued = await enqueue_review(
        db,
        job_id=job_id,
        org_id=org_id,
        user_id=user_id,
        items=(result.accounting.get("onay_kuyrugu") or []),
        packs=await org_packs(db, org_id),
    )
    await db.commit()
    if queued:
        logger.info("tr-vertical: %d kayit SMMM onayina dustu (job=%s)", queued, job_id)
    return queued
