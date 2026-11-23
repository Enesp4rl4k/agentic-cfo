"""Records of the data-lifecycle features: exports, notice acceptances, retention runs.

* `DataExport`   one company-wide export bundle: who asked, its state, where the file is, when the download window
                 closes. The file is deleted at `expires_at`; the row (without the path) stays as the record.
* `TermsAcceptance` which version of which notice a person accepted, and when (consent evidence; a user id, no text).
* `RetentionRun` one run of the retention job: counts only, never a row's content.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class DataExport(Base):
    __tablename__ = "data_exports"
    __table_args__ = (Index("ix_data_exports_org_status", "org_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    # queued -> running -> ready | failed ; ready -> expired
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # per dataset: {"rows": n, "truncated": bool}; counts only
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # A fixed code, never an exception text: "build_failed"
    error_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TermsAcceptance(Base):
    __tablename__ = "terms_acceptances"
    __table_args__ = (Index("ix_terms_acceptances_user_document", "user_id", "document"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document: Mapped[str] = mapped_column(String(20), nullable=False)  # privacy_notice | terms
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="in_app")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RetentionRun(Base):
    __tablename__ = "retention_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # "all" (the scheduled run over every active company) or an organisation hash: never a raw id
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="all")
    organisations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)  # numbers of days
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)  # action -> rows
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="running")  # running | done | failed
