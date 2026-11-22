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

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.currency_totals import (
    DEFAULT_BASE,
    currency_notes,
    fmt_money,
    normalise,
)
from app.models.open_item import OpenItem
from app.services.bank_accounts import proven_balances
from app.services.bank_balance import aged_basis, balance_age
from app.services.briefing_held import held_line as _held_line
from app.services.company_runway import company_runway
from app.services.payment_plan import effective_dates
from app.services.radar_held import BasisSplit, HeldDocuments, held_documents
from app.services.reconciliation import payment_behaviour

HORIZON_WEEKS = 13
RECEIVABLE = "receivable"

NOT_INCLUDED_DEFAULT = (
    "Kira, maaş gibi düzenli ödemeler",
    "Vergi ve SGK yükümlülükleri",
    "Çek ve senetler",
)


# How an item's date and amount are known. `known`: a document with a due date.
# `estimated`: inferred from history (recurring, tax, a customer's usual delay).
# `assumed`: placed by a rule, not by evidence (overdue payable in week 1, an approved
# plan change taken as the date). The radar's arithmetic is the same for all three;
# the basis only says how far each figure can be trusted.
KNOWN = "known"
ESTIMATED = "estimated"
ASSUMED = "assumed"


def _fmt(cents: int, currency: str | None = None) -> str:
    """An amount as the Turkish text around it writes it: ₺1.234,56 for lira, 1.234,56 USD otherwise."""
    return fmt_money(cents, currency)


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
    rescheduled: bool = False  # an approved plan change moved this payment off its document date
    basis: str = KNOWN  # known | estimated | assumed
    basis_reason: str = "document_due_date"  # machine-readable; see `_basis_of` and the projections
    basis_inputs: dict[str, Any] = field(default_factory=dict)  # what the estimate was computed from
    rules_verified: bool | None = None  # tax rows only: due-day rules checked against the official text


def _split(items: list[RadarItem]) -> BasisSplit:
    totals = {KNOWN: 0, ESTIMATED: 0, ASSUMED: 0}
    for it in items:
        totals[it.basis] += it.amount_cents
    return BasisSplit(totals[KNOWN], totals[ESTIMATED], totals[ASSUMED])


@dataclass(frozen=True)
class OpeningCash:
    """The balance the radar starts from, and how old it is."""

    balance_cents: int
    as_of: str  # the statement's closing date
    age_days: int  # anchor date minus as_of, never negative
    stale: bool  # age_days is over `stale_after_days`
    stale_after_days: int
    source_job_id: str | None
    source_filename: str | None
    # "known", or "assumed" when the proof is thin (a statement with one or two balance steps) or the
    # accounts are not certain; `basis_note` says why. `accounts`: the latest proven balance of each
    # account in the radar's currency that the starting cash adds up, each with its own date.
    basis: str = "known"
    basis_note: str | None = None
    accounts: list[dict[str, Any]] = field(default_factory=list)
    # True when statements nothing links or separates were found: only the newest balance is used
    # (`identity_note` says so) and the owner is asked whether they are one account.
    identity_uncertain: bool = False
    identity_note: str | None = None


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
    inflow_basis: BasisSplit
    outflow_basis: BasisSplit


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
    opening_cash: OpeningCash | None = None
    held_documents: HeldDocuments | None = None
    awaiting_decision: Any = None  # AwaitingDecisions: both queues of waiting decisions, one block
    # The currency every figure above is in (`core/currency_totals.effective_base`, the same one the P&L
    # uses), how it was decided, and what was left out: open items in any other currency, listed with their
    # own currency and totals, never converted.
    currency: str = "TRY"
    base_state: str = "confirmed"
    other_currency_totals: list[dict[str, Any]] = field(default_factory=list)
    # Bank balances the starting cash does not hold: other currencies (listed, never converted) and
    # statements whose balance could not be proven (named with the reason).
    other_currency_balances: list[dict[str, Any]] = field(default_factory=list)
    unproven_statements: list[dict[str, Any]] = field(default_factory=list)
    # "Bu ekstreler aynı banka hesabına mı ait?": pairs of proven statements nothing links or separates.
    account_questions: list[dict[str, Any]] = field(default_factory=list)
    # The measured runway (`services.runway`, the forecast's own computation) or why there is none.
    runway: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _opening_cash(balance: dict[str, Any] | None, anchor: date) -> OpeningCash | None:
    if balance is None:
        return None
    as_of = date.fromisoformat(str(balance["date"])[:10])
    limit = get_settings().radar_balance_stale_after_days
    age, stale = balance_age(as_of.isoformat(), anchor, limit)
    basis, aged_note = aged_basis(balance.get("basis"), None, age)
    notes = {a["basis_note"] for a in balance.get("accounts") or [] if a.get("basis_note")} | ({aged_note} if aged_note else set())
    return OpeningCash(
        balance_cents=balance["balance_cents"],
        as_of=as_of.isoformat(),
        age_days=age,
        stale=stale,
        stale_after_days=limit,
        source_job_id=balance.get("job_id"),
        source_filename=balance.get("filename"),
        basis=basis,
        basis_note="; ".join(sorted(notes)) or None,
        accounts=[dict(a) for a in balance.get("accounts") or []],
        identity_uncertain=bool(balance.get("uncertain")),
        identity_note=balance.get("identity_note"),
    )


def _basis_of(
    due: date, receivable: bool, delay: int, rescheduled: bool, expected: date, anchor: date
) -> tuple[str, str, dict[str, Any]]:
    """Why an open item sits where it does: (basis, reason, inputs)."""
    if (not receivable) and expected < anchor:
        # Owed now, but the documents give no day it will really be paid.
        return ASSUMED, "overdue_payable_placed_in_week_1", {"due_date": due.isoformat()}
    if rescheduled:
        return ASSUMED, "payment_plan_change_taken_as_date", {
            "document_due_date": due.isoformat(),
            "planned_date": expected.isoformat(),
        }
    if delay > 0:
        return ESTIMATED, "customer_average_delay", {"average_delay_days": delay}
    return KNOWN, "document_due_date", {}


def _weeks_from(anchor: date) -> list[tuple[date, date]]:
    return [
        (anchor + timedelta(days=7 * i), anchor + timedelta(days=7 * i + 6))
        for i in range(HORIZON_WEEKS)
    ]


def _actions(
    week: int, shortfall: int, collect: list[RadarItem], pay: list[RadarItem], currency: str = DEFAULT_BASE
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
                    f"{_fmt(top.amount_cents, currency)} tutarındaki alacak {top.expected_date} "
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
                    f"{week}. haftadaki {_fmt(top.amount_cents, currency)} ödemesi açığı doğuruyor; "
                    "vade uzatımı için tedarikçiyle görüşülebilir."
                ),
                "amount_cents": top.amount_cents,
            }
        )
    actions.append(
        {
            "type": "financing",
            "title": f"Finansman ihtiyacı: {_fmt(shortfall, currency)}",
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
    from app.services.ledger import effective_base_of

    effective = await effective_base_of(db, org_id)
    cur = effective.run_currency or DEFAULT_BASE
    balances = await proven_balances(db, org_id, cur)
    balance = balances["opening"]
    moved = await effective_dates(db, org_id)
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
    foreign_items: dict[str, dict[str, int]] = {}
    has_cheques = False

    for item in items:
        remaining = item.amount_cents - item.paid_cents
        if remaining <= 0:
            continue
        if normalise(item.currency) != cur:
            other_currency += 1  # counted, never converted at a rate we chose
            slot = foreign_items.setdefault(normalise(item.currency), {"receivable_cents": 0, "payable_cents": 0, "count": 0})
            slot["receivable_cents" if item.direction == RECEIVABLE else "payable_cents"] += remaining
            slot["count"] += 1
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
        rescheduled = (not receivable) and item.id in moved
        if rescheduled:
            expected = moved[item.id]
        basis, basis_reason, basis_inputs = _basis_of(
            item.due_date, receivable, delay, rescheduled, expected, anchor
        )
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
            rescheduled=rescheduled,
            basis=basis,
            basis_reason=basis_reason,
            basis_inputs=basis_inputs,
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
                basis=ESTIMATED,
                basis_reason="recurring_median",
                basis_inputs={
                    "months_observed": r_proj.evidence_count,
                    "median_cents": r_proj.amount_cents,
                    "day_of_month": r_proj.expected_date.day,
                },
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
                basis=ESTIMATED,
                basis_reason="tax_historical_median",
                basis_inputs={
                    "payments_observed": t_proj.observed_payments,
                    "median_cents": t_proj.amount_cents,
                    "tax_type": t_proj.tax_type,
                },
                rules_verified=t_proj.due_rules_verified,
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
    from app.services.awaiting_decisions import block
    from app.services.held_rows import pending_count

    waiting = await pending_count(db, org_id)
    if waiting:
        # Extracted rows a person has not yet accepted: not in any figure here.
        not_included.append(f"{waiting} kayıt incelemenizi bekliyor")
    not_included.extend(currency_notes(effective.state, cur, foreign_items))
    held = await held_documents(db, org_id, anchor, ranges, cur)
    if held is not None:
        not_included.append(_held_line(held, cur))

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
                inflow_basis=_split(receivables[i]),
                outflow_basis=_split(payables[i]),
            )
        )

    shortfall: Shortfall | None = None
    if first_gap is not None and lowest is not None:
        amount = -lowest[0]
        pays = payables[first_gap]
        top = max(pays, key=lambda p: p.amount_cents) if pays else None
        driver = (
            f"{first_gap + 1}. haftada {top.counterparty or 'bir tedarikçiye'} "
            f"{_fmt(top.amount_cents, cur)} ödemesi bakiyeyi eksiye düşürüyor."
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
            actions=_actions(first_gap + 1, amount, collect, pays, cur),
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
        opening_cash=_opening_cash(balance, anchor),
        other_currency_balances=balances["other_currencies"],
        unproven_statements=balances["excluded"],
        account_questions=balances["questions"],
        runway=await company_runway(db, org_id, anchor, balances=balances),
        held_documents=held,
        currency=cur,
        base_state=effective.state,
        other_currency_totals=[{"currency": c, **v} for c, v in sorted(foreign_items.items())],
        awaiting_decision=block(waiting, held, _held_line(held, cur) if held else ""),
    )
