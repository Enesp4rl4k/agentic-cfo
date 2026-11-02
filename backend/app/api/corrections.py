"""
Corrections API — PATCH /transactions/{id}/category

User corrects a transaction's category. We:
1. Update the transaction record
2. Persist a CategoryRule (learn from correction)
3. Return the updated transaction
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.services.classifier import learn

router = APIRouter()

VALID_CATEGORIES = {
    "revenue", "cogs", "salary", "rent", "utilities",
    "marketing", "technology", "tax", "loan",
    "other_expense", "other_income", "tax_payment", "transfer",
}


class CategoryCorrectionRequest(BaseModel):
    category: str
    apply_always: bool = False   # "Apply this rule for all future transactions from this vendor"


@router.patch("/transactions/{transaction_id}/category")
async def correct_category(
    transaction_id: str,
    body: CategoryCorrectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Correct a transaction's category and optionally save a rule
    so future transactions from the same vendor are auto-categorized.
    """
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{body.category}'. Valid: {sorted(VALID_CATEGORIES)}",
        )

    tx = await db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    job = await load_owned_job(db, tx.job_id, current_user)

    old_category = tx.category
    tx.category = body.category
    tx.category_source = "user_edit"
    await db.commit()

    org_id = str(job.org_id) if job.org_id else None
    # Persist learning rule
    rule = await learn(
        description=tx.description or "",
        vendor=tx.vendor,
        new_category=body.category,
        apply_always=body.apply_always,
        db=db,
        # The rule belongs to the company whose transaction was corrected.
        org_id=org_id,
    )

    # A standing rule changes every analysis it matches, but their dashboards
    # were derived from the old categories. Say which ones, so the UI can offer
    # to recompute them (POST /analysis/{id}/rerun) — rows are not patched in
    # place, because a derived view patched by hand drifts from its source.
    affected: list[str] = []
    if body.apply_always and org_id:
        found = set(await _jobs_matching_rule(db, org_id, rule))
        # This job's dashboard predates the correction too; a rerun re-applies
        # the rule to the row just edited.
        if job.status in ("completed", "failed"):
            found.add(str(job.id))
        affected = sorted(found)

    return {
        "data": {
            "transaction_id": transaction_id,
            "old_category": old_category,
            "new_category": body.category,
            "rule_saved": body.apply_always,
            "affected_job_ids": affected,
        },
        "error": None,
    }


async def _jobs_matching_rule(db: AsyncSession, org_id: str, rule: Any) -> list[str]:
    """Completed/failed jobs of the org with a row the rule would recategorise."""
    from sqlalchemy import select

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.services.classifier import RuleSpec, match_rule

    spec = [RuleSpec(
        id=str(rule.id), category=rule.category,
        vendor=rule.vendor_match or None, keyword=rule.keyword_match or None,
    )]
    rows = (
        await db.execute(
            select(Transaction.job_id, Transaction.vendor, Transaction.description)
            .join(AnalysisJob, AnalysisJob.id == Transaction.job_id)
            .where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.status.in_([JobStatus.COMPLETED.value, JobStatus.FAILED.value]),
                Transaction.category != rule.category,
            )
        )
    ).all()
    jobs = {
        job_id for job_id, vendor, desc in rows
        if match_rule(spec, vendor=vendor, description=desc)
    }
    return sorted(jobs)


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single transaction by ID."""
    tx = await db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    await load_owned_job(db, tx.job_id, current_user)
    return {
        "data": {
            "id": tx.id,
            "job_id": tx.job_id,
            "amount_cents": tx.amount_kurus,
            "currency": tx.currency,
            "type": tx.type,
            "category": tx.category,
            "description": tx.description,
            "vendor": tx.vendor,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
            "confidence": float(tx.confidence) if tx.confidence else None,
        },
        "error": None,
    }
