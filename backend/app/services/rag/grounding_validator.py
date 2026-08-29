"""
Grounding validator — checks that LLM responses respect evidence boundaries.

Does NOT call LLM — deterministic regex/heuristics only.

Rules:
  1. No numeric claims → grounded.
  2. Numeric claims with neither evidence nor semantic KPIs → disclaimer.
  3. Numeric claims must match a number in evidence previews or semantic KPIs
     (with cents/major-unit scale tolerance). Presence of unrelated evidence
     is not enough — invented figures are flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.platform.contracts import EvidenceBundle

# Currency / percent amounts (TR + EN grouping)
_AMOUNT_PATTERN = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d+)?)\s*"
    r"(?:TL|₺|TRY|USD|\$|EUR|€|%|percent)",
    re.IGNORECASE,
)

_MONTHS_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:months?|ay(?:lık)?)\b",
    re.IGNORECASE,
)

_GENERIC_NUMBER = re.compile(
    r"(?<![\w/])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d+)?)(?![\w])"
)

_REL_TOL = 0.05
_ABS_TOL = 0.51


@dataclass
class GroundingVerdict:
    grounded: bool
    requires_disclaimer: bool
    flagged_claims: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def parse_numeric_token(raw: str) -> float | None:
    """Parse a TR/EN grouped numeric token into a float."""
    token = (raw or "").strip().replace(" ", "")
    if not token:
        return None
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif token.count(".") > 1:
        token = token.replace(".", "")
    elif token.count(",") > 1:
        token = token.replace(",", "")
    elif "," in token:
        parts = token.split(",")
        token = token.replace(",", ".") if len(parts[-1]) <= 2 else token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


def extract_numeric_claims(text: str) -> list[float]:
    """Extract currency/percent/runway numeric claims from assistant text."""
    values: list[float] = []
    seen: set[float] = set()
    for match in list(_AMOUNT_PATTERN.findall(text or "")) + list(
        _MONTHS_PATTERN.findall(text or "")
    ):
        parsed = parse_numeric_token(match)
        if parsed is None:
            continue
        key = round(parsed, 4)
        if key in seen:
            continue
        seen.add(key)
        values.append(parsed)
    return values


def _numbers_in_text(text: str) -> list[float]:
    values: list[float] = []
    for match in _GENERIC_NUMBER.findall(text or ""):
        parsed = parse_numeric_token(match)
        if parsed is not None:
            values.append(parsed)
    return values


def _expand_scales(value: float) -> list[float]:
    out = [value]
    if abs(value) >= 1:
        out.append(value / 100.0)
        out.append(value * 100.0)
    return out


def _claim_supported(claim: float, supported: list[float]) -> bool:
    for known in supported:
        tol = max(_ABS_TOL, _REL_TOL * max(abs(claim), abs(known), 1.0))
        if abs(claim - known) <= tol:
            return True
        for scaled in _expand_scales(known):
            scale_tol = max(_ABS_TOL, _REL_TOL * max(abs(claim), abs(scaled), 1.0))
            if abs(claim - scaled) <= scale_tol:
                return True
    return False


def _supported_numbers(
    evidence: EvidenceBundle | None,
    semantic_metrics: dict[str, float | int | str | bool | None] | None,
) -> list[float]:
    supported: list[float] = []
    if evidence is not None:
        for citation in evidence.citations:
            supported.extend(_numbers_in_text(citation.preview or ""))
    if semantic_metrics:
        for raw in semantic_metrics.values():
            if isinstance(raw, bool) or raw is None:
                continue
            if isinstance(raw, (int, float)):
                supported.append(float(raw))
            elif isinstance(raw, str):
                parsed = parse_numeric_token(raw)
                if parsed is not None:
                    supported.append(parsed)
    return supported


def validate_grounding(
    response_text: str,
    evidence: EvidenceBundle | None,
    *,
    strict: bool = True,
    semantic_metrics: dict[str, float | int | str | bool | None] | None = None,
) -> GroundingVerdict:
    """
    Validate assistant response against retrieved evidence + semantic KPIs.

    Invented amounts are flagged even when *some* evidence exists, unless the
    claimed figure appears in citations or semantic metrics.
    """
    text = (response_text or "").strip()
    if not text:
        return GroundingVerdict(grounded=True, requires_disclaimer=False)

    claims = extract_numeric_claims(text)
    has_evidence = evidence is not None and evidence.found
    has_semantic = bool(semantic_metrics)
    if evidence is not None:
        has_semantic = has_semantic or any(
            c.source_type == "semantic_snapshot" for c in evidence.citations
        )

    if not claims:
        return GroundingVerdict(grounded=True, requires_disclaimer=False)

    if not has_evidence and not has_semantic:
        flagged = [str(c) for c in claims[:5]]
        return GroundingVerdict(
            grounded=False,
            requires_disclaimer=True,
            flagged_claims=flagged,
            reasons=["Response contains numeric/currency claims without retrieved evidence."],
        )

    supported = _supported_numbers(evidence, semantic_metrics)
    unmatched = [c for c in claims if not _claim_supported(c, supported)]
    if not unmatched:
        return GroundingVerdict(grounded=True, requires_disclaimer=False)

    reasons = [
        "Numeric claims do not match retrieved evidence or semantic KPIs.",
    ]
    flagged = [str(c) for c in unmatched[:5]]
    if strict or unmatched:
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


def no_evidence_verdict() -> GroundingVerdict:
    """Hard gate when dual RAG + semantic KPIs both miss for the query."""
    return GroundingVerdict(
        grounded=False,
        requires_disclaimer=True,
        reasons=["No RAG evidence or semantic metrics were available for this query."],
    )


def apply_disclaimer(response_text: str, verdict: GroundingVerdict, *, locale: str = "tr") -> str:
    if not verdict.requires_disclaimer:
        return response_text
    disclaimer = DISCLAIMER_TR if locale.startswith("tr") else DISCLAIMER_EN
    return f"{response_text.rstrip()}\n\n---\n{disclaimer}"
