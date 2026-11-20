"""What one organisation has taught the accounting agent, loaded in one place.

Two things the agent takes besides the transactions: how often this
organisation's accountant agreed with each evidence level (the measured trust
history) and the accounts the accountant has corrected recurring descriptions to
(learned rules). `/muhasebe/analiz` loaded both inline and the autopilot loaded
neither, so the same company was classified one way by hand and another by the
autopilot, and the trust it had earned went unused on the unattended path. Every
entry point now asks here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi


async def guven_gecmisi(db: AsyncSession, org_id: str | None) -> dict[str, tuple[int, int]]:
    """How often this organisation's SMMM agreed with each evidence level.

    Approved means the account was right, corrected means it was wrong. Read
    from the decisions already recorded; nothing is stored twice.
    """
    from app.services.accounting.guven import gecmisten_olc

    if not org_id:
        return {}
    rows = (
        await db.execute(
            select(SMMMOnayKaydi.orijinal_kayit, SMMMOnayKaydi.durum)
            .where(
                SMMMOnayKaydi.org_id == org_id,
                SMMMOnayKaydi.durum.in_([OnayDurumu.ONAYLANDI, OnayDurumu.DUZELTILDI]),
            )
            .order_by(desc(SMMMOnayKaydi.updated_at))
            .limit(5000)
        )
    ).all()
    return gecmisten_olc([
        (
            ((kayit or {}).get("guven") or {}).get("seviye"),
            str(durum),
            (kayit or {}).get("karar_turu") == "toplu",
        )
        for kayit, durum in rows
    ])


async def kurum_kurallari(db: AsyncSession, org_id: str | None) -> dict[str, Any]:
    """What this organisation's accountant has corrected before (a suggestion, not a verdict)."""
    from app.services.accounting.ogrenilmis_kural import kurallari_yukle

    return dict(await kurallari_yukle(db, org_id))


async def yukle(db: AsyncSession, org_id: str | None) -> dict[str, Any]:
    """Both, as the keyword arguments the accounting pipeline takes."""
    org = str(org_id) if org_id else None
    return {
        "guven_gecmisi": await guven_gecmisi(db, org),
        "kurum_kurallari": await kurum_kurallari(db, org),
    }
