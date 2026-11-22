"""
Organization model — multi-tenant workspace support.

Every user belongs to one Organization (their workspace).
AnalysisJobs are scoped to an org so members share data.

Roles within an org:
  owner   — full control, can invite/remove members, delete org
  admin   — can invite members, manage jobs
  cfo     — changes working data (writer); does not decide or manage members
  smmm    — the company's accountant: writer, and binds the official record
  analyst — can upload, run analysis, view results; does not change or decide
            a record (category corrections, matches, approvals, month close)
  viewer  — read-only access to completed jobs

The classes the API enforces (contributor / writer / decider / smmm) are in
`app/api/access.py`; the browser's copy is `frontend/src/lib/roles.ts`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.email_address import normalize_email
from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(UTC)


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

    # International locale contract (core OS — not Turkey-only)
    country_code: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="en-US", nullable=False)
    # `base_currency` above is NOT NULL with a default, so a stored value is not a
    # choice. These say whether an owner/admin actually confirmed it. Only a
    # confirmed base currency may stand in for a currency a document did not state.
    base_currency_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    base_currency_confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # e.g. ["tr"] enables Turkey regional pack (SMMM, GIB, Paraşüt, THP)
    regional_packs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # A pilot company sees only the flow it is piloting (plan v10 §O0): the
    # screens outside it are hidden from the menu, not removed.
    focus_mode: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    # True once a person has chosen focus mode themselves (PATCH /org/me). A size
    # profile only sets the default while this is false, and never overwrites it.
    focus_mode_explicit: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    # Company size, as the company says it (services/size_profile.py). Null = not
    # yet determined. Nothing in authorisation, thresholds or money reads these.
    size_profile: Mapped[str | None] = mapped_column(String(10), nullable=True)
    monthly_outflow_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    headcount_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    has_inhouse_finance: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    size_profile_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    size_profile_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    size_profile_set_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Tax identity. Decides an invoice's direction (we sold / we bought) and
    # names the e-Defter's owner; see app/services/org_identity.py.
    vkn: Mapped[str | None] = mapped_column(String(11), nullable=True)
    legal_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Plan / limits
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    max_members: Mapped[int] = mapped_column(default=5, nullable=False)
    max_jobs_per_month: Mapped[int] = mapped_column(default=20, nullable=False)

    # Stripe Billing (STRIPE sprint)
    subscription_plan: Mapped[str] = mapped_column(String(30), default="free", nullable=False)
    subscription_status: Mapped[str] = mapped_column(
        String(30), default="inactive", nullable=False
    )  # inactive | active | past_due | cancelled | trialing
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    subscription_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    members: Mapped[list[User]] = relationship(
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

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return normalize_email(value)

    # SHA-256 digest of the token e-mailed to the invitee (`app.services.secret_tokens`); the token
    # itself is never stored. The column keeps its original name, `token` (migration 071).
    token_hash: Mapped[str] = mapped_column("token", String(64), unique=True, nullable=False, index=True)

    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    organization: Mapped[Organization] = relationship("Organization")


class OrgMembership(Base):
    """A user belongs to an organisation, in a role.

    `users.org_id` is the organisation the user is *acting in*; this table is
    the organisations they may switch to. See `app/services/org_membership.py`.
    """

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_org_membership_user_org"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
