"""Money in different currencies is never added together.

An amount in USD and an amount in TRY are not the same unit, and no exchange rate is
kept here: the repository has no dated, sourced rate (TCMB/EVDS is a macro snapshot, not
a conversion table), and a rate we chose would turn a guess into a figure that reads as a
fact. So every total over money is **per currency**:

- the organisation's base currency gets the headline figure;
- every other currency is reported as its own sub-total ("ayrıca 12.400 USD gider,
  TL'ye çevrilmedi") and is never folded into the base number;
- ratios and month-over-month changes are computed on base-currency amounts only;
- rankings and anomaly detection never compare raw amounts across currencies.

This module is the one place that says which rows belong to which currency. Every
aggregation over ledger or pipeline rows goes through `split_by_currency` (or
`totals_by_currency`), and `tests/test_currency_aggregation_guard.py` fails when a new
money aggregation appears without it.

A row is a mapping (pipeline rows: `currency`, `type`) or an object (ledger rows:
`currency`, `direction`). A row that names no currency is counted as the base currency
only when it is a pipeline mapping, because every producer of those rows writes one
(parsers default to TRY): the ledger column is not nullable.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.core.tdhp import BILANCO_KATEGORILERI

DEFAULT_BASE = "TRY"
# What a figure says when its currency is unknown. The wire code for that case is "?" (see foreign_summaries).
CURRENCY_UNKNOWN_TR = "para birimi bilinmiyor"

R = TypeVar("R")


def normalise(code: str | None) -> str:
    """ISO 4217 code in capitals; "" when the row names none."""
    return (code or "").strip().upper()


def _get(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def same_currency(a: str | None, b: str | None) -> bool:
    """Could two rows be in the same currency? Equal codes are: it does not matter whether a code was
    stated by the document or assumed from the confirmed base (`currency_assumed`). A side with no code at
    all is unknown, and unknown is not "different": the comparison falls back to the one made before
    currencies existed (the pair is held if it is ambiguous), instead of splitting one invoice in two."""
    x, y = normalise(a), normalise(b)
    return not x or not y or x == y


def code_of(row: Any, base: str) -> str:
    """The currency a row is in. A mapping with none counts as `base` (see module docstring)."""
    code = normalise(_get(row, "currency"))
    if code:
        return code
    return normalise(base) if isinstance(row, dict) else ""


def direction_of(row: Any) -> str:
    return str(_get(row, "type") or _get(row, "direction") or "")


def amount_of(row: Any) -> int:
    value = _get(row, "amount_cents")
    return int(value or 0)


def split_by_currency(rows: Iterable[R], base: str) -> tuple[list[R], dict[str, list[R]]]:
    """(rows in the base currency, the rest grouped by their own currency)."""
    base = normalise(base) or DEFAULT_BASE
    mine: list[R] = []
    other: dict[str, list[R]] = {}
    for row in rows:
        code = code_of(row, base)
        if code == base:
            mine.append(row)
        else:
            other.setdefault(code, []).append(row)
    return mine, other


def totals_by_currency(rows: Iterable[R], value: Callable[[R], int], base: str = DEFAULT_BASE) -> dict[str, int]:
    """Sum `value(row)` once per currency."""
    totals: dict[str, int] = {}
    for row in rows:
        code = code_of(row, base)
        totals[code] = totals.get(code, 0) + value(row)
    return totals


def _is_income(row: Any) -> bool:
    return direction_of(row) == "income"


def _group(rows: Iterable[Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for row in rows:
        out.setdefault(code_of(row, ""), []).append(row)
    return out


def foreign_summaries(
    profit: Iterable[Any], cash: Iterable[Any], base: str
) -> list[dict[str, Any]]:
    """Sub-totals of every non-base currency, for display beside the base figure.

    `profit` rows give revenue and expense (balance-sheet movements are cash, not profit);
    `cash` rows give money in and out. Each currency is summed on its own. Sorted by
    currency code so the output is stable.
    """
    # base None: there is no headline currency, so every currency is reported on its own.
    profit_other = split_by_currency(profit, base)[1] if base else _group(profit)
    cash_other = split_by_currency(cash, base)[1] if base else _group(cash)
    out: list[dict[str, Any]] = []
    for code in sorted(set(profit_other) | set(cash_other)):
        earned = [r for r in profit_other.get(code, []) if _get(r, "category") not in BILANCO_KATEGORILERI]
        moved = cash_other.get(code, [])
        seen = {id(r): r for r in [*profit_other.get(code, []), *moved]}
        out.append({
            "currency": code or "?",
            "revenue_cents": sum(amount_of(r) for r in earned if _is_income(r)),
            "expense_cents": sum(amount_of(r) for r in earned if not _is_income(r)),
            "cash_in_cents": sum(amount_of(r) for r in moved if _is_income(r)),
            "cash_out_cents": sum(amount_of(r) for r in moved if not _is_income(r)),
            "rows": len(seen),
            "assumed_rows": sum(1 for r in seen.values() if _get(r, "currency_assumed")),
        })
    return out


def currency_note(
    base: str, foreign: list[dict[str, Any]] | None, kind: str = "profit", state: str | None = None
) -> str | None:
    """One sentence saying what was left out of the figures and how the currency was chosen, or None.

    `kind` is "profit" (revenue and expense) or "cash" (money in and out); `state` is the
    `EffectiveBase.state` the figures were computed under.
    """
    base = normalise(base) or DEFAULT_BASE
    lead = ""
    if state == SINGLE_UNCONFIRMED:
        lead = f"Şirket para birimi henüz onaylanmadı; veride yalnızca {base} var. "
    elif state == AMBIGUOUS:
        lead = (f"Şirket para birimi seçilmediği için hesap, en çok satırı olan {base} ile yapıldı. "
                "Şirket para biriminizi seçin. ")
    if not foreign:
        return lead.strip() or None
    keys = (("cash_in_cents", "giriş"), ("cash_out_cents", "çıkış")) if kind == "cash" else (
        ("revenue_cents", "gelir"), ("expense_cents", "gider"))
    parts = []
    for f in foreign:
        bits = [f"{f[k] / 100:,.2f} {f['currency']} {word}" for k, word in keys if f.get(k)]
        parts.append(" ve ".join(bits) if bits else f"{f['currency']} hareketi")
    return (
        lead + f"Toplamlar ve oranlar yalnızca {base} tutarlarıyla hesaplandı; ayrıca "
        + ", ".join(parts) + f" var, {base}'ye çevrilmedi."
    )


# ── the effective base: which currency is the headline, and how sure we are ────────────────────
#
# `Organization.base_currency` is NOT NULL with a column default of "USD", so a stored value is not a
# choice. Only a currency an owner or admin confirmed (`base_currency_confirmed_at`) is one. Every
# surface (ledger summary, company view, the pipeline's split, the cash radar, the briefings, the
# transactions list) decides its headline with this one function, so they cannot disagree.

CONFIRMED = "confirmed"
SINGLE_UNCONFIRMED = "single_unconfirmed"
AMBIGUOUS = "ambiguous"
NO_DATA = "no_data"
CONFIRM_PATH = "/bekleyen-kayitlar"  # the screen where an owner or admin confirms the company currency


@dataclass(frozen=True)
class EffectiveBase:
    """The headline currency and why.

    - `confirmed`: `currency` is the confirmed one; every other currency is "ayrıca … çevrilmedi".
    - `single_unconfirmed`: the data holds exactly one currency: it is the headline, marked as not yet
      confirmed, and nothing is dropped.
    - `ambiguous`: unconfirmed and several currencies: there is no single headline (`currency` is None);
      totals are shown per currency and a person is asked to choose. `dominant` (most rows) is only the
      currency a computation may run on, and then its outputs must be labelled.
    - `no_data`: nothing to total.
    """

    state: str
    currency: str | None
    present: dict[str, int] = field(default_factory=dict)
    dominant: str | None = None
    confirm_path: str = CONFIRM_PATH

    @property
    def confirmed(self) -> bool:
        return self.state == CONFIRMED

    @property
    def run_currency(self) -> str | None:
        """The currency a computation runs on: the headline, else (ambiguous) the dominant one, else None."""
        return self.currency or self.dominant

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state, "currency": self.currency, "confirmed": self.confirmed,
            "dominant": self.dominant, "present": dict(sorted(self.present.items())),
            "confirm_path": self.confirm_path,
        }


def effective_base(confirmed: str | None, counts: Mapping[str, int]) -> EffectiveBase:
    """The one rule. `confirmed` is the organisation's confirmed base currency or None; `counts` is
    rows per currency present in the data (zero counts are ignored)."""
    present = {normalise(c): n for c, n in counts.items() if n and normalise(c)}
    code = normalise(confirmed)
    if code:
        return EffectiveBase(CONFIRMED, code, present)
    if not present:
        return EffectiveBase(NO_DATA, None, present)
    if len(present) == 1:
        (only,) = present
        return EffectiveBase(SINGLE_UNCONFIRMED, only, present)
    top = max(present.values())
    leaders = sorted(c for c, n in present.items() if n == top)
    return EffectiveBase(AMBIGUOUS, None, present, dominant=leaders[0])


def count_currencies(rows: Iterable[Any]) -> dict[str, int]:
    """Rows per currency (a pipeline row naming none is not counted: it has no currency to vote for)."""
    out: dict[str, int] = {}
    for row in rows:
        code = normalise(_get(row, "currency"))
        if code:
            out[code] = out.get(code, 0) + 1
    return out


def fmt_money(cents: int, currency: str | None = None) -> str:
    """An amount as the Turkish text writes it: ₺1.234,56 for lira, 1.234,56 USD for the rest.

    No currency given means the currency is unknown, not lira: the plain number and the words say so."""
    sign = "-" if cents < 0 else ""
    swapped = f"{abs(cents) / 100:,.2f}".translate(str.maketrans(",.", ".,"))
    code = normalise(currency)
    if not code:
        return f"{sign}{swapped} ({CURRENCY_UNKNOWN_TR})"
    return f"{sign}₺{swapped}" if code == "TRY" else f"{sign}{swapped} {code}"


def currency_notes(state: str, currency: str, foreign_items: Mapping[str, Mapping[str, int]]) -> list[str]:
    """The radar's `not_included` lines about currency: an unconfirmed company currency, and each other
    currency's open items with their own totals (never converted)."""
    lines: list[str] = []
    if state == SINGLE_UNCONFIRMED:
        lines.append(f"Şirket para birimi henüz onaylanmadı: radar yalnızca {currency} kalemlerini içeriyor")
    elif state == AMBIGUOUS:
        lines.append(f"Şirket para biriminizi seçin: radar, en çok kalemi olan {currency} ile hesaplandı")
    for code, v in sorted(foreign_items.items()):
        sums = ", ".join(
            f"{fmt_money(v[k], code)} {word}"
            for k, word in (
                ("payable_cents", "ödeme"), ("receivable_cents", "tahsilat"),
                ("recurring_payable_cents", "düzenli ödeme tahmini"), ("tax_payable_cents", "vergi/SGK tahmini"),
            ) if v.get(k)
        )
        lines.append(f"{code} kalemleri ({v['count']}; {sums or 'tutarsız'}): {currency}'ye çevrilmedi, radarda yok")
    return lines
