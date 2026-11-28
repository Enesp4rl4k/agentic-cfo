"""Identifier detectors for the LLM egress layer: a number is masked only on POSITIVE evidence.

Order of work (the fidelity rule, see `figures`): first every amount, date, time, account code and document
number is classified as data and protected; only then do identifier patterns run, and a candidate that touches
protected data is dropped. A digit run with no label is an identifier only in the shapes below that need none
(an IBAN with its country letters, a printed card grouping, a +90 / spaced phone, a single 11-digit token with
both TCKN check digits, a tax number the books hold), and never when it is protected data.

What counts as evidence, per type (checksum where the type has one, AND shape, AND context):
  IBAN   letters + check digits + the country's exact length + mod 97 (spaces, dashes, line breaks, lower case
         tolerated); digits only (no "TR") need the label IBAN right before them: 24 digits with mod 97, or
         the 22-digit Turkish BBAN (no checksum exists for it: label + exact length + reserved digit 0)
  CARD   Luhn + issuer prefix + (a card label right before it, or the printed 4-4-4-4 / 4-6-5 grouping)
  TCKN   11 digits + both check digits + a label (TC, TCKN, T.C. Kimlik No, kimlik, tc_kimlik_no ...), written
         as one token or, with the label, in groups ("Kimlik: 100 000 001 46"); also a
         BARE 11-digit token with both check digits when `figures` has not classified it as data (decided owner
         trade-off: about 1 in 100 unlabelled 11-digit references is masked too, restored byte-exact; no amount
         or date can be, they are protected first)
  VKN    10 digits + check digit + a label (VKN, Vergi No, Vergi Kimlik No, tax_id ...)
  TEL    a phone shape that no amount has (+90 / 0090 / leading 0, then 3-3-2-2 or 3-3-4 groups separated
         by spaces, dashes or brackets, never dots), or a label (Tel, GSM, Cep, Telefon ...) + 10/11 digits
  MAIL   local@domain, Unicode letters allowed on both sides (IDN domains)
  ACCT   "Hesap No" + digits (no checksum exists)
  PLATE  a label (plaka, araç) + a Turkish plate shape (no checksum exists)
  KNOWN  a tax number the books hold for this organisation, as a whole unprotected digit token

NOT masked by pattern, by design (fidelity outranks coverage; see docs/kvkk/yapay-zeka-veri-akisi.md):
a compact mobile number with no label and no +90 ("05321234567"), an unlabelled VKN, an unlabelled 16-digit
card number, an unlabelled plate. These go as written when they appear in free text: 10- and 16-digit runs
collide with amounts and references far more often than 11-digit TCKN-checksummed ones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.platform.llm_egress.figures import overlaps, protected_spans

IBAN, PAN, EMAIL, PHONE, TCKN, VKN, ACCOUNT_NO, PLATE = "IBAN", "CARD", "MAIL", "TEL", "TCKN", "VKN", "ACCT", "PLATE"
PRIORITY = (IBAN, PAN, EMAIL, PHONE, TCKN, VKN, ACCOUNT_NO, PLATE)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    key: str            # the entity: two spellings of one value share it (one entity number, two placeholders)
    canonical: str = ""


# ── checksums ────────────────────────────────────────────────────────────────

_IBAN_LENGTHS = {
    "TR": 26, "DE": 22, "GB": 22, "FR": 27, "NL": 18, "IT": 27, "ES": 24, "BE": 16, "AT": 20, "CH": 21, "LU": 20,
    "IE": 22, "PL": 28, "RO": 24, "GR": 27, "BG": 22, "CY": 28, "AZ": 28, "GE": 22, "SA": 24, "AE": 23, "QA": 29,
    "KW": 30, "BH": 22, "LT": 20, "LV": 21, "EE": 20, "SE": 24, "NO": 15, "DK": 18, "FI": 18, "PT": 25, "HU": 28,
    "CZ": 24, "SK": 24, "SI": 19, "HR": 21, "RS": 22, "BA": 20, "MK": 19, "AL": 28, "ME": 22, "XK": 20, "MT": 31,
    "IS": 26, "LI": 21, "MC": 27, "SM": 27, "AD": 24, "IL": 23, "JO": 30, "LB": 28, "EG": 29, "UA": 29, "MD": 24,
    "KZ": 20, "TN": 24, "PK": 24, "IQ": 23, "BY": 28, "SC": 31, "MR": 27, "LC": 32, "VG": 24, "GI": 23, "FO": 18,
}


def iban_ok(compact: str) -> bool:
    """ISO 13616: known country, its exact length, mod 97 == 1."""
    if _IBAN_LENGTHS.get(compact[:2]) != len(compact) or not compact[2:4].isdigit():
        return False
    if not compact.isalnum() or not compact.isascii():
        return False
    moved = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def luhn_ok(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


def tckn_ok(d: str) -> bool:
    if len(d) != 11 or not d.isdigit() or d[0] == "0":
        return False
    n = [int(c) for c in d]
    return (sum(n[0:9:2]) * 7 - sum(n[1:8:2])) % 10 == n[9] and sum(n[:10]) % 10 == n[10]


def vkn_ok(d: str) -> bool:
    if len(d) != 10 or not d.isdigit():
        return False
    total = 0
    for i in range(9):
        tmp = (int(d[i]) + (9 - i)) % 10
        part = (tmp * 2 ** (9 - i)) % 9
        total += 9 if tmp != 0 and part == 0 else part
    return (10 - total % 10) % 10 == int(d[9])


# ── labels: the word right before a value (prose, a table header, or a JSON / dict key) ─────────────────

_GAP = r"""(?:['"’]?\s*(?:[:=#\-]|no\b|nr\b|numaras[ıi]\b|numara\b)?\s*['"’]?\s*[:=#\-]?\s*['"’]?\s*)"""


def _label(words: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])(?:" + words + r")" + _GAP + r"$", re.IGNORECASE)


_IBAN_LABEL = _label(r"iban")
_CARD_LABEL = _label(r"kart|kredi\s*kart[ıi]|card|card_?(?:no|number)|kart_?no|pan|visa|mastercard|troy")
_TCKN_LABEL = _label(r"tckn|tc|t\.\s?c\.?|tc\s*kimlik|t\.\s?c\.\s*kimlik|kimlik|tc_?kimlik(?:_?no)?|"
                     r"vatanda[sş]l[ıi]k|identity|national_?id")
_VKN_LABEL = _label(r"vkn|vergi\s*(?:kimlik)?|vergi_?(?:kimlik_?)?no|tax_?(?:id|no|number)|v\.\s?d\.?")
_PHONE_LABEL = _label(r"tel|tel\.|telefon|gsm|cep|cep\s*tel|mobil|mobile|phone|phone_?number|whatsapp|faks|fax")
_ACCOUNT_LABEL = _label(r"hesap|hes\.|account|account_?(?:no|number)|hesap_?no")
_PLATE_LABEL = _label(r"plaka|plakal[ıi]|ara[cç]|plate|ruhsat")


_DIGIT_LABELS = (
    (PAN, _CARD_LABEL), (TCKN, _TCKN_LABEL), (VKN, _VKN_LABEL), (PHONE, _PHONE_LABEL), (ACCOUNT_NO, _ACCOUNT_LABEL),
)


def _labelled(rx: re.Pattern[str], text: str, start: int) -> bool:
    return bool(rx.search(text[max(0, start - 40):start]))


# ── candidate shapes ─────────────────────────────────────────────────────────

_SEP = r"(?:[ \t\- ]|\r?\n){0,2}"
_IBAN_CAND = re.compile(r"(?<![\w])[A-Za-z]{2}\d{2}(?:" + _SEP + r"[A-Za-z0-9]){11,30}")
_DIGITS_CAND = re.compile(r"(?<![\w.,])\d(?:" + _SEP + r"\d){5,25}(?![\w]|[.,]\d)")
_EMAIL = re.compile(r"(?<![\w.+\-])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[^\W\d_]{2,}(?![\w\-])")
_PHONE_SHAPE = re.compile(
    # +90 / 0090 / leading 0, the area code (bracketed or not), then 3-3-2-2 or 3-3-4 groups; after a closing
    # bracket the separator is optional ("+90(532)123-45-67"). Never a dot: "532.123.45.67" reads as a number.
    r"(?<![\w+.,])(?:(?:\+|00)90[ \-]?\(?0?|\(?0 ?)([2-5]\d{2})(?:\)[ \-]?|[ \-])"
    r"(\d{3})[ \-](?:(\d{2})[ \-](\d{2})|(\d{4}))(?![\w]|[.,]\d)"
    r"|(?<![\w+.,])\+90([2-5]\d{9})(?![\w]|[.,]\d)"
)
_CARD_GROUPED = re.compile(r"(?<![\w.,])(?:\d{4}([ \-])\d{4}\1\d{4}\1\d{4}|\d{4}([ \-])\d{6}\2\d{5})(?![\w]|[.,]\d)")
_PLATE = re.compile(r"(?<![\w])(0[1-9]|[1-7]\d|8[01])[ \-]?([A-ZÇĞİÖŞÜ]{1,3})[ \-]?(\d{2,4})(?![\w])")
_IIN = re.compile(r"^(4|5[1-5]|2(?:2[2-9]|[3-6]\d|7[01]|720)|3[47]|9792|6(?:011|5))")


def _compact(raw: str) -> str:
    return re.sub(r"[\s\- ]", "", raw)


def _iban_spans(text: str, protected: list) -> list[Span]:
    out: list[Span] = []
    for m in _IBAN_CAND.finditer(text):
        positions = [i for i in range(m.start(), m.end()) if not (text[i].isspace() or text[i] in "- ")]
        chars = "".join(text[i] for i in positions).upper()
        length = _IBAN_LENGTHS.get(chars[:2])
        if length and len(chars) >= length and iban_ok(chars[:length]):
            out.append(Span(positions[0], positions[length - 1] + 1, IBAN, chars[:length]))
    for m in _DIGITS_CAND.finditer(text):  # digits only: the label IBAN is the evidence
        digits = _compact(m.group(0))
        if not _labelled(_IBAN_LABEL, text, m.start()) or overlaps(protected, m.start(), m.end(), labelled=True):
            continue
        if len(digits) == 24 and iban_ok("TR" + digits):
            out.append(Span(m.start(), m.end(), IBAN, "TR" + digits))
        elif len(digits) == 22 and digits[5] == "0":
            out.append(Span(m.start(), m.end(), IBAN, digits))
    return out


def _digit_spans(text: str, protected: list) -> list[Span]:
    """Card, TCKN, VKN, phone and account numbers written as a digit run: each needs its label right before it.

    A run may continue into unrelated numbers ("Tel 0532 987 65 43 1500 TL"), so the longest PREFIX of whole
    digit groups that is a valid value of a labelled type is taken, and it must not touch protected data."""
    out: list[Span] = []
    for m in _DIGITS_CAND.finditer(text):
        at = m.start()
        types = [t for t, rx in _DIGIT_LABELS if _labelled(rx, text, at)]
        if not types:
            continue
        groups = [(g.start() + at, g.end() + at) for g in re.finditer(r"\d+", m.group(0))]
        for j in range(len(groups), 0, -1):
            end = groups[j - 1][1]
            if overlaps(protected, at, end, labelled=True):
                continue
            span = _classify(text[at:end], types, at, end)
            if span is not None:
                out.append(span)
                break
    return out


def _classify(raw: str, types: list[str], start: int, end: int) -> Span | None:
    digits = _compact(raw)
    single = raw == digits
    if PAN in types and 13 <= len(digits) <= 19 and luhn_ok(digits) and _IIN.match(digits):
        return Span(start, end, PAN, digits)
    # A TCKN with its identity label right before it may be written in groups ("Kimlik: 100 000 001 46"): the label
    # is the evidence, the checksum the shape. Unlabelled, only a single 11-digit token counts (`_bare_tckn_spans`).
    if TCKN in types and tckn_ok(digits):
        return Span(start, end, TCKN, digits)
    if VKN in types and single and vkn_ok(digits):
        return Span(start, end, VKN, digits)
    if PHONE in types and _phone_digits(digits):
        return Span(start, end, PHONE, raw)
    if ACCOUNT_NO in types and 6 <= len(digits) <= 26:
        return Span(start, end, ACCOUNT_NO, raw)
    return None


def _phone_digits(d: str) -> bool:
    if d.startswith("90") and len(d) == 12:
        d = d[2:]
    elif d.startswith("0") and len(d) == 11:
        d = d[1:]
    return len(d) == 10 and d[0] in "2345"


def _card_spans(text: str, protected: list) -> list[Span]:
    out: list[Span] = []
    for m in _CARD_GROUPED.finditer(text):
        digits = _compact(m.group(0))
        if luhn_ok(digits) and _IIN.match(digits) and not overlaps(protected, m.start(), m.end(), labelled=True):
            out.append(Span(m.start(), m.end(), PAN, digits))
    return out


def _phone_spans(text: str, protected: list) -> list[Span]:
    out: list[Span] = []
    for m in _PHONE_SHAPE.finditer(text):
        if not overlaps(protected, m.start(), m.end(), labelled=True):
            out.append(Span(m.start(), m.end(), PHONE, m.group(0)))
    return out


def _plate_spans(text: str, protected: list) -> list[Span]:
    out: list[Span] = []
    for m in _PLATE.finditer(text):
        if _labelled(_PLATE_LABEL, text, m.start()) and not overlaps(protected, m.start(), m.end(), labelled=True):
            out.append(Span(m.start(), m.end(), PLATE, f"{m.group(1)}{m.group(2)}{m.group(3)}"))
    return out


def _email_spans(text: str) -> list[Span]:
    return [Span(m.start(), m.end(), EMAIL, m.group(0).lower()) for m in _EMAIL.finditer(text)] if "@" in text else []


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Keep earlier spans of the input order; drop any that overlaps one already kept."""
    kept: list[Span] = []
    for s in spans:
        if all(s.end <= k.start or s.start >= k.end for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)


def known_identifier_spans(text: str, known: dict[str, str], protected: list | None = None) -> list[Span]:
    """Tax numbers the books hold, wherever they stand as a whole digit token that is not protected data."""
    if not known or not text:
        return []
    protected = protected_spans(text) if protected is None else protected
    out: list[Span] = []
    for m in re.finditer(r"(?<![\w.,])\d{10,11}(?![\w]|[.,]\d)", text):
        label = known.get(m.group(0))
        if label and not overlaps(protected, m.start(), m.end()):
            out.append(Span(m.start(), m.end(), label, m.group(0)))
    return out


_BARE_11 = re.compile(r"(?<![\w.,])\d{11}(?![\w]|[.,]\d)")


def _bare_tckn_spans(text: str, protected: list) -> list[Span]:
    """An unlabelled 11-digit token with both TCKN check digits, unless it is protected data."""
    return [
        Span(m.start(), m.end(), TCKN, m.group(0)) for m in _BARE_11.finditer(text)
        if tckn_ok(m.group(0)) and not overlaps(protected, m.start(), m.end())
    ]


def find_identifiers(text: str, known: dict[str, str] | None = None) -> list[Span]:
    """Every identifier in `text` with positive evidence, overlaps resolved by PRIORITY."""
    if not text:
        return []
    protected = protected_spans(text)
    found = (
        _iban_spans(text, protected) + _card_spans(text, protected) + _email_spans(text)
        + _phone_spans(text, protected) + _digit_spans(text, protected) + _plate_spans(text, protected)
        + _bare_tckn_spans(text, protected)
        + known_identifier_spans(text, known or {}, protected)
    )
    found.sort(key=lambda s: (PRIORITY.index(s.label), s.start))
    return resolve_overlaps(found)
