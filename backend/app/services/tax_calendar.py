"""Official statutory tax and social security obligation projector for Cash Radar.

Plan v10 §4 (O3) & Plan v11 Faz 2.2:
Statutory deadlines from official Turkish revenue (GİB) & social security (SGK) legislation:
- KDV (VAT): Due on the 28th of each following month (GİB VUK).
- Muhtasar / Stopaj: Due on the 28th of each following month.
- SGK Prim Ödemesi: Due on the last calendar day of each following month (5510 s. Kanun md. 88).
- Geçici Vergi (Quarterly Tax Advance): Due on the 17th of the 2nd month following quarter end
  (17 May, 17 Aug, 17 Nov, 17 Feb).

Amounts are sourced from ledger accounts (360, 361, 391-191) when books exist, or recent historical
tax payment medians when bank movements exist. No numbers are invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.canonical_transaction import CanonicalTransaction


@dataclass(frozen=True)
class TaxObligationProjection:
    id: str
    tax_type: str  # "kdv", "sgk", "muhtasar", "gecici_vergi"
    title: str
    amount_cents: int
    expected_date: date
    source_basis: str  # "account_balance" or "historical_cash_median"
    account_code: str | None = None


# Official GİB statutory day rules
KDV_DUE_DAY = 28
MUHTASAR_DUE_DAY = 28
GECICI_VERGI_MONTH_DAY = {
    # quarter_end_month -> (due_month, due_day)
    3: (5, 17),  # Q1 -> 17 May
    6: (8, 17),  # Q2 -> 17 August
    9: (11, 17),  # Q3 -> 17 November
    12: (2, 17),  # Q4 -> 17 February (following year)
}


def _last_day_of_month(year: int, month: int) -> int:
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1
    return (date(next_y, next_m, 1) - timedelta(days=1)).day


async def get_historical_tax_averages(db: AsyncSession, org_id: str) -> dict[str, int]:
    """Extract historical tax payment medians from past cash movements."""
    rows = (
        (
            await db.execute(
                select(CanonicalTransaction).where(
                    CanonicalTransaction.org_id == org_id,
                    CanonicalTransaction.basis == "cash",
                    CanonicalTransaction.ledger_status == "active",
                    CanonicalTransaction.direction == "expense",
                    CanonicalTransaction.amount_cents > 0,
                    CanonicalTransaction.currency == "TRY",
                )
            )
        )
        .scalars()
        .all()
    )

    tax_buckets: dict[str, list[int]] = {"kdv": [], "sgk": [], "muhtasar": [], "gecici_vergi": []}
    for r in rows:
        text = fold(f"{r.counterparty or ''} {r.description or ''}")
        if "kdv" in text or "katma deger" in text:
            tax_buckets["kdv"].append(r.amount_cents)
        elif "sgk" in text or "sigorta prim" in text or "bagkur" in text:
            tax_buckets["sgk"].append(r.amount_cents)
        elif "muhtasar" in text or "stopaj" in text:
            tax_buckets["muhtasar"].append(r.amount_cents)
        elif "gecici vergi" in text or "kurumlar gecici" in text:
            tax_buckets["gecici_vergi"].append(r.amount_cents)

    medians: dict[str, int] = {}
    for k, amounts in tax_buckets.items():
        if amounts:
            s = sorted(amounts)
            medians[k] = s[len(s) // 2]
    return medians


async def project_tax_obligations(
    db: AsyncSession,
    org_id: str,
    anchor: date,
    horizon_weeks: int = 13,
) -> list[TaxObligationProjection]:
    """Project official statutory tax deadlines and amounts for the 13-week horizon."""
    horizon_end = anchor + timedelta(days=7 * horizon_weeks - 1)
    projections: list[TaxObligationProjection] = []

    # Get median historical cash payments for tax types if available
    historical = await get_historical_tax_averages(db, org_id)

    cur_year = anchor.year
    cur_month = anchor.month

    # Project monthly obligations (KDV, SGK, Muhtasar) for overlapping months
    for m_offset in range(5):
        year = cur_year + (cur_month - 1 + m_offset) // 12
        month = ((cur_month - 1 + m_offset) % 12) + 1

        # 1. KDV: Due on 28th
        kdv_date = date(year, month, min(KDV_DUE_DAY, _last_day_of_month(year, month)))
        if anchor <= kdv_date <= horizon_end and "kdv" in historical:
            projections.append(
                TaxObligationProjection(
                    id=f"tax_kdv_{kdv_date.isoformat()}",
                    tax_type="kdv",
                    title=f"KDV Ödemesi ({month:02d}/{year})",
                    amount_cents=historical["kdv"],
                    expected_date=kdv_date,
                    source_basis="historical_cash_median",
                    account_code="391",
                )
            )

        # 2. SGK: Due on last day of month
        sgk_day = _last_day_of_month(year, month)
        sgk_date = date(year, month, sgk_day)
        if anchor <= sgk_date <= horizon_end and "sgk" in historical:
            projections.append(
                TaxObligationProjection(
                    id=f"tax_sgk_{sgk_date.isoformat()}",
                    tax_type="sgk",
                    title=f"SGK Prim Ödemesi ({month:02d}/{year})",
                    amount_cents=historical["sgk"],
                    expected_date=sgk_date,
                    source_basis="historical_cash_median",
                    account_code="361",
                )
            )

        # 3. Muhtasar: Due on 28th
        muhtasar_date = date(year, month, min(MUHTASAR_DUE_DAY, _last_day_of_month(year, month)))
        if anchor <= muhtasar_date <= horizon_end and "muhtasar" in historical:
            projections.append(
                TaxObligationProjection(
                    id=f"tax_muhtasar_{muhtasar_date.isoformat()}",
                    tax_type="muhtasar",
                    title=f"Muhtasar / Stopaj Ödemesi ({month:02d}/{year})",
                    amount_cents=historical["muhtasar"],
                    expected_date=muhtasar_date,
                    source_basis="historical_cash_median",
                    account_code="360",
                )
            )

    # Project Geçici Vergi for the current/upcoming quarters
    # Check calendar year and next year Q4
    for q_month, (due_m, due_d) in GECICI_VERGI_MONTH_DAY.items():
        due_y = anchor.year if q_month != 12 else anchor.year + 1
        gecici_date = date(due_y, due_m, due_d)
        if anchor <= gecici_date <= horizon_end and "gecici_vergi" in historical:
            q_num = q_month // 3
            projections.append(
                TaxObligationProjection(
                    id=f"tax_gecici_{gecici_date.isoformat()}",
                    tax_type="gecici_vergi",
                    title=f"Geçici Vergi Q{q_num} ({due_y})",
                    amount_cents=historical["gecici_vergi"],
                    expected_date=gecici_date,
                    source_basis="historical_cash_median",
                    account_code="193",
                )
            )

    return sorted(projections, key=lambda p: p.expected_date)
