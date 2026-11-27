"""Numbers that are DATA, found before any identifier pattern runs: amounts, dates, times, account codes,
document numbers. Whatever this module marks is protected: no identifier detector may touch it.

The rule the egress layer keeps (and `tests/test_llm_egress_fidelity.py` fuzzes at 200,000+ lines): a figure
from the books is never altered. So the default for a number is "data"; only positive evidence (a checksum
AND a shape AND a label or an unambiguous format, see `detectors`) makes it an identifier, and even then not
when this module has already classified the same characters as an amount, a date or a document number.

Classified as data (each a whole numeric token: never the middle of a longer digit run):
  amounts   with tr-TR or en-US separators (1.234.567,89 / 1,234,567.89 / 1 234 567,89 / 41176993.01), a
            sign, or a currency / percent / amount word next to a plain integer (60 TL, %18, Tutar 1500)
  dates     12.03.2026, 2026-03-12, 12/03/26, compact 20260312 or 12032026 when it is a real calendar day
  times     14:05, 14:05:33
  codes     THP account codes 120.01.001, 770.1
  documents the value after a document label (Fatura No, Belge No, Fiş No, Dekont, Ref, ETTN, Sipariş No ...)
"""
from __future__ import annotations

import re
from datetime import date

_NOT_GLUED_BEFORE = r"(?<![\w.,])"           # not inside a longer number or word
_NOT_GLUED_AFTER = r"(?![\w]|[.,]\d)"         # and not followed by more of one

# 1.234.567,89 | 1,234,567.89 | 1 234 567,89 | 1'234'567.89 (grouped: separators every three digits)
_GROUPED = re.compile(
    _NOT_GLUED_BEFORE + r"[+\-−]?\d{1,3}(?:(?P<sep>[.,'   ])\d{3})(?:(?P=sep)\d{3})*(?:[.,]\d{1,4})?"
    + _NOT_GLUED_AFTER
)
# 41176993.01 | 1500,5 | -0.25 (one decimal separator, 1-4 decimals)
_DECIMAL = re.compile(_NOT_GLUED_BEFORE + r"[+\-−]?\d+[.,]\d{1,4}" + _NOT_GLUED_AFTER)
# THP account codes and dotted section numbers: 120.01.001, 770.1.2 (two or more dots, or 3-digit head)
_ACCOUNT_CODE = re.compile(_NOT_GLUED_BEFORE + r"\d{3}(?:\.\d{1,3}){1,4}" + _NOT_GLUED_AFTER)
_DATE_SEP = re.compile(
    _NOT_GLUED_BEFORE + r"(?:\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}[./\-]\d{1,2}[./\-]\d{1,2})" + _NOT_GLUED_AFTER
)
_TIME = re.compile(_NOT_GLUED_BEFORE + r"\d{1,2}:\d{2}(?::\d{2})?" + _NOT_GLUED_AFTER)
_INTEGER = re.compile(r"(?<![\w.,])[+\-−]?\d+(?![\w]|[.,]\d)")
_COMPACT_DATE = re.compile(r"(?<![\w.,])\d{8}(?![\w]|[.,]\d)")

_CURRENCY = r"(?:tl|try|ytl|usd|eur|gbp|chf|jpy|rub|kuruş|kurus|krş|krs|lira|dolar|euro|avro|sterlin)"
# a currency right before the number, a sign allowed between them ("EUR+71862066848", "TL−4.105,00")
_SYMBOL_BEFORE = re.compile(r"(?:[₺$€£%]|\b" + _CURRENCY + r")\s{0,2}[+\-−]?\s{0,2}$", re.IGNORECASE)
_SYMBOL_AFTER = re.compile(r"^\s{0,2}(?:[₺$€£%]|" + _CURRENCY + r"\b)", re.IGNORECASE)
_AMOUNT_WORD = re.compile(
    r"(?:tutar[ıi]?|toplam[ıi]?|bakiye(?:si)?|net|brüt|brut|ciro(?:su)?|gelir(?:i)?|gider(?:i)?|kâr|kar|zarar|"
    r"kalan|borç|borc|alacak|ödeme|odeme|tahsilat|havale|eft|fast|kdv|stopaj|matrah|fiyat|bedel|ücret|ucret|"
    r"maaş|maas|kira|amount|total|balance|price|sum|revenue|cost|adet|miktar|qty)"
    r"\s*(?:tutar[ıi]|toplam[ıi])?\s*[:=]?\s{0,3}$",
    re.IGNORECASE,
)
# A document's own number: protected as text, whatever its digits look like.
_DOCUMENT_VALUE = re.compile(
    r"(?:fatura|belge|fi[şs]|makbuz|dekont|irsaliye|sipari[şs]|po|order|invoice|receipt|evrak|i[şs]lem|"
    r"referans|ref|seri|sıra|sira|ettn|uuid|kayıt|kayit|yevmiye|fiş)"
    r"\s*(?:no|nr|numaras[ıi]|numara|kodu|#)?\s*[:.#\-]?\s{0,3}"
    r"(?P<value>[A-Za-z]{0,6}[\-/]?\d[\w\-/.]*)",
    re.IGNORECASE,
)


def _real_compact_date(digits: str) -> bool:
    for y, m, d in ((digits[:4], digits[4:6], digits[6:]), (digits[4:], digits[2:4], digits[:2])):
        try:
            year = int(y)
            if 1900 <= year <= 2100:
                date(year, int(m), int(d))
                return True
        except ValueError:
            continue
    return False


def _real_date(token: str) -> bool:
    parts = re.split(r"[./\-]", token)
    if len(parts) != 3:
        return False
    try:
        a, b, c = (int(p) for p in parts)
    except ValueError:
        return False
    if len(parts[0]) == 4:
        return 1 <= b <= 12 and 1 <= c <= 31
    return (1 <= a <= 31 and 1 <= b <= 12) or (1 <= b <= 31 and 1 <= a <= 12)


def protected_spans(text: str) -> list[tuple[int, int, bool]]:
    """Ranges of `text` that are data (amounts, dates, codes, document numbers), as (start, end, strong).

    `strong` is False only for a grouped integer with no decimals, no currency and no amount word next to it
    ("532 987", "1.234.567"): an identifier with its own label right before it ("Tel: 532 987 65 43") may
    claim those characters. Everything else is strong: no identifier may touch it, labelled or not."""
    if not text or not any(c.isdigit() for c in text):
        return []
    spans: list[tuple[int, int, bool]] = []
    spans += [(m.start(), m.end(), True) for m in _DATE_SEP.finditer(text) if _real_date(m.group(0))]
    for rx in (_DECIMAL, _ACCOUNT_CODE, _TIME):
        spans += [(m.start(), m.end(), True) for m in rx.finditer(text)]
    for m in _GROUPED.finditer(text):
        before, after = text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 12]
        strong = bool(re.search(r"[.,]\d{1,4}$", m.group(0)) and m.group("sep") not in m.group(0)[-5:]) or _cued(before, after)
        spans.append((m.start(), m.end(), strong))
    spans += [(m.start(), m.end(), True) for m in _COMPACT_DATE.finditer(text) if _real_compact_date(m.group(0))]
    for m in _INTEGER.finditer(text):
        if _cued(text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 12]):
            spans.append((m.start(), m.end(), True))
    for m in _DOCUMENT_VALUE.finditer(text):
        if re.search(r"\d", m.group("value")):
            spans.append((m.start("value"), m.end("value"), True))
    return spans


def _cued(before: str, after: str) -> bool:
    return bool(_SYMBOL_BEFORE.search(before) or _SYMBOL_AFTER.search(after) or _AMOUNT_WORD.search(before))


def overlaps(spans: list[tuple[int, int, bool]], start: int, end: int, *, labelled: bool = False) -> bool:
    """True when [start, end) touches protected data (a labelled identifier may take weak spans)."""
    return any(s < end and start < e and (strong or not labelled) for s, e, strong in spans)
