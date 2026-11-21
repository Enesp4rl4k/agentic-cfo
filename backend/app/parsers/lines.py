"""Every physical line of a text statement is accounted for, whatever the row pattern thinks of it.

The row regexes of the bank layouts (and the column finders of the accounting exports) decide what a
transaction looks like. A line they reject used to vanish: never read, never counted, never reported, a
5.000,00 payment with it. This module is the INDEPENDENT source of "what was read": the non-empty physical lines
of the text, taken before any row pattern is asked. Each one ends in exactly one bucket:

  row            a transaction the parser built from it (booked, or held when its amount is uncertain)
  unread         it may carry money and the parser did not take it: HELD with its raw text, never dropped
  summary        the whole line is a summary phrase ("Devreden Bakiye 10.000,00", "Toplam"): counted and listed
  continuation   a wrapped description: attached to the row above it, counted
  non_row        a page header, footer, address, rule: counted

RULE A, "no digit left behind". A line may be absorbed as a continuation, counted as a non-row or booked ONLY
if every number in it is accounted for:
  (i)   a line with any digit run that could be money (an integer of 2+ digits, a number with separators, a
        currency sign or suffix, a Turkish number word such as bin/milyon/lira/TL) that no matched row consumed is
        HELD, never absorbed and never classed non-row; only tokens an explicit pattern identifies as something
        else (IBAN, account/card/reference numbers, a phone number, "Sayfa 2/5", the dates of a header phrase)
        are exempt. Extra held noise is acceptable; loss is not.
  (ii)  after a row pattern matched, a money-like token of the line that is neither the row's amount nor its
        balance nor its date (`₺5.000` left over in `B ₺5.000 -9.200`) means the match is unreliable: the row is
        HELD with its raw text ("tutar belirsiz"), not booked. Generic: no bank-specific code.
  (iii) a booked amount is never a token of the balance position when another money token is on the line: that
        is case (ii).
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
_CURRENCY_MARKED = re.compile(
    r"[₺$€£]\s?\d[\d.,]*|\d[\d.,]*\s?(?:₺|TL\b|TRY\b|USD\b|EUR\b|GBP\b)", re.IGNORECASE,
)
_MONEY_WORDS = re.compile(r"\b(?:bin|milyon|milyar|lira|kuruş|kurus|tl|try|usd|eur|dolar|euro|avro|sterlin)\b", re.IGNORECASE)
_BIG_INTEGER = re.compile(r"(?<![\d.,])\d{2,}(?!\d)(?![.,]\d)")

# Numbers positively identified as something else, each by an explicit pattern (tested in test_text_lines_invariant).
_NOT_MONEY = [
    re.compile(r"\bTR\d{2}(?:[ ]?\d{4}){5}[ ]?\d{2}\b", re.IGNORECASE),                                  # IBAN
    re.compile(                                                                                         # account / card / reference ids
        r"\b(?:hesap|müşteri|musteri|kart|referans|ref|dekont|şube|sube|vkn|tckn|sicil|mersis|evrak|fiş|fis|belge)"
        r"[ ]*(?:no|numarası|numarasi|kodu)?[ ]*[.:]?[ ]*\d[\d\- /]{2,}", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\+?90[ -]?)?\(?0?\d{3}\)?[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}(?!\d)"),               # phone
    re.compile(r"\b(?:sayfa|page)[ ]*\d+(?:[ ]*(?:/|of)[ ]*\d+)?", re.IGNORECASE),                       # page 2/5
    re.compile(                                                                                         # dates of a header phrase
        r"\b(?:dönem|donem|tarih aralığı|tarih araligi|rapor tarihi|ekstre tarihi|düzenleme tarihi|hesap özeti|"
        r"hesap ozeti|başlangıç|baslangic|bitiş|bitis)\b[^\n\d]{0,20}[\d./ \-–:]{6,30}", re.IGNORECASE),
    re.compile(r"(?:©|\bcopyright\b|\ball rights\b|\btüm hakları\b)[^\n]*?\d{4}", re.IGNORECASE),        # a year in a footer
]
_HEADER_WORDS = ("tarih", "aciklama", "borc", "alacak", "bakiye", "tutar", "islem", "valor", "date", "description", "balance")
MAX_LISTED = 25


def read_lines(text: str) -> list[str]:
    """The units: every non-empty physical line, stripped. Computed from the text alone."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def strip_explained(line: str) -> str:
    """The line with the numbers an explicit pattern identifies as not money blanked out."""
    for pattern in _NOT_MONEY:
        line = pattern.sub(" ", line)
    return line


def money_tokens(line: str) -> list[str]:
    """Tokens of a line that could be money, after the explained ones are removed (dates excluded)."""
    text = DATE_LIKE.sub(" ", strip_explained(line))
    found = [m.group(0) for m in AMOUNT_LIKE.finditer(text)]
    found += [m.group(0) for m in _CURRENCY_MARKED.finditer(text)]
    found += [m.group(0) for m in _BIG_INTEGER.finditer(text)]
    found += [m.group(0) for m in _MONEY_WORDS.finditer(text)]
    return found


def is_candidate(line: str) -> bool:
    """Loose on purpose: a date, or anything that could be money that no explicit pattern explains."""
    cleaned = strip_explained(line)
    return bool(DATE_LIKE.search(cleaned) or money_tokens(line))


def _is_header(line: str) -> bool:
    """A column header row, repeated at a page break."""
    return sum(w in fold(line) for w in _HEADER_WORDS) >= 2 and not is_candidate(line)


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


def _first_amount(line: str) -> int:
    """The first token of the line that reads as an amount, in kuruş (0 when none does).

    A bare integer is whole lira: "5000" is 5.000,00."""
    cleaned = DATE_LIKE.sub(" ", strip_explained(line))
    found = sorted(
        (m.start(), m.group(0)) for pattern in (_CURRENCY_MARKED, AMOUNT_LIKE, _BIG_INTEGER) for m in pattern.finditer(cleaned)
    )
    for _, token in found:                  # the earliest token in the text: the amount precedes the balance
        parsed = parse_money(token)
        if parsed and parsed[0]:
            return parsed[0]
    return 0


def _unread_row(line: str) -> ParsedTransaction:
    date_token = DATE_LIKE.search(strip_explained(line))
    when = BankParser.parse_turkish_date(date_token.group(0)) if date_token else None
    return ParsedTransaction(
        date=when or datetime.now(UTC),
        description=line[:200],
        amount_cents=_first_amount(line),
        tx_type="",
        raw_row=line,
        date_estimated=when is None,
        unread=True,
        confidence_note="satır okunamadı: satır biçimi tanınmadı",
    )


_CURRENCY_CODES = {"tl", "try", "usd", "eur", "gbp"}


def _delimited(line: str) -> bool:
    """A row of a delimited export (an ERP CSV): its other numbers sit in cells of their own (fiş no, account
    code, a running balance the parser does not keep). RULE A (ii) is for free-text layouts, where a stray
    token means the pattern took the wrong one; a delimited row's cells are checked by the unread-line rule."""
    return line.count(";") >= 2 or line.count(chr(9)) >= 2 or line.count(",") >= 4


def _uncertain(line: str, tx: ParsedTransaction) -> bool:
    """RULE A (ii): a money-like token of a matched line that is not the row's amount or balance."""
    consumed = {tx.amount_cents}
    if tx.balance_cents is not None:
        consumed.add(abs(tx.balance_cents))
    for token in money_tokens(line):
        if token.lower() in _CURRENCY_CODES:
            continue                          # the currency suffix of a consumed amount
        parsed = parse_money(token)
        if parsed is None:
            return True                       # a number word ("bin", "lira") beside a matched row
        if parsed[0] in consumed:
            continue
        # A plain integer inside the description ("FATURA 12345") is a reference, not money; anything with
        # separators, decimals or a currency mark is money.
        if _BIG_INTEGER.fullmatch(token) and token in tx.description:
            continue
        return True
    return False


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
            if not _delimited(line) and _uncertain(line, last_tx):
                last_tx.amount_uncertain = True
                # The first money token of the line, in text order: the amount precedes the balance. The row is
                # held either way; a person sees this value beside the raw line.
                last_tx.amount_cents = _first_amount(line) or last_tx.amount_cents
                last_tx.confidence_note = "tutar belirsiz: satırda satırın tutarı/bakiyesi olmayan bir sayı var"
            out.append(last_tx)
            previous_is_row = True
            continue
        if is_summary_phrase(_words(line)):
            acct.summary.append(line[:120])
            previous_is_row = False
            continue
        if is_candidate(line):
            # Before the first row, a line with no amount is a title ("Dönem: 01.01.2024 - 31.01.2024" is
            # also explained above); inside and after the body, and in a text nothing parsed, every candidate is held.
            if first < 0 or i > first or money_tokens(line):
                last_tx = _unread_row(line)
                out.append(last_tx)
                acct.unread += 1
                previous_is_row = True
                continue
        if _is_header(line):
            acct.non_row += 1
            previous_is_row = False
            continue
        if previous_is_row and last_tx is not None and not is_candidate(line) \
                and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", line) and len(line) <= 80 and not re.match(r"(?i)^(sayfa|page)\b", line):
            last_tx.description = f"{last_tx.description} {line}".strip()[:300]
            acct.continuation += 1
            continue
        acct.non_row += 1
        previous_is_row = False
    out.extend(pending)         # kept, never lost: rows the matching could not place
    return acct
