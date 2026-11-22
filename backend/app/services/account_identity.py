"""A person's answer to "Bu ekstreler aynı banka hesabına mı ait?" (see `bank_accounts`).

Two proven statements nothing links or separates are never summed. The owner (or an admin) answers once
per pair: same account (they are joined, the newest balance is the account's, a missing statement between
them is named) or different accounts (they add up). The answer is a recorded decision whose `after` holds
the statements on both sides, so a later statement that chains onto either side is covered by it; changing
the answer supersedes the earlier one (nothing is deleted) and the cash is recomputed on the next read.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import DecidedVia, DecisionKind
from app.services.decisions import list_decisions, record_decision

ANSWERS = ("same", "different")


class AnswerRefused(ValueError):
    """The answer is not usable; nothing was written."""


async def _own_jobs(db: AsyncSession, org_id: str, ids: list[str]) -> None:
    found = set((await db.execute(
        select(AnalysisJob.id).where(
            AnalysisJob.org_id == org_id, AnalysisJob.id.in_(set(ids)), AnalysisJob.status == JobStatus.COMPLETED
        )
    )).scalars().all())
    if missing := sorted(set(ids) - found):
        raise AnswerRefused("bilinmeyen ekstre: " + ", ".join(missing))


async def answer(
    db: AsyncSession, org_id: str, user_id: str, *, answer: str, job_ids_a: list[str], job_ids_b: list[str],
    name_a: str | None = None, name_b: str | None = None, note: str | None = None,
) -> dict[str, Any]:
    """Record the answer for two groups of statements. No commit. Raises `AnswerRefused`."""
    if answer not in ANSWERS:
        raise AnswerRefused("yanıt 'same' ya da 'different' olmalı")
    if not job_ids_a or not job_ids_b or set(job_ids_a) & set(job_ids_b):
        raise AnswerRefused("iki ayrı ekstre grubu gerekli")
    await _own_jobs(db, org_id, [*job_ids_a, *job_ids_b])
    left, right = sorted([sorted(job_ids_a), sorted(job_ids_b)])
    target = f"{left[0]}|{right[0]}"
    standing = None
    rows, _ = await list_decisions(
        db, org_id, kind=DecisionKind.ACCOUNT_IDENTITY.value, current_only=True, limit=500
    )
    for d in rows:
        after = d.after or {}
        a, b = set(after.get("a") or []), set(after.get("b") or [])
        if (a & set(left) and b & set(right)) or (a & set(right) and b & set(left)):
            standing = d
            break
    if standing is not None and standing.outcome == answer and not (name_a or name_b):
        return {"changed": False, "decision_id": standing.id}
    decision = await record_decision(
        db, org_id=org_id, kind=DecisionKind.ACCOUNT_IDENTITY, target_type="statement_pair",
        target_id=standing.target_id if standing is not None else target, outcome=answer,
        decided_via=DecidedVia.HUMAN, decided_by=user_id, reason=note,
        evidence_refs=[{"type": "analysis_job", "id": j} for j in [*left, *right][:40]],
        before={"answer": standing.outcome} if standing is not None else None,
        after={"a": left, "b": right, "name_a": name_a, "name_b": name_b},
        supersedes_id=standing.id if standing is not None else None,
    )
    return {"changed": True, "decision_id": decision.id}
