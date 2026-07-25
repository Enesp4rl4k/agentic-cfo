"""
Organization model — multi-tenant workspace support.

Every user belongs to one Organization (their workspace).
AnalysisJobs are scoped to an org so members share data.

Roles within an org:
  owner   — full control, can invite/remove members, delete org
  admin   — can invite members, manage jobs
  analyst — can upload, run analysis, view results
  viewer  — read-only access to completed jobs
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    # Branding / settings
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Plan / limits
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    max_members: Mapped[int] = mapped_column(default=5, nullable=False)
    max_jobs_per_month: Mapped[int] = mapped_column(default=20, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    members: Mapped[list["User"]] = relationship(
        "User", back_populates="organization", foreign_keys="User.org_id"
    )


class OrgInvite(Base):
    """Pending invitation to join an organization."""
    __tablename__ = "org_invites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="analyst", nullable=False)

    # Secure token sent by email
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization")
