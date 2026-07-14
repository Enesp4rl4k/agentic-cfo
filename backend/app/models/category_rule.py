import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CategoryRule(Base):
    """
    User-defined categorisation rule.
    Created when a user corrects a transaction category (PATCH /transactions/{id}/category).
    The classifier checks these before falling back to built-in keyword heuristics.
    """
    __tablename__ = "category_rules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Vendor name to match (case-insensitive LIKE)
    vendor_match: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # Keyword to match in description (case-insensitive contains)
    keyword_match: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # Target category
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    # If True, applies to ALL future transactions from this vendor, not just once
    apply_always: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Times this rule has been used — used for ordering (most-used first)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
