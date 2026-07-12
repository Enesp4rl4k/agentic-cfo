"""
Corrections API — PATCH /transactions/{id}/category

User corrects a transaction's category. We:
1. Update the transaction record
2. Persist a CategoryRule (learn from correction)
3. Return the updated transaction
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.transaction import Transaction
from app.services.classifier import learn

router = APIRouter()

VALID_CATEGORIES = {
    "revenue", "cogs", "salary", "rent", "utilities",
    "marketing", "technology", "tax", "loan",
    "other_expense", "other_income",
}


class CategoryCorrectionRequest(BaseModel):
    category: str
    apply_always: bool = False   # "Apply this rule for all future transactions from this vendor"


@router.patch("/transactions/{transaction_id}/category")
async def correct_category(
    transaction_id: str,
    body: CategoryCorrectionRequest,
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

    old_category = tx.category
    tx.category = body.category
    await db.commit()

    # Persist learning rule
    await learn(
        description=tx.description or "",
        vendor=tx.vendor,
        new_category=body.category,
        apply_always=body.apply_always,
        db=db,
    )

    return {
        "data": {
            "transaction_id": transaction_id,
            "old_category": old_category,
            "new_category": body.category,
            "rule_saved": body.apply_always,
        },
        "error": None,
    }


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single transaction by ID."""
    tx = await db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
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
