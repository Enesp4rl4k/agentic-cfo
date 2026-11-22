"""Which currency an organisation's figures are in: the lookups behind `core/currency_totals.effective_base`."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import DEFAULT_BASE, EffectiveBase, effective_base, normalise
from app.models.canonical_transaction import CanonicalTransaction
from app.models.organization import Organization
from app.services.ledger_documents import EXCLUDED


async def confirmed_base_of(db: AsyncSession, org_id: str) -> str | None:
    """The organisation's CONFIRMED base currency, or None.

    `Organization.base_currency` has a column default of "USD", so a stored value is not a choice:
    only one an owner or admin confirmed (`base_currency_confirmed_at`) counts.
    """
    row = (await db.execute(
        select(Organization.base_currency, Organization.base_currency_confirmed_at)
        .where(Organization.id == org_id)
    )).first()
    if row is None or row[1] is None:
        return None
    return normalise(row[0]) or None


async def effective_base_of(db: AsyncSession, org_id: str) -> EffectiveBase:
    """The headline currency of this organisation's figures: the one function every surface uses
    (`core/currency_totals.effective_base`), over the currencies its ledger holds."""
    counts = {
        str(code): int(n) for code, n in (await db.execute(
            select(CanonicalTransaction.currency, func.count(CanonicalTransaction.id)).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.ledger_status != EXCLUDED,
                CanonicalTransaction.corrects_id.is_(None),
            ).group_by(CanonicalTransaction.currency)
        )).all()
    }
    return effective_base(await confirmed_base_of(db, org_id), counts)


async def base_currency_of(db: AsyncSession, org_id: str) -> str:
    """The currency a computation over this organisation's rows runs on (`EffectiveBase.run_currency`)."""
    return (await effective_base_of(db, org_id)).run_currency or DEFAULT_BASE
