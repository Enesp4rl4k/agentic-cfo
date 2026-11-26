"""Identifier detectors for the LLM egress layer: patterns plus the check digits that exist.

Every detector returns spans of the ORIGINAL text. A span is only returned when the identifier is
valid by its own checksum (IBAN mod 97, TCKN, VKN, Luhn) AND the context says it is an identifier and
not an amount: an 11-digit lira amount with a correct TCKN checksum is not a person. Nothing here
touches a number with a thousand separator, a decimal comma, a currency next to it, or a date.

Residual risk, stated plainly: an identifier in a shape no pattern knows (a passport number, a
free-text "my number is ...") is not found. Detecting is a filter, not a proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Placeholder labels, in the order spans win an overlap (first wins).
IBAN, PAN, EMAIL, PHONE, TCKN, VKN, ACCOUNT_NO, PLATE = (
    "IBAN", "KART", "E_POSTA", "TELEFON", "TCKN", "VKN", "HESAP_NO", "PLAKA",
)
PRIORITY = (IBAN, PAN, EMAIL, PHONE, TCKN, VKN, ACCOUNT_NO, PLATE)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    key: str            # canonical form: two spellings of one value share it
    canonical: str = ""  # what to show when restoring (empty: the text as it stood)


# ── checksums ────────────────────────────────────────────────────────────────

def iban_ok(compact: str) -> bool:
    """ISO 13616 mod 97; a Turkish IBAN is exactly 26 characters."""
    if not (15 <= len(compact) <= 34) or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    if compact[:2] == "TR" and len(compact) != 26:
        return False
    if not compact.isalnum() or not compact.isascii():
        return False
    moved = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


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
    if len(d) != 11 or d[0] == "0":
        return False
    n = [int(c) for c in d]
    return (sum(n[0:9:2]) * 7 - sum(n[1:8:2])) % 10 == n[9] and sum(n[:10]) % 10 == n[10]


def vkn_ok(d: str) -> bool:
    if len(d) != 10:
        return False
    total = 0
    for i in range(9):
        tmp = (int(d[i]) + (9 - i)) % 10
        part = (tmp * 2 ** (9 - i)) % 9
        total += 9 if tmp != 0 and part == 0 else part
    return (10 - total % 10) % 10 == int(d[9])


# ── context ──────────────────────────────────────────────────────────────────

_AMOUNT_CUE = re.compile(
    r"(tutar|bakiye|toplam|amount|total|balance|price|fiyat|bedel|borç|borc|alacak|kdv|"
    r"kuru[sş]|cents|kurus|\btl\b|\btry\b|\busd\b|\beur\b|\bgbp\b|₺|\$|€|£)",
    re.IGNORECASE,
)
_TCKN_CUE = re.compile(r"(\btc\b|t\.c\.|tckn|kimlik|vatanda[sş]|identity)", re.IGNORECASE)
_VKN_CUE = re.compile(r"(vkn|vergi\s*(kimlik|no|numaras)|v\.?\s?d\.?\s*no|tax\s*(id|no|number))", re.IGNORECASE)
_CARD_CUE = re.compile(r"(kart|card|\bpan\b|visa|master|troy|cvv)", re.IGNORECASE)
_PHONE_CUE = re.compile(r"(tel|gsm|cep|phone|mobile|whatsapp|fax|faks)", re.IGNORECASE)
_PLATE_CUE = re.compile(r"(plaka|ara[cç]|plate|ruhsat)", re.IGNORECASE)


def _window(text: str, start: int, end: int, before: int = 30, after: int = 12) -> tuple[str, str]:
    return text[max(0, start - before):start], text[end:end + after]


def _glued_to_amount_punctuation(text: str, start: int, end: int) -> bool:
    """A digit run glued to `.` or `,` and another digit is part of an amount, never an identifier."""
    if start >= 2 and text[start - 1] in ".," and text[start - 2].isdigit():
        return True
    return end + 1 < len(text) and text[end] in ".," and text[end + 1].isdigit()


# ── patterns ─────────────────────────────────────────────────────────────────

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_IBAN_CAND = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]){11,32}")
_DIGIT_RUN = re.compile(r"(?<![\d])\d{10,11}(?!\d)")
_PAN_CAND = re.compile(r"(?<![\d.,])\d(?:[ -]?\d){12,18}(?![\d])")
_PHONE = re.compile(
    r"(?<![\w.,+])(?:(?:\+|00)90[\s.-]?|0)?\(?([2-5]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{2})[\s.-]?(\d{2})(?![\d])"
)
_ACCOUNT_NO = re.compile(r"hesap\s*(?:no|numaras[ıi])\s*[:\-]?\s*(\d[\d\s\-]{5,}\d)", re.IGNORECASE)
_PLATE = re.compile(
    r"(?<![\w])(0[1-9]|[1-7]\d|8[01])[ -]?([A-ZÇĞİÖŞÜ]{1,3})[ -]?(\d{2,4})(?![\w])"
)
_NOT_A_PLATE = frozenset({"TL", "TRY", "USD", "EUR", "GBP", "KG", "ADT", "KDV", "AD", "LT", "GR", "CM", "MM", "MT", "AY",
    # month abbreviations: "05 MAR 24" is a date, not a plate
    "OCA", "ŞUB", "SUB", "MAR", "NİS", "NIS", "MAY", "HAZ", "TEM", "AĞU", "AGU", "EYL", "EKİ", "EKI", "KAS", "ARA",
    "JAN", "FEB", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
})
_PLATE_SHAPES = {(1, 4), (1, 3), (2, 3), (2, 4), (2, 2), (3, 2), (3, 3)}
_IIN_PLAIN = re.compile(r"^(4|5[1-5]|2[2-7]|3[47]|9792|6[0245])")


def _iban_spans(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _IBAN_CAND.finditer(text):
        positions = [i for i in range(m.start(), m.end()) if text[i] != " "]
        chars = "".join(text[i] for i in positions).upper()
        for length in range(min(34, len(chars)), 14, -1):
            if iban_ok(chars[:length]):
                out.append(Span(positions[0], positions[length - 1] + 1, IBAN, chars[:length]))
                break
    return out


def _pan_spans(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _PAN_CAND.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if not (13 <= len(digits) <= 19) or not luhn_ok(digits):
            continue
        before, _ = _window(text, m.start(), m.end())
        grouped = bool(re.search(r"[ -]", raw))
        if grouped or _CARD_CUE.search(before) or (len(digits) >= 15 and _IIN_PLAIN.match(digits)):
            out.append(Span(m.start(), m.end(), PAN, digits))
    return out


def _tax_spans(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _DIGIT_RUN.finditer(text):
        d = m.group(0)
        if _glued_to_amount_punctuation(text, m.start(), m.end()):
            continue
        before, after = _window(text, m.start(), m.end())
        if len(d) == 11 and tckn_ok(d):
            id_cue = bool(_TCKN_CUE.search(before))
            if id_cue or not (_AMOUNT_CUE.search(before[-22:]) or _AMOUNT_CUE.search(after[:8])):
                out.append(Span(m.start(), m.end(), TCKN, d))
        elif len(d) == 10 and vkn_ok(d) and _VKN_CUE.search(before):
            out.append(Span(m.start(), m.end(), VKN, d))
    return out


def _phone_spans(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _PHONE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if _glued_to_amount_punctuation(text, m.start(), m.end()):
            continue
        before, _ = _window(text, m.start(), m.end(), 20, 0)
        prefixed = raw.lstrip().startswith(("+", "0"))
        separated = bool(re.search(r"[\s.()-]", raw.strip()))
        if not (prefixed or separated or _PHONE_CUE.search(before)):
            continue  # a bare ten-digit run is more often an amount or a document number
        if _AMOUNT_CUE.search(before[-10:]) and not prefixed:
            continue
        out.append(Span(m.start(), m.end(), PHONE, digits[-10:]))
    return out


def _account_spans(text: str) -> list[Span]:
    return [
        Span(m.start(1), m.end(1), ACCOUNT_NO, re.sub(r"\D", "", m.group(1)))
        for m in _ACCOUNT_NO.finditer(text)
    ]


def _plate_spans(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _PLATE.finditer(text):
        letters = m.group(2)
        if letters in _NOT_A_PLATE or _glued_to_amount_punctuation(text, m.start(), m.end()):
            continue
        if (len(letters), len(m.group(3))) not in _PLATE_SHAPES:
            continue
        before, _ = _window(text, m.start(), m.end(), 20, 0)
        spaced = m.group(0) != re.sub(r"[ -]", "", m.group(0))
        if spaced or _PLATE_CUE.search(before):
            out.append(Span(m.start(), m.end(), PLATE, f"{m.group(1)}{letters}{m.group(3)}"))
    return out


def _email_spans(text: str) -> list[Span]:
    return [Span(m.start(), m.end(), EMAIL, m.group(0).lower()) for m in _EMAIL.finditer(text)]


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Keep earlier spans of the input order; drop any that overlaps one already kept."""
    kept: list[Span] = []
    for s in spans:
        if all(s.end <= k.start or s.start >= k.end for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)


def find_identifiers(text: str) -> list[Span]:
    """Every identifier in `text`, overlaps resolved by PRIORITY (a card number is not also a phone)."""
    found = (
        _iban_spans(text) + _pan_spans(text) + _email_spans(text) + _phone_spans(text)
        + _tax_spans(text) + _account_spans(text) + _plate_spans(text)
    )
    found.sort(key=lambda s: (PRIORITY.index(s.label), s.start))
    return resolve_overlaps(found)
