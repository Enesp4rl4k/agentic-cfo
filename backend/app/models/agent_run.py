"""AgentRun ORM — one durable record per agent-pipeline execution.

Faz 14 (Durable Runs). `AnalysisJob` tracks the CFO analysis specifically;
`SyncRun` tracks connector pulls. `AgentRun` is the generic ledger every
long-running pipeline (cfo / ceo / tr_vertical / cto / …) writes, so a run can be
observed, audited, and resumed from its last node.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    pipeline: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # cfo | ceo | tr_vertical | cto | chro | ...
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    # running | completed | failed | halted | awaiting_review
    current_node: Mapped[str | None] = mapped_column(String(60), nullable=True)
    node_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
