"""
Pydantic validation schemas for all data sync operations.

Ensures data quality at ingestion time — validates structure, types, ranges.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SyncSourceType(StrEnum):
    """Supported data source types."""
    PARASUT = "parasut"
    NETSIS = "netsis"
    MIKRO = "mikro"
    LOGO_TIGER = "logo_tiger"
    GARANTI = "garanti"
    AKBANK = "akbank"


class TransactionType(StrEnum):
    """Transaction classification."""
    INCOME = "income"
    EXPENSE = "expense"


class SyncTransaction(BaseModel):
    """Normalized transaction from any source."""
    date: datetime
    description: str = Field(..., min_length=1, max_length=500)
    amount_cents: int = Field(..., gt=0)  # Always positive; sign in tx_type
    tx_type: TransactionType
    currency: str = Field(default="TRY", pattern="^[A-Z]{3}$")
    vendor: Optional[str] = Field(None, max_length=200)
    balance_cents: Optional[int] = None
    reference: Optional[str] = Field(None, max_length=100)
    source_type: SyncSourceType
    source_id: Optional[str] = Field(None, max_length=100)  # External transaction ID
    raw_row: str = ""

    class Config:
        json_schema_extra = {
            "example": {
                "date": "2026-01-15T10:30:00Z",
                "description": "Müşteri A - Hizmet Faturalandırması",
                "amount_cents": 150000,
                "tx_type": "income",
                "currency": "TRY",
                "vendor": "Müşteri A",
                "source_type": "parasut",
                "source_id": "TXN-12345",
            }
        }

    @field_validator("amount_cents")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        """Reject suspiciously large amounts (> 1 billion TRY)."""
        if v > 100_000_000_000:  # 1B TRY in cents
            raise ValueError("Amount exceeds maximum threshold")
        return v


class SyncBatch(BaseModel):
    """Batch of transactions from a single sync operation."""
    source_type: SyncSourceType
    sync_timestamp: datetime
    transactions: list[SyncTransaction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_count: int = 0
    total_processed: int = 0
    batch_id: Optional[str] = None


class SyncStatus(StrEnum):
    """Sync job status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class SyncJobLog(BaseModel):
    """Immutable log entry for each sync operation."""
    source_type: SyncSourceType
    status: SyncStatus
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    transactions_synced: int = 0
    transactions_failed: int = 0
    conflict_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    data_hash: str = ""  # SHA256 of synced data for audit trail


class AccountingSourceConfig(BaseModel):
    """Configuration for accounting software sources."""
    source_type: SyncSourceType
    is_enabled: bool = True
    schedule_cron: str = "0 2 * * *"  # Default: 2 AM daily
    retry_count: int = 3
    timeout_seconds: int = 300
    
    # OAuth2 (Paraşüt)
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_refresh_token: Optional[str] = None
    
    # Scheduled export (Netsis, Mikro, Logo Tiger)
    export_format: Optional[str] = None  # "csv", "xls", "xlsx"
    export_endpoint: Optional[str] = None
    export_credentials: Optional[dict] = None


class BankingSourceConfig(BaseModel):
    """Configuration for Open Banking APIs."""
    source_type: SyncSourceType
    is_enabled: bool = True
    schedule_cron: str = "0 */4 * * *"  # Default: every 4 hours
    retry_count: int = 3
    timeout_seconds: int = 60
    
    # PSD2 credentials
    client_id: str
    client_secret: str
    sandbox_mode: bool = True
    
    # Account selection
    account_ids: Optional[list[str]] = None  # If None, sync all accounts


class DataQualityThresholds(BaseModel):
    """Thresholds for data quality checks."""
    max_consecutive_duplicates: int = 3
    max_amount_increase_percent: int = 500  # Flag if amount > 5x previous avg
    min_transaction_interval_minutes: int = 1
    max_daily_transactions: int = 10000
    outlier_stddev_threshold: float = 3.0
