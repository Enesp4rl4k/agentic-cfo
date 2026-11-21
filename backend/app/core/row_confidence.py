"""What a row's confidence can be: a score in [0, 1], or *unknown*.

A row nobody scored is not an 0.8 row. It used to be: the LLM path filled a
missing score with 0.8 and the gate held only `< 0.80`, so the row the model had
not scored passed unreviewed. Unknown is `None`, end to end (extraction,
`Transaction.confidence` NULL, API `null`), and it is always held for a person.

A score outside [0, 1] (a model answering "95") is not guessed to be a percentage:
it is unknown too.
"""
from __future__ import annotations

import math
from typing import Any

from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN

REVIEW_BELOW: float = CONFIDENCE_AUTO_PROCEED_MIN

UNKNOWN_LABEL = "güven bilinmiyor"


def parse_confidence(raw: Any) -> float | None:
    """The score as a float in [0, 1]; `None` when absent, unreadable or out of range."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or not 0.0 <= value <= 1.0:
        return None
    return value


def needs_review(confidence: float | None) -> bool:
    """Unknown is held; so is anything below the bar."""
    return confidence is None or confidence < REVIEW_BELOW


def label(confidence: float | None) -> str:
    """Honest wording for a person: never a number for an unscored row."""
    return UNKNOWN_LABEL if confidence is None else f"%{round(confidence * 100)}"
