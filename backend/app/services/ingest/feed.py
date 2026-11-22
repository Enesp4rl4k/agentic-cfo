"""The counting layer for money rows that do not come from an uploaded file.

An upload is counted by `okuma.ReadLedger` and held by `hold.split_uncertain`. A pull from a bank, an ERP, an
e-commerce channel or a scheduled sync is the same problem with a different front door, and it had no layer
at all: a missing type code became an expense, a missing amount became 0, "1.500" became 1,50, an outage
became "no transactions". Every source that fetches money rows now goes through `Feed`:

  - every fetched item is COUNTED when it is looked at (`Feed.each`), so the count does not depend on the code
    that builds the row; the row is then BUILT (`Feed.add`): booked, or flagged and held by the ingest
    pipeline; or it is skipped under one of two named rules: `blank` (the item has no content at all) or
    `out_of_scope` (a READABLE date outside the window asked for). There is no other exit, and `okuma.reconcile` checks it (`read == emitted + blank + out_of_scope`);
  - a value the source did not state is None, never a default: amount (parsed by `parsers.direction.parse_money`,
    the ONE amount parser; a text amount that reads two ways is held), direction, date, currency;
  - a row with any unknown value reaches /bekleyen-kayitlar with the raw values that were fetched (`evidence`,
    fields the source chose: never a token or a secret);
  - a fetch that failed or stopped short is a FAILED or PARTIAL result with the reason, never an empty success,
    and a result that is not complete does not cover its period (`FeedResult.complete`).

`tests/test_non_upload_sources.py` fails when a module that fetches money rows does not go through this layer.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.core.dates import parse_transaction_date
from app.parsers.direction import parse_money
from app.parsers.money_text import money_is_ambiguous, money_is_wellformed
from app.services.ingest.currencies import is_currency_code
from app.services.ingest.okuma import ReadLedger, reconcile

SUCCESS = "success"
AWAITING_REVIEW = "awaiting_review"
PARTIAL = "partial"
FAILED = "failed"

INCOME = "income"
EXPENSE = "expense"

# Flags a row carries when the source did not state (or stated unreadably) something the books need.
AMOUNT_MISSING = "amount_missing"
AMOUNT_UNREADABLE = "amount_unreadable"
AMOUNT_AMBIGUOUS = "amount_ambiguous"
AMOUNT_ZERO = "amount_zero"
DIRECTION_MISSING = "direction_missing"
DATE_UNREADABLE = "date_unreadable"
CURRENCY_UNREADABLE = "currency_unreadable"

_SECRET_WORDS = re.compile(r"token|secret|password|authorization|bearer|api[_-]?key", re.IGNORECASE)
_SUMMARY_VALUE = 60
_ALIASES = {"TL": "TRY", "TRL": "TRY", "₺": "TRY", "$": "USD", "€": "EUR", "£": "GBP"}


class FeedFailed(Exception):
    """The fetch gave nothing usable (outage, refused, malformed response). The message is the reason."""


@dataclass(frozen=True)
class MoneyRead:
    cents: int | None          # magnitude in kuruş; None when no amount can be stood behind
    negative: bool
    flag: str | None           # why `cents` is None (AMOUNT_*)


def read_money(raw: Any) -> MoneyRead:
    """An amount as a source stated it: through `parse_money`; missing, unreadable and ambiguous are NOT zero."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return MoneyRead(None, False, AMOUNT_MISSING)
    if isinstance(raw, (bool, list, dict)):
        return MoneyRead(None, False, AMOUNT_UNREADABLE)
    if not money_is_wellformed(raw):
        return MoneyRead(None, False, AMOUNT_UNREADABLE)
    if money_is_ambiguous(raw):
        return MoneyRead(None, False, AMOUNT_AMBIGUOUS)
    try:
        parsed = parse_money(raw)
    except (ValueError, OverflowError, ArithmeticError):     # nan, inf
        parsed = None
    if parsed is None:
        return MoneyRead(None, False, AMOUNT_UNREADABLE)
    return MoneyRead(parsed[0], parsed[1], None)


def signed_amount(raw: Any) -> float | None:
    """A balance as a signed number in currency units (an overdraft is negative); None when it cannot be read."""
    money = read_money(raw)
    return None if money.cents is None else (-money.cents if money.negative else money.cents) / 100


def first(item: Any, *keys: str) -> Any:
    """The first of `keys` the item states (not missing, not empty); None when none is. Never a default."""
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


ONE_WAY = "one_way"      # the source's contract: every row moves money one way; a sign that says otherwise is held
SIGNED = "signed"        # the source's contract: amounts are signed (negative = out); only a declared source may use it

# THE one place a direction is declared by a source's contract, never inferred from the data. A row's own explicit
# direction/type field always comes first; with neither a field nor an entry here the row is HELD. There is no
# file-level rule ("the file has a negative, so it is signed"): one refund row in a payroll or Stripe file must not
# turn every other row into income.
SOURCE_DIRECTION: dict[str, tuple[str, str | None]] = {
    # A payroll export lists what the company pays its staff: outflows. A negative line (an advance returned) says
    # nothing the contract allows, so it is held, not booked as income and not as more payroll.
    "hr_export": (ONE_WAY, EXPENSE),
    # A CRM deal export is filtered to closed-won deals: sales, inflows.
    "crm_export": (ONE_WAY, INCOME),
    # The Stripe pull is `status=paid` invoices: charges, inflows. A refund or credit note is not in this pull;
    # one that appears (a negative amount) is held.
    "billing_stripe": (ONE_WAY, INCOME),
}


def direction_by_contract(contract: tuple[str, str | None] | None, money: MoneyRead) -> str | None:
    """The direction a source's declared contract gives this amount; None (held) when it gives none."""
    if contract is None or money.cents is None:
        return None
    kind, fixed = contract
    if kind == ONE_WAY:
        return None if money.negative else fixed
    if kind == SIGNED:
        return direction_from_sign(money)
    return None


def direction_from_code(code: Any, credit: Iterable[str], debit: Iterable[str]) -> str | None:
    """income / expense from a type code the source documents; anything else, or nothing, is None (held)."""
    text = str(code).strip().upper() if code is not None else ""
    if text in {c.upper() for c in credit}:
        return INCOME
    if text in {d.upper() for d in debit}:
        return EXPENSE
    return None


def direction_from_sign(money: MoneyRead) -> str | None:
    """A signed amount's direction. An unreadable amount, and a zero one, say nothing."""
    if not money.cents:
        return None
    return EXPENSE if money.negative else INCOME


def iso_date(raw: Any) -> str | None:
    """A date as ISO text, or None when the source stated none that can be read (never today's date)."""
    if raw is None or raw == "":
        return None
    when, estimated = parse_transaction_date(raw)
    return None if estimated else when.date().isoformat()


def iso_currency(raw: Any) -> tuple[str | None, bool]:
    """(code, readable): a stated ISO-4217 code, or (None, True) when none was stated, or (None, False) when unreadable."""
    text = str(raw).strip().upper() if raw is not None else ""
    if not text:
        return None, True
    text = _ALIASES.get(text, text)
    return (text, True) if is_currency_code(text) else (None, False)


_CARD_RUN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_BEARER = re.compile(r"(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)


def mask_secrets(text: str) -> str:
    """A held row is shown to people: a token, an authorization header or a full card number never is.

    A run of 13-19 digits (a card number, with or without spaces/dashes) keeps its last four; "Bearer xxxx" is cut."""
    text = _BEARER.sub("[gizli]", text)
    return _CARD_RUN.sub(lambda m: "**** " + re.sub(r"\D", "", m.group(0))[-4:], text)


def evidence_text(evidence: dict[str, Any]) -> str:
    """The raw values a held row shows its reviewer. Fields the SOURCE module chose; a secret-looking key is dropped."""
    parts = []
    for key, value in evidence.items():
        if _SECRET_WORDS.search(str(key)):
            continue
        text = repr(value) if not isinstance(value, str) else repr(value[:_SUMMARY_VALUE])
        parts.append(f"{key}={text[:_SUMMARY_VALUE]}")
    return mask_secrets("; ".join(parts))


def _tr_date(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


_COVERAGE_MARK = re.compile(r"çekim\s+(?:tamamlandı|yarıda\s+kaldı)", re.IGNORECASE)


def has_coverage_header(text: str) -> bool:
    """Whether a file's title rows carry a sync's own statement of what it received (`coverage_header`)."""
    return bool(_COVERAGE_MARK.search(text or ""))


def coverage_header(window: tuple[str, str] | None, row_dates: list[str | None], partial: str | None) -> str | None:
    """The one title line a pulled file carries so coverage reads it like a statement's stated period.

    A COMPLETED pull states the window it asked for and fully received ("Dönem: 01.03.2026 - 31.03.2026 Çekim
    tamamlandı"): that is proof of the period, not a guess from the first and last row. A PARTIAL pull states only what
    it received, from its first to its last row ("... Çekim yarıda kaldı: en son tam alınan gün 27.03.2026"); both
    edges of that span are strict and the five-day edge tolerance never applies to them. No window and no rows:
    nothing is stated.
    """
    days = sorted(str(d)[:10] for d in row_dates if d)
    if partial:
        if not days:
            return None
        return (f"Dönem: {_tr_date(days[0])} - {_tr_date(days[-1])} "
                f"Çekim yarıda kaldı: en son tam alınan gün {_tr_date(days[-1])}")
    if window:
        return f"Dönem: {_tr_date(window[0])} - {_tr_date(window[1])} Çekim tamamlandı"
    return None


@dataclass
class FeedResult:
    rows: list[dict[str, Any]]
    ledger: ReadLedger
    source: str
    failed: str | None = None          # nothing usable was fetched; the reason
    partial: str | None = None         # some of it was fetched; what is missing
    ignored: dict[str, int] = field(default_factory=dict)    # items the source marks as not (yet) money, by named rule
    window: tuple[str, str] | None = None                    # the days the pull asked for (ISO), when it asked for a range

    def coverage_header(self) -> str | None:
        """The title line for the file this pull becomes (see `coverage_header`)."""
        if self.failed:
            return None
        return coverage_header(self.window, [r.get("date") for r in self.rows], self.partial)

    @property
    def held_candidates(self) -> int:
        """Rows that will wait for a person: some value the source did not state."""
        return sum(1 for r in self.rows if r.get("feed_flags"))

    @property
    def complete(self) -> bool:
        """The whole requested window was fetched: only then may a sync say it covers its period."""
        return self.failed is None and self.partial is None

    def outcome(self) -> dict[str, Any]:
        """What a sync reports: counts, whether it may say "success", and why not."""
        counts, lost = reconcile(self.ledger.as_dict(), len(self.rows), 0)
        flagged = self.held_candidates
        if self.failed:
            status = FAILED
        elif self.partial:
            status = PARTIAL
        elif lost or flagged:
            status = AWAITING_REVIEW
        else:
            status = SUCCESS
        return {
            "ok": self.failed is None and lost == 0, "status": status, "complete": self.complete,
            "reason": self.failed or self.partial, "unaccounted": lost, "held_candidates": flagged,
            "counts": counts, "skipped": self.ledger.blank + self.ledger.out_of_scope, "ignored": dict(self.ignored), "source": self.source,
        }


class Feed:
    """Collects the rows of one pull. `each` counts what is fetched; `add` / `blank` say where each item went."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.ledger = ReadLedger()
        self.rows: list[dict[str, Any]] = []
        self.failed: str | None = None
        self.partial: str | None = None
        self.ignored: dict[str, int] = {}
        self.window: tuple[str, str] | None = None

    def each(self, items: Iterable[Any]) -> Iterator[Any]:
        """Iterate the fetched items, counting every one (`read`) before the caller looks at it."""
        for item in items:
            self.ledger.read += 1
            yield item

    def skip_outside_window(self) -> None:
        """The source returned an item older/newer than the window asked for (no server-side date filter): counted."""
        self.ledger.out_of_scope += 1

    def blank(self) -> None:
        """The one skip rule: the item carries nothing at all (no key has a value), so there is no money in it."""
        self.ledger.blank += 1

    def ignore(self, rule: str) -> None:
        """An item the source itself labels as not booked money (a pending entry): counted by rule, not in `read`."""
        self.ignored[rule] = self.ignored.get(rule, 0) + 1

    def add(
        self, *, amount: Any, direction: str | None, date: Any, currency: Any, description: str,
        reference: str | None = None, evidence: dict[str, Any] | None = None, **extra: Any,
    ) -> dict[str, Any]:
        """One fetched item as a row of the shape `ekle.islemleri_ekle` takes. Unknown values stay None and flag the row."""
        money = read_money(amount)
        flags: list[str] = [money.flag] if money.flag else ([AMOUNT_ZERO] if money.cents == 0 else [])
        if direction not in (INCOME, EXPENSE):
            direction = None
            flags.append(DIRECTION_MISSING)
        when = iso_date(date)
        if when is None:
            flags.append(DATE_UNREADABLE)
        code, readable = iso_currency(currency)
        if not readable:
            flags.append(CURRENCY_UNREADABLE)
            extra["currency_raw"] = str(currency).strip()[:20]     # what the source STATED: it travels to the review queue
        text = mask_secrets(description or "")
        if flags and evidence:
            text = f"{text} [ham: {evidence_text(evidence)}]"
        row: dict[str, Any] = {
            "date": when, "amount_cents": money.cents, "type": direction, "currency": code,
            "description": text[:500], "reference": reference or "", "source": self.source,
            "feed_flags": flags, **extra,
        }
        self.rows.append(row)
        self.ledger.emitted += 1
        return row

    def fail(self, reason: str) -> FeedResult:
        self.failed = reason
        return self.result()

    def result(self) -> FeedResult:
        return FeedResult(self.rows, self.ledger, self.source, self.failed, self.partial, self.ignored, self.window)


def item_is_blank(item: Any) -> bool:
    """Nothing in it at all: None, an empty object, or a dict whose every value is empty."""
    if item is None:
        return True
    if isinstance(item, dict):
        return not any(v not in (None, "", [], {}) for v in item.values())
    return isinstance(item, (str, list)) and not item


SAFETY_KEYS = ("feed_flags", "currency_raw")


def rows_for_pipeline(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows as `islemler_csv` reads them. A projection never drops a safety key (`SAFETY_KEYS`): it was the
    dropped `feed_flags` that let a stated-but-unreadable currency be replaced by the base currency."""
    return [dict(r) for r in rows]
