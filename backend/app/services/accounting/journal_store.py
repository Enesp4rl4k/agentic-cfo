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
    source the defensibility packet and the e-Defter itemise from — and write the
    same entries to `journal_entries` / `journal_lines` (A1.2 dual write; the JSON
    stays what outputs read until the shadow comparison has held)."""
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
    from app.services.accounting.journal_tables import yaz

    await yaz(db, job_id, full_result.get("yevmiye_kayitlari") or [])


def _kurus(onay_item: dict[str, Any]) -> int | None:
    """The amount in kuruş; a queue item from before 058 carries lira."""
    if onay_item.get("tx_amount_kurus") is not None:
        return int(onay_item["tx_amount_kurus"])
    if onay_item.get("tx_amount_try") is not None:
        return round(float(onay_item["tx_amount_try"]) * 100)
    return None


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

    Entry ids are stable across re-runs (`double_entry.kararli_kayit_id`). Rows
    still waiting from the previous run are replaced, not left to pile up.
    Decided rows (approved / corrected / rejected) are history and stay; an
    entry whose decision still applies — same entry, same proposed account —
    is not queued again. One whose proposed account changed is: the old
    decision was about a different classification.
    """
    if "tr" not in packs:
        return 0
    await db.execute(
        delete(SMMMOnayKaydi).where(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
        )
    )
    from app.services.accounting.approved_journal import gecerli_onay, onay_indeksi

    kararlar = onay_indeksi(
        (
            await db.execute(select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id))
        ).scalars().all()
    )
    added = 0
    for onay_item in items:
        if gecerli_onay(kararlar.get(str(onay_item["kayit_id"]), []), onay_item) is not None:
            continue
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
                tx_amount_kurus=_kurus(onay_item),
                tx_amount_try=(_kurus(onay_item) / 100) if _kurus(onay_item) is not None else None,
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
