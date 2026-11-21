"""Every physical line of a text statement is accounted for, whatever the row pattern thinks of it.

The row regexes of the bank layouts (and the column finders of the accounting exports) decide what a
transaction looks like. A line they reject used to vanish: never read, never counted, never reported, a
5.000,00 payment with it. This module is the INDEPENDENT source of "what was read": the non-empty physical lines
of the text, taken before any row pattern is asked. Each one ends in exactly one bucket:

  row            a transaction the parser built from it (booked or held downstream)
  unread         it looks like money (a date-like or an amount-like token) and the parser did not take it:
                 HELD as a transaction ("satır okunamadı") with its raw text, never dropped
  summary        the whole line is a summary phrase ("Devreden Bakiye 10.000,00", "Toplam"): counted and listed
  continuation   a wrapped description: attached to the row above it, counted
  non_row        a page header, footer, address, rule: counted

The candidate test is deliberately loose: when in doubt a line is a candidate and a person sees it.
`read_lines` is a different function from every parser and does not call any row pattern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.turkish import fold
from app.parsers.base import BankParser, ParsedTransaction
from app.parsers.direction import is_summary_phrase, norm_header, parse_money

DATE_LIKE = re.compile(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})(?!\d)|(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
AMOUNT_LIKE = re.compile(
    r"(?<![\d.,])[+\-−(]?\d{1,3}(?:[. ]\d{3})+(?:[.,]\d{1,2})?\)?(?!\d|[.,]\d)"
    r"|(?<![\d.,])[+\-−(]?\d+[.,]\d{1,2}\)?(?!\d|[.,]\d)"
)
_FOOTER = re.compile(
    r"^(sayfa|page)\b|hesap\s*(no|numaras|ozeti|ekstresi)|ekstre|musteri|sube\b|iban|www\.|http|\btel\b|adres|"
    r"^[-_=*.\s]{3,}$|bu belge|gizli|kvkk",
)
_HEADER_WORDS = ("tarih", "aciklama", "borc", "alacak", "bakiye", "tutar", "islem", "valor", "date", "description", "balance")
MAX_LISTED = 25


def _is_header(line: str) -> bool:
    """A column header row, repeated at a page break."""
    folded = fold(line)
    return sum(w in folded for w in _HEADER_WORDS) >= 2 and not is_candidate(line)


def read_lines(text: str) -> list[str]:
    """The units: every non-empty physical line, stripped. Computed from the text alone."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def is_candidate(line: str) -> bool:
    """Loose on purpose: a date-like token or an amount-like token."""
    return bool(DATE_LIKE.search(line) or AMOUNT_LIKE.search(line))


def _squash(s: str) -> str:
    return re.sub(r"[\s\"';,]+", "", s)


def _words(line: str) -> str:
    """The line without its dates, amounts and punctuation: what it SAYS."""
    return norm_header(AMOUNT_LIKE.sub(" ", DATE_LIKE.sub(" ", line)))


@dataclass
class LineAccount:
    transactions: list[ParsedTransaction]
    read: int = 0
    unread: int = 0
    continuation: int = 0
    non_row: int = 0
    summary: list[str] = field(default_factory=list)

    @property
    def emitted(self) -> int:
        return len(self.transactions)


def _unread_row(line: str) -> ParsedTransaction:
    date_token = DATE_LIKE.search(line)
    when = BankParser.parse_turkish_date(date_token.group(0)) if date_token else None
    amount = AMOUNT_LIKE.search(line)
    parsed = parse_money(amount.group(0)) if amount else None
    return ParsedTransaction(
        date=when or datetime.now(UTC),
        description=line[:200],
        amount_cents=parsed[0] if parsed else 0,
        tx_type="",
        raw_row=line,
        date_estimated=when is None,
        unread=True,
        confidence_note="satır okunamadı: satır biçimi tanınmadı",
    )


def account_for_lines(text: str, transactions: list[ParsedTransaction]) -> LineAccount:
    """Match what the parser built to the lines of the text, then give every other line a bucket.

    The result lists the transactions in text order, with an unread line standing where it was. A
    transaction the matching cannot place is kept (at the end): nothing the parser built is lost either.
    """
    lines = read_lines(text)
    squashed = [_squash(line) for line in lines]
    pending = list(transactions)
    placed: dict[int, ParsedTransaction] = {}
    cursor = 0
    for i, sq in enumerate(squashed):
        # The parser's rows come in text order: compare with the next few it has not placed.
        for j in range(cursor, min(cursor + 6, len(pending))):
            raw = _squash(pending[j].raw_row)
            if raw and raw in sq:
                placed[i] = pending[j]
                pending.pop(j)
                cursor = j
                break
    first = min(placed, default=-1)
    out: list[ParsedTransaction] = []
    acct = LineAccount(out, read=len(lines))
    previous_is_row = False
    last_tx: ParsedTransaction | None = None
    for i, line in enumerate(lines):
        if i in placed:
            last_tx = placed[i]
            out.append(last_tx)
            previous_is_row = True
            continue
        words = _words(line)
        candidate = is_candidate(line)
        if is_summary_phrase(words):
            acct.summary.append(line[:120])
            previous_is_row = False
            continue
        if candidate and not _FOOTER.search(fold(line)):
            # Before the first row, a line with no amount is a title ("Dönem: 01.01.2024 - 31.01.2024"); with an
            # amount it is money and is held. Inside and after the body, and in a text nothing parsed, every
            # candidate is held.
            if first < 0 or i > first or AMOUNT_LIKE.search(line):
                last_tx = _unread_row(line)
                out.append(last_tx)
                acct.unread += 1
                previous_is_row = True
                continue
        if _is_header(line):
            acct.non_row += 1
            previous_is_row = False
            continue
        if previous_is_row and last_tx is not None and not candidate and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", line) \
                and not _FOOTER.search(fold(line)) and len(line) <= 80:
            last_tx.description = f"{last_tx.description} {line}".strip()[:300]
            acct.continuation += 1
            continue
        acct.non_row += 1
        previous_is_row = False
    out.extend(pending)         # kept, never lost: rows the matching could not place
    return acct
