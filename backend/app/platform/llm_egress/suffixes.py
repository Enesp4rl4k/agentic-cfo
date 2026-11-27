"""A bounded grammar of Turkish suffixes that may follow a name WITHOUT an apostrophe ("Yılmazın", "Gıdaya").

Folded forms only (ı->i, ü->u, ö->o, ş->s, ç->c, ğ->g: `names.fold`), so vowel harmony needs no table.
Built as (plural)? (possessive)? (case)? (ki | copula)?, each slot from a short closed list, at most
MAX_SUFFIX letters: a finite set, never "any letters after the name".
"""
from __future__ import annotations

from itertools import product

_PLURAL = ("", "lar", "ler")
_POSSESSIVE = ("", "i", "u", "si", "su", "in", "un", "imiz", "umuz", "iniz", "unuz", "leri", "lari")
_CASE = (
    "", "a", "e", "ya", "ye", "na", "ne", "i", "u", "yi", "yu", "ni", "nu",
    "da", "de", "ta", "te", "nda", "nde", "dan", "den", "tan", "ten", "ndan", "nden",
    "in", "un", "nin", "nun", "la", "le", "yla", "yle", "ca", "ce", "yken",
)
_TAIL = ("", "ki", "dir", "dur", "tir", "tur")

MAX_SUFFIX = 9
SUFFIXES: frozenset[str] = frozenset(
    s for s in ("".join(p) for p in product(_PLURAL, _POSSESSIVE, _CASE, _TAIL)) if 0 < len(s) <= MAX_SUFFIX
)
