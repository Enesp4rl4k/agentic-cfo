"""
Pilot program models — PilotInvite and UserFeedback.

PilotInvite: an invitation, issued by a platform operator to one e-mail address, that lets that person
register and become the owner of a new company (`company_name`). The secret token is e-mailed to the
address and kept only as a SHA-256 digest (`token_hash`); `code` is a non-secret reference for the list.
UserFeedback: post-analysis NPS + rating + open comment.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.email_address import normalize_email
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    @validates("email")
    def _normalise_email(self, _key: str, value: str | None) -> str | None:
        return normalize_email(value) if value else value

    note: Mapped[str | None] = mapped_column(String(500), nullable=True)   # admin note
    # The company the invited person will own, and the digest of the e-mailed token (NULL: an invite
    # from before tokens were hashed; it can no longer be redeemed). `issued_by` is the operator's user id.
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    issued_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

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
