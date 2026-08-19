"""
CompanyContextSnapshot — DB persistence for CompanyContext.

One row per organization; upserted on every agent completion.

Storage:
  - PostgreSQL (prod): context_json stored as JSONB for indexed key-path
    queries and binary compression. Migration 013_company_context_jsonb
    converts the column type automatically.
  - SQLite (dev): Text column — JSONB not available; application-level
    payload trimming in company_context.py handles size.

Adding new fields to CompanyContext requires no schema migration —
just update the dataclass in services/company_context.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _jsonb_or_text():
    """
    Return JSONB on PostgreSQL, Text on SQLite.
    Evaluated at import time — safe for create_all in SQLite dev mode.
    """
    try:
        from app.config import get_settings
        s = get_settings()
        if not s.use_sqlite:
            from sqlalchemy.dialects.postgresql import JSONB
            return JSONB(astext_type=Text())
    except Exception:
        pass
    return Text()


class CompanyContextSnapshot(Base):
    __tablename__ = "company_context_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    # Full CompanyContext dataclass serialized as JSON.
    # Column type: JSONB on PostgreSQL (via migration 013), Text on SQLite.
    # Application-level payload trimming is applied before writes (see
    # services/company_context.py::save_company_context).
    context_json: Mapped[str] = mapped_column(
        _jsonb_or_text(), nullable=False, default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
