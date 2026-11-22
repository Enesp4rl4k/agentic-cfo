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
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.email_address import normalize_email
from app.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UserRole(StrEnum):
    OWNER    = "owner"
    ADMIN    = "admin"
    CFO      = "cfo"
    ANALYST  = "analyst"
    VIEWER   = "viewer"
    # An accountant (mali müşavir) acting in a client's organisation. Gets no
    # owner/admin/cfo privileges there: billing and member management stay
    # with the client.
    SMMM = "smmm"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return normalize_email(value)

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
    organization: Mapped[Organization | None] = relationship(
        "Organization", back_populates="members", foreign_keys=[org_id]
    )

    # API key for programmatic access (optional)
    api_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    # SSO / OAuth2 fields (SEC-1)
    sso_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)   # "microsoft"|"google"|"github"
    sso_id:       Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # provider user ID
    last_login:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Raised when the password changes. Every token carries the version it was issued under
    # (`tv`); a token of an older version is refused, so a reset ends all earlier sessions.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # When the holder of this address proved it (a verification link, an invitation e-mailed to it, or
    # a sign-in provider that verified it). NULL: nobody has, and the account cannot sign in or act
    # while `email_verification_required` is on.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# One account per mailbox whatever the spelling: a backstop under `normalize_email`
# (migration 069). A functional index, so it holds on Postgres and SQLite alike.
Index("uq_users_email_lower", func.lower(User.email), unique=True)
