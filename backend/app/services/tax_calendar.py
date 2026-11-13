"""Tax and social-security obligations for the Cash Radar.

Plan v10 §4 (O3), gaps G7 and G15.

What is projected, and from what:

- **Amounts** come only from this company's own bank history: the median of past
  cash payments *to the tax office or SGK* (see `_classify`). Nothing is taken from
  ledger balances and no rate is applied, so no figure is invented. A tax never
  seen in the bank history is not projected, and the radar says so.
- **Dates** follow the statutory day rules in `DUE_RULES`. Those rules are written
  from memory of the legislation and are **not yet checked against GİB/SGK's own
  text** (`due_rules_verified` is False). Where a due day falls on a weekend the
  payment moves to the next working day; official holidays are not known here.
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
    source_basis: str  # always "historical_cash_median"
    account_code: str | None = None
    due_rules_verified: bool = False


# Day-of-month rules. UNVERIFIED against the official text: see the module docstring.
due_rules_verified = False
KDV_DUE_DAY = 28
MUHTASAR_DUE_DAY = 28
SGK_DUE = "last day of the month"
# Provisional tax: 17th of the 2nd month after the quarter ends.
# quarter number -> (due month, due day, due year is the quarter's year + this)
GECICI_VERGI_DUE = {
    1: (5, 17, 0),
    2: (8, 17, 0),
    3: (11, 17, 0),
    4: (2, 17, 1),
}

# A payment is a tax payment only if it names the authority it went to. A word like
# "KDV" alone also appears in supplier payments ("KDV dahil") and "sigorta prim" in
# every insurance premium.
_AUTHORITY = ("vergi dairesi", "gib", "maliye", "tahakkuk", "beyanname", "vergi odeme")
_SGK = ("sgk", "sosyal guvenlik", "bagkur", "prim hizmet")
_NOT_A_TAX = ("dahil", "haric", "fatura")


def _classify(counterparty: str | None, description: str | None) -> str | None:
    text = fold(f"{counterparty or ''} {description or ''}")
    if any(w in text for w in _SGK):
        return "sgk"
    if not any(w in text for w in _AUTHORITY) or any(w in text for w in _NOT_A_TAX):
        return None
    if "gecici" in text:
        return "gecici_vergi"
    if "kdv" in text or "katma deger" in text:
        return "kdv"
    if "muhtasar" in text or "stopaj" in text:
        return "muhtasar"
    return None


def _last_day_of_month(year: int, month: int) -> int:
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1
    return (date(next_y, next_m, 1) - timedelta(days=1)).day


def _next_working_day(day: date) -> date:
    """A deadline on Saturday or Sunday falls on the Monday after."""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


async def get_historical_tax_averages(db: AsyncSession, org_id: str) -> dict[str, int]:
    """Median of past cash payments to the tax office / SGK, per kind of tax."""
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

    buckets: dict[str, list[int]] = {"kdv": [], "sgk": [], "muhtasar": [], "gecici_vergi": []}
    for r in rows:
        kind = _classify(r.counterparty, r.description)
        if kind:
            buckets[kind].append(r.amount_cents)

    medians: dict[str, int] = {}
    for kind, amounts in buckets.items():
        if amounts:
            s = sorted(amounts)
            medians[kind] = s[len(s) // 2]
    return medians


async def project_tax_obligations(
    db: AsyncSession,
    org_id: str,
    anchor: date,
    horizon_weeks: int = 13,
) -> list[TaxObligationProjection]:
    """Statutory deadlines inside the horizon, with amounts from past payments."""
    horizon_end = anchor + timedelta(days=7 * horizon_weeks - 1)
    historical = await get_historical_tax_averages(db, org_id)
    found: dict[str, TaxObligationProjection] = {}

    def add(kind: str, label: str, due: date, account: str, key: str) -> None:
        due = _next_working_day(due)
        if kind in historical and anchor <= due <= horizon_end:
            found.setdefault(
                key,
                TaxObligationProjection(
                    id=f"tax_{kind}_{due.isoformat()}",
                    tax_type=kind,
                    title=label,
                    amount_cents=historical[kind],
                    expected_date=due,
                    source_basis="historical_cash_median",
                    account_code=account,
                ),
            )

    # Monthly obligations: the month of the deadline, a month back and a few ahead.
    for m_offset in range(-1, 5):
        year = anchor.year + (anchor.month - 1 + m_offset) // 12
        month = (anchor.month - 1 + m_offset) % 12 + 1
        last = _last_day_of_month(year, month)
        tag = f"{month:02d}/{year}"
        add("kdv", f"KDV Ödemesi ({tag})", date(year, month, min(KDV_DUE_DAY, last)), "391", f"kdv{tag}")
        add("sgk", f"SGK Prim Ödemesi ({tag})", date(year, month, last), "361", f"sgk{tag}")
        add(
            "muhtasar",
            f"Muhtasar / Stopaj Ödemesi ({tag})",
            date(year, month, min(MUHTASAR_DUE_DAY, last)),
            "360",
            f"muh{tag}",
        )

    # Provisional tax: the previous year's Q4 is due in February of this one.
    for quarter_year in (anchor.year - 1, anchor.year):
        for quarter, (due_m, due_d, plus) in GECICI_VERGI_DUE.items():
            add(
                "gecici_vergi",
                f"Geçici Vergi Q{quarter} ({quarter_year})",
                date(quarter_year + plus, due_m, due_d),
                "193",
                f"gec{quarter}{quarter_year}",
            )

    return sorted(found.values(), key=lambda p: p.expected_date)
