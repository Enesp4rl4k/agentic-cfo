"""LLMCallLog — one row per LLM egress call through the Model Gateway.

Every call that leaves the process for a language model is recorded here:
which org / job triggered it, which model answered, token counts, computed
USD cost, latency, and whether it succeeded.  This is the ledger behind the
per-org cost endpoint and the audit trail for agent reasoning spend.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Who / what triggered the call (both nullable — not every call is org-scoped)
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    task_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
