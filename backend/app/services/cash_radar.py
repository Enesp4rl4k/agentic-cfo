"""Nakit Radarı: the next 13 weeks of open invoices against the last proven balance.

Plan v9 §K1 / Plan v10 §4 (O3) / Plan v11 Faz 2:
Deterministic, and only from what the company's documents say:

- Starting cash is the balance the latest bank statement closes on, and only
  when its running balances chain (`app.services.bank_balance`).
- Receivables land on their due date, moved by how late that customer really
  paid before (`reconciliation.payment_behaviour`); payables on their due date.
- What the documents do not date is not placed. A receivable still unpaid after
  its expected day has no day we could believe, so it is reported, not counted.
  An overdue payable is owed now, so it is counted in week 1.
- Recurring obligations (rent, payroll) are detected from past cash movements (≥3 months)
  and projected deterministically (`app.services.recurring_obligations`).
- Official statutory tax & SGK liabilities are projected from official calendar
  schedules (`app.services.tax_calendar`).
- Cheques & promissory notes are recognized directly via OpenItem.instrument.
- `not_included` dynamically lists only what cannot yet be derived from documents.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.services.reconciliation import payment_behaviour

HORIZON_WEEKS = 13
RECEIVABLE = "receivable"

NOT_INCLUDED_DEFAULT = (
    "Kira, maaş gibi düzenli ödemeler",
    "Vergi ve SGK yükümlülükleri",
    "Çek ve senetler",
)


def _fmt(cents: int) -> str:
    """Lira as the Turkish text around it writes it: ₺1.234,56."""
    sign = "-" if cents < 0 else ""
    swapped = f"{abs(cents) / 100:,.2f}".translate(str.maketrans(",.", ".,"))
    return f"{sign}₺{swapped}"


@dataclass(frozen=True)
class RadarItem:
    id: str
    counterparty: str | None
    description: str | None
    amount_cents: int
    due_date: str | None
    expected_date: str
    delay_days: int  # measured lateness applied; 0 when none is known
    is_overdue: bool
    instrument: str = "invoice"  # invoice | cheque | promissory_note | recurring | tax


@dataclass(frozen=True)
class RadarWeek:
    week: int
    start_date: str
    end_date: str
    inflow_cents: int
    outflow_cents: int
    net_cents: int
    # The balance when the starting cash is known; otherwise movement since the anchor.
    end_balance_cents: int
    receivables: list[dict[str, Any]]
    payables: list[dict[str, Any]]


@dataclass(frozen=True)
class Shortfall:
    week: int
    week_start: str
    week_end: str
    shortfall_cents: int  # the lowest the balance goes, below zero
    driver: str
    actions: list[dict[str, Any]]


@dataclass(frozen=True)
class CashRadar:
    anchor_date: str
    starting_cash_cents: int | None
    starting_cash_as_of: str | None
    weeks: list[RadarWeek]
    shortfall: Shortfall | None
    overdue_receivables: list[dict[str, Any]]
    overdue_payables_cents: int
    undated_receivables_cents: int
    undated_payables_cents: int
    beyond_horizon_cents: int
    other_currency_items: int
    not_included: list[str]
    recurring_payables_cents: int = 0
    tax_obligations_cents: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def proven_balance(db: AsyncSession, org_id: str) -> dict[str, Any] | None:
    """The latest closing balance a completed statement proved, if any did."""
    metas = (
        (
            await db.execute(
                select(AnalysisJob.result_metadata).where(
                    AnalysisJob.org_id == org_id,
                    AnalysisJob.status == JobStatus.COMPLETED,
                )
            )
        )
        .scalars()
        .all()
    )
    found = [m["closing_balance"] for m in metas if m and m.get("closing_balance")]
    return max(found, key=lambda c: c["date"], default=None)


def _weeks_from(anchor: date) -> list[tuple[date, date]]:
    return [
        (anchor + timedelta(days=7 * i), anchor + timedelta(days=7 * i + 6))
        for i in range(HORIZON_WEEKS)
    ]


def _actions(
    week: int, shortfall: int, collect: list[RadarItem], pay: list[RadarItem]
) -> list[dict[str, Any]]:
    """What a person could do about the gap: each names real money, none invents terms."""
    actions: list[dict[str, Any]] = []
    if collect:
        top = max(collect, key=lambda r: r.amount_cents)
        actions.append(
            {
                "type": "early_collection",
                "title": f"Tahsilatı öne çek: {top.counterparty or 'müşteri'}",
                "detail": (
                    f"{_fmt(top.amount_cents)} tutarındaki alacak {top.expected_date} "
                    f"tarihinde bekleniyor; {week}. haftadan önce tahsil edilirse açık küçülür."
                ),
                "amount_cents": top.amount_cents,
            }
        )
    if pay:
        top = max(pay, key=lambda p: p.amount_cents)
        actions.append(
            {
                "type": "defer_payment",
                "title": f"Ödemeyi konuş: {top.counterparty or 'tedarikçi'}",
                "detail": (
                    f"{week}. haftadaki {_fmt(top.amount_cents)} ödemesi açığı doğuruyor; "
                    "vade uzatımı için tedarikçiyle görüşülebilir."
                ),
                "amount_cents": top.amount_cents,
            }
        )
    actions.append(
        {
            "type": "financing",
            "title": f"Finansman ihtiyacı: {_fmt(shortfall)}",
            "detail": f"Açık {week}. haftada başlıyor; bu tutar için kredi limiti gerekebilir.",
            "amount_cents": shortfall,
        }
    )
    return actions


async def compute_cash_radar(
    db: AsyncSession,
    org_id: str,
    anchor_date: date | None = None,
) -> CashRadar:
    """The 13 weeks from `anchor_date` (today, UTC, by default)."""
    anchor = anchor_date or datetime.now(UTC).date()
    ranges = _weeks_from(anchor)
    horizon_end = ranges[-1][1]
    balance = await proven_balance(db, org_id)
    delays = {
        (d["counterparty"], d["direction"]): max(0, round(d["average_delay_days"]))
        for d in await payment_behaviour(db, org_id)
    }
    items = (
        (
            await db.execute(
                select(OpenItem)
                .where(OpenItem.org_id == org_id, OpenItem.status == "open")
                .order_by(OpenItem.due_date, OpenItem.issue_date)
            )
        )
        .scalars()
        .all()
    )

    receivables: list[list[RadarItem]] = [[] for _ in ranges]
    payables: list[list[RadarItem]] = [[] for _ in ranges]
    overdue_receivables: list[dict[str, Any]] = []
    overdue_payables = undated_rec = undated_pay = beyond = other_currency = 0
    has_cheques = False

    for item in items:
        remaining = item.amount_cents - item.paid_cents
        if remaining <= 0:
            continue
        if item.currency != "TRY":
            other_currency += 1  # counted, never converted at a rate we chose
            continue
        if item.instrument in ("cheque", "promissory_note"):
            has_cheques = True

        receivable = item.direction == RECEIVABLE
        if item.due_date is None:
            if receivable:
                undated_rec += remaining
            else:
                undated_pay += remaining
            continue
        delay = delays.get((item.counterparty or "", item.direction), 0) if receivable else 0
        expected = item.due_date + timedelta(days=delay)
        entry = RadarItem(
            id=item.id,
            counterparty=item.counterparty,
            description=item.description,
            amount_cents=remaining,
            due_date=item.due_date.isoformat(),
            expected_date=expected.isoformat(),
            delay_days=delay,
            is_overdue=expected < anchor,
            instrument=item.instrument,
        )
        if expected > horizon_end:
            beyond += remaining
        elif expected < anchor and receivable:
            overdue_receivables.append(asdict(entry))
        elif expected < anchor:
            overdue_payables += remaining
            payables[0].append(entry)
        else:
            index = (expected - anchor).days // 7
            (receivables if receivable else payables)[index].append(entry)

    # 1. Recurring obligations (rent, payroll, subscriptions)
    from app.services.recurring_obligations import (
        detect_recurring_obligations,
        project_recurring_obligations,
    )

    recurring_obs = await detect_recurring_obligations(db, org_id)
    recurring_projections = project_recurring_obligations(recurring_obs, anchor, HORIZON_WEEKS)
    total_recurring_cents = 0
    for r_proj in recurring_projections:
        idx = (r_proj.expected_date - anchor).days // 7
        if 0 <= idx < HORIZON_WEEKS:
            entry = RadarItem(
                id=r_proj.id,
                counterparty=r_proj.counterparty,
                description=r_proj.description,
                amount_cents=r_proj.amount_cents,
                due_date=r_proj.expected_date.isoformat(),
                expected_date=r_proj.expected_date.isoformat(),
                delay_days=0,
                is_overdue=False,
                instrument="recurring",
            )
            payables[idx].append(entry)
            total_recurring_cents += r_proj.amount_cents

    # 2. Statutory tax & SGK liabilities
    from app.services.tax_calendar import project_tax_obligations

    tax_projections = await project_tax_obligations(db, org_id, anchor, HORIZON_WEEKS)
    total_tax_cents = 0
    for t_proj in tax_projections:
        idx = (t_proj.expected_date - anchor).days // 7
        if 0 <= idx < HORIZON_WEEKS:
            entry = RadarItem(
                id=t_proj.id,
                counterparty="GİB / SGK",
                description=t_proj.title,
                amount_cents=t_proj.amount_cents,
                due_date=t_proj.expected_date.isoformat(),
                expected_date=t_proj.expected_date.isoformat(),
                delay_days=0,
                is_overdue=False,
                instrument="tax",
            )
            payables[idx].append(entry)
            total_tax_cents += t_proj.amount_cents

    # Dynamic not_included list
    not_included: list[str] = []
    if not recurring_projections:
        not_included.append("Kira, maaş gibi düzenli ödemeler")
    if not tax_projections:
        not_included.append("Vergi ve SGK yükümlülükleri")
    if not has_cheques:
        not_included.append("Çek ve senetler")

    weeks: list[RadarWeek] = []
    running = balance["balance_cents"] if balance else 0
    lowest: tuple[int, int] | None = None  # (balance, week index)
    first_gap: int | None = None
    for i, (start, end) in enumerate(ranges):
        inflow = sum(r.amount_cents for r in receivables[i])
        outflow = sum(p.amount_cents for p in payables[i])
        running += inflow - outflow
        if balance and running < 0:
            first_gap = i if first_gap is None else first_gap
            lowest = (running, i) if lowest is None or running < lowest[0] else lowest
        weeks.append(
            RadarWeek(
                week=i + 1,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                inflow_cents=inflow,
                outflow_cents=outflow,
                net_cents=inflow - outflow,
                end_balance_cents=running,
                receivables=[asdict(r) for r in receivables[i]],
                payables=[asdict(p) for p in payables[i]],
            )
        )

    shortfall: Shortfall | None = None
    if first_gap is not None and lowest is not None:
        amount = -lowest[0]
        pays = payables[first_gap]
        top = max(pays, key=lambda p: p.amount_cents) if pays else None
        driver = (
            f"{first_gap + 1}. haftada {top.counterparty or 'bir tedarikçiye'} "
            f"{_fmt(top.amount_cents)} ödemesi bakiyeyi eksiye düşürüyor."
            if top
            else f"{first_gap + 1}. haftada çıkışlar mevcut nakdi aşıyor."
        )
        collect = [r for week in receivables[first_gap + 1 :] for r in week]
        shortfall = Shortfall(
            week=first_gap + 1,
            week_start=ranges[first_gap][0].isoformat(),
            week_end=ranges[first_gap][1].isoformat(),
            shortfall_cents=amount,
            driver=driver,
            actions=_actions(first_gap + 1, amount, collect, pays),
        )

    return CashRadar(
        anchor_date=anchor.isoformat(),
        starting_cash_cents=balance["balance_cents"] if balance else None,
        starting_cash_as_of=balance["date"] if balance else None,
        weeks=weeks,
        shortfall=shortfall,
        overdue_receivables=overdue_receivables,
        overdue_payables_cents=overdue_payables,
        undated_receivables_cents=undated_rec,
        undated_payables_cents=undated_pay,
        beyond_horizon_cents=beyond,
        other_currency_items=other_currency,
        not_included=not_included,
        recurring_payables_cents=total_recurring_cents,
        tax_obligations_cents=total_tax_cents,
    )
