"""Every client's upcoming deadlines in one list: the accountant's month at a glance.

The tax calendar existed only per company, inside the Cash Radar, and showed a tax
only if that company had paid it from its bank before. An accountant needs the
other view: across all clients, what falls due next.

What is and is not claimed, so nothing reads as more certain than it is:
* **Dates** come from `tax_calendar.statutory_deadlines`, whose day rules are not
  yet checked against GİB/SGK's own text (`kurallar_dogrulandi` is False in every
  response). Weekend deadlines move to Monday; official holidays are not known.
* **Amounts** appear only when *that client* has paid that tax from its bank before
  (the median of its own payments). Otherwise the amount is empty, never estimated.
* **Liability** is not known: whether a client has employees (SGK) or pays
  provisional tax. `gecmiste_odeme_var` says which taxes it has actually paid.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smmm_portal import SMMMMusteriKayit
from app.services import tax_calendar

EN_FAZLA_GUN = 120


async def musteri_takvimi(
    db: AsyncSession, muhasebeci_id: str, anchor: date, gun: int = 45
) -> dict[str, Any]:
    """The statutory deadlines of every active client of this accountant, nearest first."""
    gun = max(1, min(int(gun), EN_FAZLA_GUN))
    son = anchor + timedelta(days=gun - 1)
    musteriler = (
        await db.execute(
            select(SMMMMusteriKayit).where(
                SMMMMusteriKayit.muhasebeci_id == muhasebeci_id,
                SMMMMusteriKayit.is_active.is_(True),
            )
        )
    ).scalars().all()
    tarihler = tax_calendar.statutory_deadlines(anchor, son)

    kalemler: list[dict[str, Any]] = []
    for m in musteriler:
        # Amounts from the client's own organisation only. A client from before M1 has
        # no organisation of its own: its money is mixed into the accountant's, so no
        # amount is read for it rather than one that belongs to someone else.
        gecmis = (
            await tax_calendar.get_historical_tax_averages(db, str(m.client_org_id))
            if m.client_org_id else {}
        )
        for d in tarihler:
            kalemler.append({
                "tarih": d.due.isoformat(),
                "tur": d.kind,
                "baslik": d.label,
                "musteri_id": str(m.id),
                "firma_adi": m.firma_adi,
                "client_org_id": m.client_org_id,
                "tutar_kurus": gecmis.get(d.kind),
                "gecmiste_odeme_var": d.kind in gecmis,
            })
    kalemler.sort(key=lambda k: (k["tarih"], k["firma_adi"] or "", k["tur"]))
    return {
        "baslangic": anchor.isoformat(),
        "bitis": son.isoformat(),
        "kalemler": kalemler,
        "kurallar_dogrulandi": tax_calendar.due_rules_verified,
    }
