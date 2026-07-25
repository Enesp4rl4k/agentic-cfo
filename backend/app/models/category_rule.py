"""
CategoryRule — user-defined classification rules.

When a user corrects a transaction's category, we store a rule so future
transactions from the same vendor/keyword are auto-categorized correctly.
This is the feedback loop that makes the classifier smarter over time.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Matching criteria — at least one must be set
    # Exact vendor match (case-insensitive)
    vendor_match: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    # Keyword in description (case-insensitive substring match)
    keyword_match: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)

    # Result
    category: Mapped[str] = mapped_column(String(40), nullable=False)

    # "Apply to all future transactions from this vendor" toggle
    apply_always: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # How many times this rule has been applied (for ranking)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
