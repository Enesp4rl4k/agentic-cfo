"""Recurring obligations detector & projector for Cash Radar.

Plan v10 §4 (O3) & Plan v11 Faz 2.1:
Identifies regular operational outflows (rent, payroll, subscriptions, accountant fees)
from past bank movements (basis="cash").
Strict Rule: Requires at least 3 distinct calendar months of historical evidence.
Every projection cites its source rows; none invents obligations.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.canonical_transaction import CanonicalTransaction

RECURRING_MIN_MONTHS = 3

_AY_ADLARI = frozenset(
    {
        "ocak",
        "subat",
        "mart",
        "nisan",
        "mayis",
        "haziran",
        "temmuz",
        "agustos",
        "eylul",
        "ekim",
        "kasim",
        "aralik",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)

_NOISE_TERMS = frozenset(
    {
        "eft",
        "havale",
        "odeme",
        "odemesi",
        "bedeli",
        "fatura",
        "tahsili",
        "giden",
        "gelen",
        "hesap",
        "hesabi",
        "no",
        "nolu",
    }
)


def recurrence_key(counterparty: str | None, description: str | None) -> str:
    """Normalize text into a stable recurrence key by removing month names and transaction noise."""
    combined = f"{counterparty or ''} {description or ''}"
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", fold(combined))
        if w not in _AY_ADLARI and w not in _NOISE_TERMS and len(w) > 1 and not w.isdigit()
    ]
    return " ".join(sorted(set(words[:3]))) if words else ""


@dataclass(frozen=True)
class RecurringObligation:
    key: str
    label: str
    counterparty: str | None
    amount_cents: int
    day_of_month: int
    observed_months_count: int
    source_row_ids: list[str]


@dataclass(frozen=True)
class RecurringProjection:
    id: str
    key: str
    counterparty: str | None
    description: str
    amount_cents: int
    expected_date: date
    is_recurring: bool = True
    evidence_count: int = 0


async def detect_recurring_obligations(db: AsyncSession, org_id: str) -> list[RecurringObligation]:
    """Detect recurring payments from historical cash transactions in the ledger."""
    rows = (
        (
            await db.execute(
                select(CanonicalTransaction)
                .where(
                    CanonicalTransaction.org_id == org_id,
                    CanonicalTransaction.basis == "cash",
                    CanonicalTransaction.ledger_status == "active",
                    CanonicalTransaction.direction == "expense",
                    CanonicalTransaction.amount_cents > 0,
                    CanonicalTransaction.currency == "TRY",
                )
                .order_by(CanonicalTransaction.transaction_date)
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return []

    # Group by recurrence key
    grouped: dict[str, list[CanonicalTransaction]] = defaultdict(list)
    for row in rows:
        key = recurrence_key(row.counterparty, row.description)
        if key:
            grouped[key].append(row)

    obligations: list[RecurringObligation] = []
    for key, items in grouped.items():
        # Check distinct months
        months = {
            (row.transaction_date.astimezone(UTC).year, row.transaction_date.astimezone(UTC).month)
            if row.transaction_date.tzinfo
            else (row.transaction_date.year, row.transaction_date.month)
            for row in items
        }
        if len(months) < RECURRING_MIN_MONTHS:
            continue

        # Sort amounts to pick median amount
        amounts = sorted(r.amount_cents for r in items)
        median_amount = amounts[len(amounts) // 2]

        # Calculate median day of month
        days = sorted(
            r.transaction_date.astimezone(UTC).day
            if r.transaction_date.tzinfo
            else r.transaction_date.day
            for r in items
        )
        median_day = days[len(days) // 2]

        representative = items[-1]
        label = representative.description or representative.counterparty or key.title()

        obligations.append(
            RecurringObligation(
                key=key,
                label=label,
                counterparty=representative.counterparty,
                amount_cents=median_amount,
                day_of_month=median_day,
                observed_months_count=len(months),
                source_row_ids=[r.id for r in items[-5:]],
            )
        )

    return obligations


def project_recurring_obligations(
    obligations: list[RecurringObligation],
    anchor: date,
    horizon_weeks: int = 13,
) -> list[RecurringProjection]:
    """Project recurring obligations into future calendar days within the horizon."""
    horizon_end = anchor + timedelta(days=7 * horizon_weeks - 1)
    projections: list[RecurringProjection] = []

    for ob in obligations:
        # Check each month overlapping with the horizon
        cur_year = anchor.year
        cur_month = anchor.month

        # Check up to 4 calendar months forward
        for m_offset in range(5):
            year = cur_year + (cur_month - 1 + m_offset) // 12
            month = ((cur_month - 1 + m_offset) % 12) + 1

            # Determine actual valid day for this month (e.g. handle Feb 28/29 or day 31)
            # Find last day of month:
            next_m = month + 1 if month < 12 else 1
            next_m_y = year if month < 12 else year + 1
            last_day = (date(next_m_y, next_m, 1) - timedelta(days=1)).day
            target_day = min(ob.day_of_month, last_day)

            projected_date = date(year, month, target_day)
            if anchor <= projected_date <= horizon_end:
                projections.append(
                    RecurringProjection(
                        id=f"rec_{ob.key}_{projected_date.isoformat()}",
                        key=ob.key,
                        counterparty=ob.counterparty,
                        description=f"{ob.label} (Düzenli Ödeme)",
                        amount_cents=ob.amount_cents,
                        expected_date=projected_date,
                        is_recurring=True,
                        evidence_count=ob.observed_months_count,
                    )
                )

    return projections
