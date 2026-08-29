"""ORM model for agent_conflicts (migration 016)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _json_col():
    try:
        from app.config import get_settings

        if not get_settings().use_sqlite:
            from sqlalchemy.dialects.postgresql import JSONB

            return JSONB(astext_type=Text())
    except Exception:
        pass
    return Text()


class AgentConflict(Base):
    __tablename__ = "agent_conflicts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_a: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_b: Mapped[str] = mapped_column(String(50), nullable=False)
    claim_a: Mapped[str | None] = mapped_column(_json_col(), nullable=True)
    claim_b: Mapped[str | None] = mapped_column(_json_col(), nullable=True)
    consensus_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution: Mapped[str | None] = mapped_column(_json_col(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
