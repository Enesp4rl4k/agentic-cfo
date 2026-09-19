"""SOX certification and GDPR breach-notification records.

These two tables existed only in migration 017 and were reached with raw SQL,
which broke twice over: CLAUDE.md law 4 forbids raw SQL, and because no model
declared them, `create_all` never created them on SQLite — so every route in
`app/api/compliance_extended.py` answered 500 in dev with
"no such table: breach_notifications".

Columns mirror migration 017 exactly; no schema change, so no new migration is
needed for existing PostgreSQL deployments.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ComplianceCertification(Base):
    """One signed SOX/GDPR certification for an org and period."""

    __tablename__ = "compliance_certifications"
    __table_args__ = (
        Index("ix_compliance_certifications_org", "org_id", "framework"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    framework: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    certifier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    certifier_role: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSON array of booleans, stored as text to match migration 017.
    statements: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    certified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "framework": self.framework,
            "period": self.period,
            "certifier_name": self.certifier_name,
            "certifier_role": self.certifier_role,
            "signature_hash": self.signature_hash,
            "certified_at": self.certified_at.isoformat() if self.certified_at else None,
        }


class BreachNotification(Base):
    """A personal-data breach and its 72-hour KVKK/GDPR notification deadline."""

    __tablename__ = "breach_notifications"
    __table_args__ = (
        Index("ix_breach_notifications_org_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    affected_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_72h: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "severity": self.severity,
            "affected_users": self.affected_users,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "deadline_72h": self.deadline_72h.isoformat() if self.deadline_72h else None,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "status": self.status,
        }
