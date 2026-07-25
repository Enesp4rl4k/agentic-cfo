"""
User model — authentication and authorization.

Supports:
  - Email/password login (bcrypt hashed)
  - Role-based access: owner | admin | cfo | analyst | viewer
  - API key authentication (for programmatic access)
  - Multi-tenant: each user belongs to one Organization
  - Soft delete (deactivate instead of delete)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(StrEnum):
    OWNER    = "owner"
    ADMIN    = "admin"
    CFO      = "cfo"
    ANALYST  = "analyst"
    VIEWER   = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.ANALYST, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Multi-tenant: organization membership (nullable for super-admins / first setup)
    org_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    organization: Mapped["Organization | None"] = relationship(
        "Organization", back_populates="members", foreign_keys=[org_id]
    )

    # API key for programmatic access (optional)
    api_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    # Metadata
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
