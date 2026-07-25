"""
Pilot program models — PilotInvite and UserFeedback.

PilotInvite: pre-generated invite codes that gate registration.
UserFeedback: post-analysis NPS + rating + open comment.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Integer, Text, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PilotInvite(Base):
    """
    Pre-generated invite code for pilot program.
    Admin generates these and shares with potential pilot users.
    """
    __tablename__ = "pilot_invites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # optional: pre-assign to email
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)   # admin note (e.g. company name)

    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class UserFeedback(Base):
    """
    Post-analysis feedback from pilot users.
    Collected after each analysis job completes.
    """
    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # NPS: 0–10 (how likely to recommend)
    nps_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Analysis quality rating: 1–5 stars
    analysis_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Specific aspect ratings (1–5)
    accuracy_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usefulness_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Open-ended
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    biggest_benefit: Mapped[str | None] = mapped_column(Text, nullable=True)  # "What helped you most?"
    biggest_gap: Mapped[str | None] = mapped_column(Text, nullable=True)       # "What's missing?"

    # Context
    page_context: Mapped[str | None] = mapped_column(String(100), nullable=True)  # which page triggered feedback
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
