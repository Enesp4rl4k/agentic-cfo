import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob


def utcnow() -> datetime:
    return datetime.now(UTC)


class TransactionCategory(StrEnum):
    REVENUE = "revenue"
    COGS = "cogs"
    SALARY = "salary"
    RENT = "rent"
    UTILITIES = "utilities"
    MARKETING = "marketing"
    TECHNOLOGY = "technology"
    TAX = "tax"
    LOAN = "loan"
    OTHER_EXPENSE = "other_expense"
    OTHER_INCOME = "other_income"


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id"), nullable=False, index=True
    )
    # All amounts stored in kuruş (smallest unit) as integer
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="TRY", nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # income | expense
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # True when `transaction_date` was invented because the source had no
    # readable date. The column cannot be null and the row has to exist to be
    # reviewed, so the estimate is made — but it says so, because the date
    # decides the accounting period and the period reaches a legal filing.
    date_is_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    job: Mapped["AnalysisJob"] = relationship("AnalysisJob", back_populates="transactions")
