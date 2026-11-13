"""Recurring obligations detector & projector for Cash Radar.

Plan v10 §4 (O3) & Plan v11 Faz 2.1:
Identifies regular operational outflows (rent, payroll, subscriptions, accountant fees)
from past bank movements (basis="cash").
Strict rules (a wrong obligation is a false "you will run short"):
- at least 3 distinct calendar months of evidence, at an amount that is stable
  (within `AMOUNT_TOLERANCE` of the recent median): purchases that merely repeat
  a supplier's name are not obligations;
- payments that settled an open invoice are left out: the invoice is already an
  open item, so projecting its payments again would count it twice;
- an obligation not seen for `STALE_AFTER_MONTHS` is treated as ended.
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
from app.services.reconciliation import rows_settling_items

RECURRING_MIN_MONTHS = 3
AMOUNT_TOLERANCE = 0.15
STABLE_WINDOW = 6          # most recent payments judged for stability
STALE_AFTER_MONTHS = 2     # missed this many months in a row: assumed ended

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


def _utc(row: CanonicalTransaction):
    when = row.transaction_date
    return when.astimezone(UTC) if when.tzinfo else when


def _month_of(row: CanonicalTransaction) -> tuple[int, int]:
    when = _utc(row)
    return (when.year, when.month)


def _day_of(row: CanonicalTransaction) -> int:
    return _utc(row).day


def _date_of(row: CanonicalTransaction) -> date:
    return _utc(row).date()


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
    last_seen: date | None = None


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

    settling = await rows_settling_items(db, org_id)
    rows = [r for r in rows if r.id not in settling]

    # Group by recurrence key
    grouped: dict[str, list[CanonicalTransaction]] = defaultdict(list)
    for row in rows:
        key = recurrence_key(row.counterparty, row.description)
        if key:
            grouped[key].append(row)

    obligations: list[RecurringObligation] = []
    for key, items in grouped.items():
        # Judge the most recent payments: a rent that was raised is still a rent.
        recent = items[-STABLE_WINDOW:]
        amounts = sorted(r.amount_cents for r in recent)
        median_amount = amounts[len(amounts) // 2]
        stable = [
            r for r in recent if abs(r.amount_cents - median_amount) <= AMOUNT_TOLERANCE * median_amount
        ]
        months = {_month_of(r) for r in stable}
        if len(months) < RECURRING_MIN_MONTHS:
            continue

        median_day = sorted(_day_of(r) for r in stable)[len(stable) // 2]
        representative = stable[-1]
        label = representative.description or representative.counterparty or key.title()

        obligations.append(
            RecurringObligation(
                key=key,
                label=label,
                counterparty=representative.counterparty,
                amount_cents=median_amount,
                day_of_month=median_day,
                observed_months_count=len(months),
                source_row_ids=[r.id for r in stable[-5:]],
                last_seen=_date_of(representative),
            )
        )

    return obligations


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def project_recurring_obligations(
    obligations: list[RecurringObligation],
    anchor: date,
    horizon_weeks: int = 13,
) -> list[RecurringProjection]:
    """Project recurring obligations into future calendar days within the horizon."""
    horizon_end = anchor + timedelta(days=7 * horizon_weeks - 1)
    projections: list[RecurringProjection] = []

    for ob in obligations:
        if ob.last_seen is not None and _months_between(ob.last_seen, anchor) > STALE_AFTER_MONTHS:
            continue
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
