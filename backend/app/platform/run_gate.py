"""The confidence gate every role passes through (CLAUDE.md: `runAgent`, law 10).

The gate lived only in the CFO pipeline. The other roles either had their own
threshold (CEO 0.75) or none: CHRO, Risk, Audit and Compliance logged
`{node, status, message}` with no confidence anywhere, so they always
auto-proceeded into the company's context (plan v9 §K0 / §V6 S1).

One contract, one decision:

- every role's log entries read as `StepResult`, whichever shape they were
  written in;
- a run is held if any step failed, reports `needs_review`, or is below the
  threshold, and also if **no step measured its confidence**. Unknown is not
  calm: until a role measures itself (§V6 S3), a person looks at its output.

A skipped step has no confidence (None, not 1.0) and does not count.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN

OK = "ok"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(frozen=True)
class StepResult:
    step: str
    ok: bool
    status: str                     # ok | skipped | failed
    confidence: float | None = None
    needs_review: bool = False
    detail: str | None = None
    data_source: str | None = None


@dataclass(frozen=True)
class GateDecision:
    awaiting_review: bool
    min_confidence: float | None
    reasons: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "awaiting_review": self.awaiting_review,
            "min_confidence": self.min_confidence,
            "reasons": list(self.reasons),
            "steps": [dataclasses.asdict(s) for s in self.steps],
        }


def _as_dict(entry: Any) -> dict[str, Any] | None:
    if dataclasses.is_dataclass(entry) and not isinstance(entry, type):
        return dataclasses.asdict(entry)
    return entry if isinstance(entry, dict) else None


def _step_result(entry: Any) -> StepResult | None:
    """One log entry as a StepResult; None for a "started" marker or junk."""
    raw = _as_dict(entry)
    if raw is None:
        return None
    name = str(raw.get("step") or raw.get("node") or "?")
    confidence = raw.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    extra: dict[str, Any] = {
        "needs_review": bool(raw.get("needs_review")),
        "detail": raw.get("detail") or raw.get("message"),
        "data_source": raw.get("data_source"),
    }
    status = str(raw.get("status") or "")
    if status == SKIPPED:
        return StepResult(name, True, SKIPPED, None, **extra)
    if "ok" in raw:   # {step, ok, detail, confidence}
        return StepResult(name, bool(raw["ok"]), OK if raw["ok"] else FAILED, confidence, **extra)
    # {node, status, message}
    if status == "started":
        return None
    if status in ("failed", "error"):
        return StepResult(name, False, FAILED, confidence, **extra)
    return StepResult(name, True, OK, confidence, **extra)


def step_results(result: dict[str, Any]) -> list[StepResult]:
    return [s for s in map(_step_result, result.get("logs") or []) if s is not None]


def evaluate(result: dict[str, Any], threshold: float = CONFIDENCE_AUTO_PROCEED_MIN) -> GateDecision:
    """Does this role's result wait for a person?"""
    steps = step_results(result)
    measured = [s.confidence for s in steps if s.confidence is not None]
    declared = result.get("min_confidence")
    # The states start at 1.0 before any step reports, so it says nothing alone.
    if isinstance(declared, (int, float)) and measured:
        measured.append(float(declared))
    lowest = min(measured) if measured else None

    reasons: list[str] = []
    if result.get("error"):
        reasons.append("Koşu hata bildirdi.")
    failed = [s.step for s in steps if s.status == FAILED]
    if failed:
        reasons.append(f"Başarısız adım: {', '.join(failed)}.")
    if result.get("awaiting_review") or result.get("needs_review") or any(s.needs_review for s in steps):
        reasons.append("Bir adım insan incelemesi istedi.")
    if lowest is None:
        reasons.append("Bu rolün güveni ölçülmedi; sonucu bir kişi onaylamalı.")
    elif lowest < threshold:
        reasons.append(f"Güven %{lowest * 100:.0f}, eşik %{threshold * 100:.0f}.")
    return GateDecision(bool(reasons), lowest, reasons, steps)


def inherited_confidence(inputs: list[dict[str, Any] | None]) -> float:
    """What a synthesis may claim: its least certain input, as that input's gate
    recorded it. It started at a constant 1.0 whatever it was built on."""
    known: list[float] = []
    for result in inputs:
        result = result or {}
        value = (result.get("gate") or {}).get("min_confidence", result.get("min_confidence"))
        if isinstance(value, (int, float)):
            known.append(float(value))
    return min(known, default=1.0)
