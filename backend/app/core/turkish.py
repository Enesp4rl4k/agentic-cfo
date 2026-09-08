"""Türkçe metni işaretlerinden arındırma — eşleştirme için.

Turkish text arrives without its diacritics far more often than with them. ERP
exports, bank statements and older accounting systems write "maas odemesi",
"dogalgaz faturasi", "kira odemesi" — and a keyword list spelled "maaş",
"doğalgaz", "kira" matches the third and misses the first two.

That is not a cosmetic loss: a payroll line that fails to match `salary` lands
in `other_expense`, and every report that groups by category is quietly wrong
about where the money went.

Fold both sides before comparing. Never fold for display: the company's name is
"Yıldız Tekstil", not "Yildiz Tekstil".
"""
from __future__ import annotations

# Both cases, and the combining dot that `"İ".lower()` leaves behind.
_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "I": "i",
    "ğ": "g", "Ğ": "g",
    "ş": "s", "Ş": "s",
    "ö": "o", "Ö": "o",
    "ü": "u", "Ü": "u",
    "ç": "c", "Ç": "c",
    "̇": "",
})


def fold(text: str | None) -> str:
    """Lower-case and strip Turkish diacritics, for matching only.

    `"İ".lower()` is `i` followed by U+0307 (combining dot above), so the
    lowering happens first and the combining mark is folded away after.
    """
    return (text or "").lower().translate(_FOLD)


def contains(haystack: str | None, needle: str) -> bool:
    """Does `haystack` contain `needle`, ignoring case and Turkish diacritics?"""
    return fold(needle) in fold(haystack)
