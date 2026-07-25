"""
AuditLog model — immutable record of every data mutation.

Every POST/PATCH/DELETE request creates an AuditLog entry.
Entries are never deleted (compliance requirement).

Fields:
  - user_id:     Who did it (None = unauthenticated/system)
  - action:      HTTP method + path (e.g. "POST /api/v1/upload")
  - resource:    Resource path
  - request_body: Sanitized request body (secrets stripped)
  - response_status: HTTP status code
  - ip_address:  Client IP
  - duration_ms: Request duration
  - reason:      Optional X-Audit-Reason header value
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Who
    user_id:   Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_role:  Mapped[str | None] = mapped_column(String(20), nullable=True)

    # What
    action:          Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    resource:        Mapped[str] = mapped_column(String(500), nullable=False)
    request_body:    Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Context
    ip_address:  Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent:  Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason:      Mapped[str | None] = mapped_column(Text, nullable=True)

    # When
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
