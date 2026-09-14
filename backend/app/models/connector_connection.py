"""ConnectorConnection ORM — a tenant's link to one external data source.

Faz 13 (Connector Platform). Distinct from `ERPIntegration` (accounting/banking,
transaction-centric): this row backs the generic `Connector` protocol for
engineering / HR / marketing / ops sources. One row per (org_id, connector).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConnectorConnection(Base):
    __tablename__ = "connector_connections"
    __table_args__ = (
        UniqueConstraint("org_id", "connector", name="uq_connector_conn_org_connector"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    connector: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # "github"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending | active | error | disconnected
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # Non-secret config as JSON text (e.g. {"owner": "acme", "repo": "api"}).
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Secret blob, Fernet-encrypted JSON (e.g. {"token": "ghp_..."}).
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Incremental sync state — opaque cursor + universal `since` fallback.
    watermark_cursor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    watermark_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_record_count: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
