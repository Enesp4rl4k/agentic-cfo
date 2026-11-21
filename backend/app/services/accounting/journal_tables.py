"""Writing and reading the journal tables (plan v11 A1.2, ADR 0001).

Dual write: `journal_store.persist_journal` keeps writing the JSON report every
output reads today and, in the same transaction, calls `yaz` to write the same
entries here. `yevmiye_tablodan` reads them back in the JSON's shape, so the
shadow comparison (`tests/test_journal_tables.py`) can run the accountant's
decisions over both sources and require the same trial balance to the kuruş.
Readers move to the tables only after that has held (A1.3).

An entry that does not balance, or a line that is both a debit and a credit, is
not written: the database would refuse it, and storing it would make the table
say something the books cannot. It is logged at ERROR with its id, so the gap
between the JSON and the tables is never silent.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob
from app.models.journal import JournalEntry, JournalLine

logger = logging.getLogger(__name__)


def _kurus(value: Any) -> int:
    return int(value or 0)


def _tarih(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _neden_yazilmaz(entry: dict[str, Any]) -> str | None:
    """Why an entry cannot go into the tables, or None when it can."""
    if not entry.get("kayit_id"):
        return "kayit_id yok"
    if not entry.get("tarih"):
        return "tarih yok"
    satirlar = entry.get("satirlar") or []
    if not satirlar:
        return "satır yok"
    for satir in satirlar:
        borc, alacak = _kurus(satir.get("borc")), _kurus(satir.get("alacak"))
        if borc < 0 or alacak < 0:
            return "negatif tutarlı satır"
        if borc and alacak:
            return "hem borç hem alacak taşıyan satır"
    borc = sum(_kurus(s.get("borc")) for s in satirlar)
    alacak = sum(_kurus(s.get("alacak")) for s in satirlar)
    if borc != alacak:
        return f"dengesiz (borç {borc} ≠ alacak {alacak})"
    return None


async def yaz(db: AsyncSession, job_id: str, entries: list[dict[str, Any]]) -> int:
    """Replace this job's journal rows with `entries`. Returns entries written.

    Does not commit: it runs inside the caller's transaction, next to the JSON.
    """
    job = await db.get(AnalysisJob, job_id)
    org_id = getattr(job, "org_id", None)

    eski = select(JournalEntry.id).where(JournalEntry.job_id == job_id)
    await db.execute(delete(JournalLine).where(JournalLine.entry_id.in_(eski)))
    await db.execute(delete(JournalEntry).where(JournalEntry.job_id == job_id))

    yazilan = 0
    gorulen: set[str] = set()
    for sira, entry in enumerate(entries):
        neden = _neden_yazilmaz(entry)
        kayit_id = str(entry.get("kayit_id") or "")
        if neden is None and kayit_id in gorulen:
            neden = "aynı kayit_id ikinci kez"
        if neden is not None:
            logger.error(
                "journal_tables: kayıt tabloya yazılmadı job=%s kayit_id=%s: %s",
                job_id, kayit_id or "?", neden,
            )
            continue
        gorulen.add(kayit_id)
        satirlar = entry["satirlar"]
        toplam = sum(_kurus(s.get("borc")) for s in satirlar)
        row = JournalEntry(
            job_id=job_id,
            org_id=org_id,
            kayit_id=kayit_id,
            sira=sira,
            tarih=_tarih(entry["tarih"]),
            tarih_kaynagi=entry.get("tarih_kaynagi") or "islem",
            aciklama=entry.get("aciklama") or "",
            kaynak_islem_id=str(entry.get("kaynak_islem_id") or ""),
            thp_hesap_kodu=str(entry.get("thp_hesap_kodu") or ""),
            confidence=float(entry.get("confidence", 1.0)),
            onay_gerekli=bool(entry.get("onay_gerekli")),
            onay_neden=entry.get("onay_neden") or "",
            kdv_durumu=entry.get("kdv_durumu") or "yok",
            guven=entry.get("guven") or None,
            authority=entry.get("authority") or None,
            toplam_borc_kurus=toplam,
            toplam_alacak_kurus=toplam,
        )
        db.add(row)
        await db.flush()
        for i, satir in enumerate(satirlar):
            db.add(JournalLine(
                entry_id=row.id,
                sira=i,
                hesap_kodu=str(satir.get("hesap_kodu") or ""),
                hesap_adi=satir.get("hesap_adi") or "",
                borc_kurus=_kurus(satir.get("borc")),
                alacak_kurus=_kurus(satir.get("alacak")),
                aciklama=satir.get("aciklama") or "",
            ))
        yazilan += 1
    await db.flush()
    return yazilan


async def yevmiye_tablodan(db: AsyncSession, job_id: str) -> list[dict[str, Any]]:
    """This job's entries from the tables, in the shape the JSON report holds them."""
    entries = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.job_id == job_id).order_by(JournalEntry.sira)
        )
    ).scalars().all()
    if not entries:
        return []
    lines = (
        await db.execute(
            select(JournalLine)
            .where(JournalLine.entry_id.in_([e.id for e in entries]))
            .order_by(JournalLine.entry_id, JournalLine.sira)
        )
    ).scalars().all()
    by_entry: dict[str, list[JournalLine]] = {}
    for line in lines:
        by_entry.setdefault(line.entry_id, []).append(line)

    out: list[dict[str, Any]] = []
    for e in entries:
        satirlar = [
            {
                "hesap_kodu": s.hesap_kodu,
                "hesap_adi": s.hesap_adi,
                "borc": int(s.borc_kurus),
                "alacak": int(s.alacak_kurus),
                "aciklama": s.aciklama,
            }
            for s in sorted(by_entry.get(e.id, []), key=lambda s: s.sira)
        ]
        out.append({
            "kayit_id": e.kayit_id,
            "tarih": e.tarih.isoformat(),
            "aciklama": e.aciklama,
            "toplam_borc": int(e.toplam_borc_kurus),
            "toplam_alacak": int(e.toplam_alacak_kurus),
            "dengeli": True,
            "confidence": e.confidence,
            "onay_gerekli": e.onay_gerekli,
            "onay_neden": e.onay_neden,
            "authority": e.authority or {},
            "thp_hesap_kodu": e.thp_hesap_kodu,
            "kaynak_islem_id": e.kaynak_islem_id,
            "tarih_kaynagi": e.tarih_kaynagi,
            "kdv_durumu": e.kdv_durumu,
            "guven": e.guven or {},
            "satirlar": satirlar,
        })
    return out
