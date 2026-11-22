"""Two checks on the TEXT of an amount that `parse_money` deliberately does not make.

`parse_money` is lenient on purpose: it reads a statement cell ("1.234,56 TL", "Tutar: 500") by keeping the digits and
dropping the rest, and it reads "1.234" as Turkish thousands. A source that STATES an amount in a field (an API, a
sync) must not be read that way: "x1" is not 1, and "1.500" with no locale evidence is not 1500. These two functions
say so; `app.services.ingest.feed.read_money` applies them before it calls `parse_money`.
"""
from __future__ import annotations

import re
from typing import Any

from app.parsers.direction import _CURRENCY_TOKEN

_WELLFORMED = re.compile(
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?: \d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
)


def money_is_wellformed(raw: Any) -> bool:
    """True when a TEXT amount is a number and nothing else around a sign, brackets or a currency mark.

    `parse_money` is deliberately lenient for a statement cell ("1.234,56 TL", "Tutar: 500"): it keeps the digits and
    drops the rest, so "x1" reads as 1 and "12abc34" as 1234. A source that STATES an amount in a field must not be
    read that way: a garbled amount is unreadable, not whatever digits survive.
    """
    if raw is None or isinstance(raw, (bool, int, float)):
        return True
    text = _CURRENCY_TOKEN.sub("", str(raw).replace(" ", " ").replace("−", "-").replace("–", "-")).strip()
    text = re.sub(r"^[+-]\s*|\s*-$", "", text.strip("()").strip())
    return _WELLFORMED.fullmatch(text) is not None


def money_is_ambiguous(raw: Any) -> bool:
    """True when a TEXT amount can be read two ways and nothing in it says which.

    "1.500" and "1,500" are one thousand five hundred (thousands separator) or one and a half (decimal
    comma/point): `parse_money` takes the Turkish reading, which is right for a Turkish statement and wrong
    for an API that sends a dot decimal. A source with no stated number format must not have that guessed
    for it: it holds the row. A JSON number is exact and never ambiguous; "1.500,00", "1500.50" and
    "1.234.567" carry their own evidence.
    """
    if raw is None or isinstance(raw, (bool, int, float)):
        return False
    text = _CURRENCY_TOKEN.sub("", str(raw).replace("\xa0", " ")).strip()
    digits = re.sub(r"[^\d,.]", "", text)
    for sep in (",", "."):
        other = "." if sep == "," else ","
        if other not in digits and digits.count(sep) == 1:
            head, tail = digits.split(sep)
            return len(tail) == 3 and tail.isdigit() and head.isdigit() and (len(head) <= 3)
    return False
