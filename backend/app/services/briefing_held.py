"""What the Monday briefing says about documents waiting for a decision (split from monday_briefing.py)."""
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.currency_totals import fmt_money as _fmt
from app.services.ledger_documents import HOLD_REASONS_TR


def held_caveat(radar: Any, week_outflow_cents: int) -> str:
    """The headline caveat for documents waiting for a decision, "" when they do not matter yet.

    Material (named setting `radar_held_material_ratio`, default 10%): what the held payables would add
    to this week, plus held payables with no date (they could fall in it), is at least that share of
    the week's outflow, or the week has no outflow at all; or a held payable's size is unknown
    (foreign currency, never converted). A caveat is never dropped for an amount that cannot be
    added up: unknown counts as material. Small queues stay in `not_included` only.
    """
    held = radar.held_documents
    if held is None:
        return ""
    ratio = get_settings().radar_held_material_ratio
    at_risk = held.week1_payable_cents + held.undated_payable_cents
    unknown = held.other_currency_payable_count > 0
    material = unknown or (at_risk > 0 and (week_outflow_cents <= 0 or at_risk >= ratio * week_outflow_cents))
    if not material:
        return ""
    size = f" ({_fmt(held.payable_cents, radar.currency)} ödeme)" if held.payable_cents else ""
    foreign = " Tutarı çevrilmemiş döviz belgeleri de var." if unknown else ""
    return (
        f" Karar bekleyen {held.count} belge{size} radara dahil değil; "
        f"bu hafta çıkışlar olduğundan düşük görünebilir.{foreign}"
    )


def held_only_sentence(held: Any, currency: str | None = None) -> str:
    """The headline when the radar is empty only because every document is waiting for a decision."""
    size = f" ({_fmt(held.payable_cents, currency)} ödeme)" if held.payable_cents else ""
    return f"{held.count} belge{size} kararınızı bekliyor; radar bunlar olmadan boş."


def held_line(held: Any, currency: str | None = None) -> str:
    """The `not_included` line: what waits (in the currency given, bare when none), and that a person must answer."""
    parts = []
    if held.payable_cents:
        parts.append(f"{_fmt(held.payable_cents, currency)} ödeme")
    if held.receivable_cents:
        parts.append(f"{_fmt(held.receivable_cents, currency)} tahsilat")
    if held.other_currency_count:
        parts.append(f"{held.other_currency_count} döviz belgesi (tutar çevrilmedi)")
    why = "; ".join(f"{HOLD_REASONS_TR[k]}: {n}" for k, n in sorted(held.by_reason.items()) if n)
    return (
        f"Karar bekleyen {held.count} belge ({', '.join(parts)}): mükerrer olabilir, "
        f"siz karar verene kadar radarda yok" + (f" ({why})" if why else "")
    )
