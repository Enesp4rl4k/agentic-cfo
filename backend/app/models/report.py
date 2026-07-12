import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportType(str):
    PNL = "pnl"
    CASHFLOW = "cashflow"
    FORECAST = "forecast"
    FULL = "full"


class ReportFormat(str):
    EXCEL = "xlsx"
    PDF = "pdf"
    JSON = "json"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("analysis_jobs.id"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)   # pnl | cashflow | forecast | full
    report_format: Mapped[str] = mapped_column(String(10), nullable=False) # xlsx | pdf | json

    # File path on disk (local storage) or S3 key
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # JSON payload — used for dashboard API responses and json-format reports
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    job: Mapped["AnalysisJob"] = relationship("AnalysisJob", back_populates="reports")
