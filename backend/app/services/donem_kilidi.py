"""Closed months: what the accountant has signed off does not change afterwards.

Owner's decision (2026-11-21): a change that belongs to a closed month is booked as a
correction in the first open month, marked with the period it belongs to. The closed
month's figures, which may already have been declared and filed in the e-Defter,
stay exactly as they were.

This module holds the lock and the arithmetic of "the first open month". The ledger
(`services/ledger.append_job`) applies it, and so does a category
correction (`services/ledger_correction.py`). Accountant decisions on a closed
month are not covered yet (next slice).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.donem_kilidi import DonemKilidi
from app.models.organization import Organization

_DONEM = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class DonemHatasi(ValueError):
    """A month that cannot be closed: malformed, in the future, or already closed."""


def gecerli_donem(donem: str) -> bool:
    return bool(_DONEM.match(donem or ""))


def sonraki(donem: str) -> str:
    yil, ay = int(donem[:4]), int(donem[5:7])
    return f"{yil + 1}-01" if ay == 12 else f"{yil}-{ay + 1:02d}"


def ilk_acik_donem(donem: str, kilitli: set[str]) -> str:
    """The month itself if open, else the first month after it that is not closed."""
    while donem in kilitli:
        donem = sonraki(donem)
    return donem


async def kilitli_donemler(db: AsyncSession, org_id: str | None) -> set[str]:
    if not org_id:
        return set()
    return {
        str(d)
        for d in (
            await db.execute(select(DonemKilidi.donem).where(DonemKilidi.org_id == str(org_id)))
        ).scalars()
    }


async def kilitle(db: AsyncSession, org_id: str, donem: str, user_id: str | None) -> DonemKilidi:
    """Close `donem` for the organisation. The caller commits.

    Refused for a malformed month, a month that has not ended or begun (the future, so a
    typo cannot freeze months that have not happened), and a month already closed.
    """
    if not gecerli_donem(donem):
        raise DonemHatasi("Dönem YYYY-AA biçiminde olmalı (ör. 2026-01).")
    if donem > datetime.now(UTC).strftime("%Y-%m"):
        raise DonemHatasi("Gelecekteki bir dönem kapatılamaz.")
    # The same per-organisation lock the ledger correction takes: a close and a correction
    # are serial, and two closes of one month cannot both pass the check below.
    await db.execute(select(Organization.id).where(Organization.id == str(org_id)).with_for_update())
    if donem in await kilitli_donemler(db, org_id):
        raise DonemHatasi("Bu dönem zaten kapalı.")
    kilit = DonemKilidi(org_id=str(org_id), donem=donem, kilitleyen_user_id=user_id)
    try:
        async with db.begin_nested():
            db.add(kilit)
    except IntegrityError as exc:  # lost a race the lock could not see (no organisation row)
        raise DonemHatasi("Bu dönem zaten kapalı.") from exc
    return kilit
