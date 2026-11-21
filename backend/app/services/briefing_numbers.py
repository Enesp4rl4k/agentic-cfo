"""The anti-hallucination gate of the briefings: every number in a narrative must be a known fact."""
from __future__ import annotations

import re

from app.services.rag.grounding_validator import parse_numeric_token

_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
# Money is written to the lira or to the kuruş; nothing looser counts as the same figure.
_ROUNDING = 0.5


def _date_parts(*days: str | None) -> set[int]:
    """Year, month and day numbers of the dates the briefing itself states."""
    parts: set[int] = set()
    for day in days:
        if day:
            parts.update(int(p) for p in re.findall(r"\d+", day))
    return parts


def verify_narrative_numbers(
    narrative: str,
    allowed_cents: set[int],
    *,
    allowed_plain: set[int] | None = None,
) -> bool:
    """Anti-hallucination gate: every number in the narrative must be a known fact.

    A number is a fact when it is one of the verified amounts (to the lira or the
    kuruş, no looser) or a date part the briefing itself states. Days, counts and
    percentages count as claims too: nothing here computed them.
    """
    allowed_liras = {abs(c) / 100.0 for c in allowed_cents if c is not None}
    plain = allowed_plain or set()
    for raw in _NUMBER.findall(narrative or ""):
        value = parse_numeric_token(raw)
        if value is None:
            return False
        if value.is_integer() and int(value) in plain:
            continue
        if any(abs(value - known) <= _ROUNDING for known in allowed_liras):
            continue
        return False
    return True
