"""The morning brief's figures: one source, no per-job summation, every number checked.

The figures come from the company ledger (`ledger_summary`, period-aware) and the cash
radar, the same sources as the Monday briefing. They are never summed over the
per-upload reports: two uploads that overlap would be counted twice. A figure that is
not known is left out of the brief, never written as 0. An LLM narrative is shown only
when every number in it is one of these facts (`verify_narrative_numbers`); otherwise
the template, which states only the facts, is the brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cash_radar import _fmt, compute_cash_radar
from app.services.ledger import ledger_summary
from app.services.monday_briefing import _tr_date, verify_narrative_numbers

SOURCE = "ledger+radar"


@dataclass(frozen=True)
class MorningFacts:
    data_date: str
    job_count: int
    critical_count: int
    high_count: int
    revenue_cents: int | None = None
    expense_cents: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    period_months: int | None = None
    opening_cash_cents: int | None = None
    opening_as_of: str | None = None
    week_net_cents: int | None = None
    week_end_balance_cents: int | None = None
    shortfall_cents: int | None = None
    # (currency, revenue, expense) of every other currency in the period: never added to the
    # lira figures, and said so in a line of their own.
    other_currencies: tuple[tuple[str, int, int], ...] = ()

    @property
    def profit_cents(self) -> int | None:
        if self.revenue_cents is None or self.expense_cents is None:
            return None
        return self.revenue_cents - self.expense_cents

    @property
    def has_figures(self) -> bool:
        return any(
            v is not None
            for v in (self.revenue_cents, self.opening_cash_cents, self.week_net_cents)
        )

    def allowed_cents(self) -> set[int]:
        known = (
            self.revenue_cents, self.expense_cents, self.profit_cents, self.opening_cash_cents,
            self.week_net_cents, self.week_end_balance_cents, self.shortfall_cents,
        )
        foreign = {abs(v) for _code, rev, exp in self.other_currencies for v in (rev, exp) if v}
        return {abs(v) for v in known if v is not None} | foreign

    def allowed_plain(self) -> set[int]:
        plain = {self.job_count, self.critical_count, self.high_count}
        if self.period_months is not None:
            plain.add(self.period_months)
        for day in (self.period_start, self.period_end, self.opening_as_of, self.data_date):
            if day:
                plain.update(int(p) for p in re.findall(r"\d+", day))
        return plain


async def build_facts(
    db: AsyncSession, org_id: str, *, job_count: int, critical_count: int, high_count: int,
    today: date,
) -> MorningFacts:
    """Read the figures once, from the ledger and the radar."""
    fields: dict[str, Any] = {}
    summary = await ledger_summary(db, org_id)
    if summary["rows"] > 0:
        period = summary["period"]
        fields.update(
            revenue_cents=int(summary["revenue_cents"]),
            expense_cents=int(summary["expense_cents"]),
            period_start=period["start"], period_end=period["end"], period_months=period["months"],
            other_currencies=tuple(
                (o["currency"], int(o["revenue_cents"]), int(o["expense_cents"]))
                for o in summary["other_currencies"]
            ),
        )
    radar = await compute_cash_radar(db, org_id, anchor_date=today)
    if radar.opening_cash is not None:
        fields.update(
            opening_cash_cents=radar.opening_cash.balance_cents,
            opening_as_of=radar.opening_cash.as_of,
        )
    if radar.weeks:
        week = radar.weeks[0]
        fields["week_net_cents"] = week.net_cents
        if radar.starting_cash_cents is not None:
            fields["week_end_balance_cents"] = week.end_balance_cents
    if radar.shortfall is not None:
        fields["shortfall_cents"] = radar.shortfall.shortfall_cents
    return MorningFacts(
        data_date=today.isoformat(), job_count=job_count,
        critical_count=critical_count, high_count=high_count, **fields,
    )


def _data_date_line(facts: MorningFacts) -> str:
    return f"{_tr_date(facts.data_date)} tarihli verilere göre."


def _plain(cents: int) -> str:
    """An amount as the Turkish text writes it, without a currency sign: 12.400,00."""
    return f"{abs(cents) / 100:,.2f}".translate(str.maketrans(",.", ".,"))


def facts_lines(facts: MorningFacts) -> list[str]:
    """One sentence per known figure. An unknown figure has no sentence."""
    lines: list[str] = []
    if facts.revenue_cents is not None and facts.expense_cents is not None:
        lines.append(
            f"Defterde {facts.period_start} – {facts.period_end} arasında "
            f"{_fmt(facts.revenue_cents)} gelir, {_fmt(facts.expense_cents)} gider görünüyor."
        )
    for code, revenue, expense in facts.other_currencies:
        parts = [f"{_plain(v)} {code} {word}" for v, word in ((revenue, "gelir"), (expense, "gider")) if v]
        if parts:
            lines.append(f"Ayrıca {' ve '.join(parts)} var; TL'ye çevrilmedi, yukarıdaki toplamlara girmedi.")
    if facts.opening_cash_cents is not None and facts.opening_as_of:
        lines.append(
            f"Banka bakiyesi {_fmt(facts.opening_cash_cents)} "
            f"({_tr_date(facts.opening_as_of)} ekstresine göre)."
        )
    if facts.week_net_cents:
        word = "giriş" if facts.week_net_cents > 0 else "çıkış"
        lines.append(f"Bu hafta radarda {_fmt(abs(facts.week_net_cents))} net {word} bekleniyor.")
    if facts.shortfall_cents is not None:
        lines.append(
            f"Radar, bakiyenin en düşük noktada {_fmt(abs(facts.shortfall_cents))} "
            "açığa düşebileceğini gösteriyor."
        )
    return lines


def template_brief(facts: MorningFacts) -> str:
    """The brief with no LLM: the facts, the alert counts and the date of the data."""
    if facts.critical_count:
        headline = f"Dikkat: {facts.critical_count} kritik uyarı var."
    else:
        headline = "Bugün için kritik uyarı yok."
    tail = f"Son 24 saatte {facts.job_count} analiz tamamlandı. {_data_date_line(facts)}"
    return "\n".join([headline, *facts_lines(facts), tail])


def llm_prompt(facts: MorningFacts) -> str:
    lines = facts_lines(facts)
    lines.append(f"Kritik uyarı sayısı: {facts.critical_count}; yüksek: {facts.high_count}.")
    return "Veri (başka sayı kullanma):\n" + "\n".join(lines)


def accept_narrative(narrative: str, facts: MorningFacts) -> str | None:
    """The narrative with the date of the data appended, or None when any number is not a fact."""
    text = (narrative or "").strip()
    if not text:
        return None
    if not verify_narrative_numbers(text, facts.allowed_cents(), allowed_plain=facts.allowed_plain()):
        return None
    return f"{text}\n{_data_date_line(facts)}"
