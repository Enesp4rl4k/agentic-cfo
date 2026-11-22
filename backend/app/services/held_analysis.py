"""Analyses waiting for a person: why each was held, and the owner's answer.

A run that ends `awaiting_review` finished its work but is not the company's yet:
the confidence gate (or a step that asked for a person) held it. Until someone
decides, the company view, the ledger append and the cash radar do not use it.

This module only describes ("why was it held?") and records the answer; the
routes in `app.api.analysis` and the setup page's facts (`app.api.baslangic`)
both read it, so a held analysis is described once. Wording lives in the frontend:
reasons are codes with their numbers.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN

# Reason codes, in the order a person should read them.
CONFIDENCE_LOW = "confidence_low"
WEAKEST_STEP = "weakest_step"
STEP_FLAGGED = "step_flagged"
ROWS_WAITING = "rows_waiting"
UNSPECIFIED = "unspecified"


def held_by(result: dict[str, Any]) -> dict[str, Any] | None:
    """What the finished run says held it: its weakest step, with the step's own words.

    The run's logs say a step "was ok"; the gate's reason is in the confidence breakdown
    (`app.agents.confidence_breakdown`), which is not kept on the job. Saved at the moment the
    run is held, so the person deciding reads the run's own explanation, not a guess.
    """
    breakdown = result.get("confidence_breakdown") or {}
    binding = breakdown.get("binding_constraint")
    if not binding:
        return None
    for component in breakdown.get("components") or []:
        if component.get("step") == binding:
            confidence = component.get("confidence")
            return {
                "step": str(binding),
                "detail": str(component.get("detail") or ""),
                "confidence": float(confidence) if isinstance(confidence, int | float) else None,
            }
    return {"step": str(binding), "detail": "", "confidence": None}


def why_held(job: AnalysisJob) -> list[dict[str, Any]]:
    """The facts behind a hold, read from what the run itself recorded."""
    meta = job.result_metadata or {}
    reasons: list[dict[str, Any]] = []
    ingest = meta.get("ingest") or {}
    held_rows = int(ingest.get("held") or 0)
    if held_rows and not int(ingest.get("processed") or 0):
        # Every row waits for a person: the run's 0% confidence is only that, not a judgement of the file.
        return [{"code": ROWS_WAITING, "count": held_rows, "all_rows": True, "summary": str(ingest.get("summary") or "")}]
    below_gate = job.min_confidence is not None and float(job.min_confidence) < CONFIDENCE_AUTO_PROCEED_MIN
    if below_gate:
        reasons.append({
            "code": CONFIDENCE_LOW,
            "min_confidence": float(job.min_confidence),  # type: ignore[arg-type]
            "threshold": CONFIDENCE_AUTO_PROCEED_MIN,
        })
    weakest = meta.get("held_by")
    if isinstance(weakest, dict) and weakest.get("step"):
        reasons.append({"code": WEAKEST_STEP, **weakest})
    for log in job.logs or []:
        # A failed step other than the verifier (whose message is the gate itself).
        if isinstance(log, dict) and log.get("ok") is False and log.get("step") != "verifier":
            reasons.append({
                "code": STEP_FLAGGED,
                "step": str(log.get("step") or ""),
                "detail": str(log.get("detail") or ""),
            })
    if held_rows:
        reasons.append({"code": ROWS_WAITING, "count": held_rows, "all_rows": False, "summary": str(ingest.get("summary") or "")})
    return reasons or [{"code": UNSPECIFIED}]


def proves_balance(job: AnalysisJob) -> bool:
    """True when the run read a statement whose running balances chain."""
    return bool((job.result_metadata or {}).get("closing_balance"))


def describe(job: AnalysisJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "filename": job.filename,
        "min_confidence": float(job.min_confidence) if job.min_confidence is not None else None,
        "reasons": why_held(job),
        "proves_balance": proves_balance(job),
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _scope(org_id: str | None, user_id: str):  # type: ignore[no-untyped-def]
    return AnalysisJob.org_id == org_id if org_id else AnalysisJob.user_id == user_id


async def list_held(db: AsyncSession, org_id: str | None, user_id: str) -> list[AnalysisJob]:
    """Analyses of this company (or, with no company, this user's) awaiting a decision, oldest first."""
    rows = await db.execute(
        select(AnalysisJob)
        .where(
            _scope(org_id, user_id),
            AnalysisJob.status == JobStatus.AWAITING_REVIEW,
        )
        .order_by(AnalysisJob.created_at, AnalysisJob.id)
    )
    return list(rows.scalars().all())
