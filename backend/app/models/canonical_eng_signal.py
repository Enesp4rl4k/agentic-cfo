"""CanonicalEngSignal ORM — source-agnostic engineering activity record.

Faz 13 (Connector Platform). The engineering-domain sibling of
`CanonicalTransaction`: connectors (GitHub, later Jira/Linear/CI) normalise their
records into this shape so the CTO view can read one contract instead of
provider-specific payloads.

`signal_type` discriminates the row; `magnitude` holds the one number that
matters per type (commit → additions+deletions, pull_request → cycle-time hours,
issue/incident → comment count) and `attributes` carries the long tail.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CanonicalEngSignal(Base):
    __tablename__ = "canonical_eng_signals"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source", "source_record_id",
            name="uq_canonical_eng_org_source_record",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # "github"
    source_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    sync_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    signal_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # commit | pull_request | issue | incident | deploy
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    magnitude: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
