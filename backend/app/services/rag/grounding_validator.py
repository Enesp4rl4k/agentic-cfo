"""
Grounding validator — checks that LLM responses respect evidence boundaries.

Rule: if factual financial claims appear without citations, flag for review.
Does NOT call LLM — deterministic regex/heuristics only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.platform.contracts import EvidenceBundle

# Turkish + English currency/amount patterns
_AMOUNT_PATTERN = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:TL|₺|TRY|USD|\$|EUR|€|%|percent)",
    re.IGNORECASE,
)


@dataclass
class GroundingVerdict:
    grounded: bool
    requires_disclaimer: bool
    flagged_claims: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def validate_grounding(
    response_text: str,
    evidence: EvidenceBundle | None,
    *,
    strict: bool = True,
) -> GroundingVerdict:
    """
    Validate assistant response against retrieved evidence.

    strict=True: any amount-like claim without evidence → requires disclaimer
    """
    text = (response_text or "").strip()
    if not text:
        return GroundingVerdict(grounded=True, requires_disclaimer=False)

    amounts = _AMOUNT_PATTERN.findall(text)
    has_evidence = evidence is not None and evidence.found

    if not amounts:
        return GroundingVerdict(grounded=True, requires_disclaimer=False)

    if has_evidence:
        return GroundingVerdict(grounded=True, requires_disclaimer=False)

    flagged = amounts[:5]
    reasons = [
        "Response contains numeric/currency claims without retrieved evidence.",
    ]
    if strict:
        return GroundingVerdict(
            grounded=False,
            requires_disclaimer=True,
            flagged_claims=flagged,
            reasons=reasons,
        )

    return GroundingVerdict(
        grounded=False,
        requires_disclaimer=True,
        flagged_claims=flagged,
        reasons=reasons,
    )


DISCLAIMER_TR = (
    "Not: Bu yanıt yüklenen belgelerden otomatik kanıt bulamadığı için "
    "sayısal ifadeler doğrulanmamıştır. Karar öncesi kaynak verileri kontrol edin."
)

DISCLAIMER_EN = (
    "Note: No evidence was retrieved from indexed documents. "
    "Numeric claims are unverified — check source data before acting."
)


def apply_disclaimer(response_text: str, verdict: GroundingVerdict, *, locale: str = "tr") -> str:
    if not verdict.requires_disclaimer:
        return response_text
    disclaimer = DISCLAIMER_TR if locale.startswith("tr") else DISCLAIMER_EN
    return f"{response_text.rstrip()}\n\n---\n{disclaimer}"
