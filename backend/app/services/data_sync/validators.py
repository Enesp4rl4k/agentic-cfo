"""
Data quality validation engine for ingested transactions.

Detects:
  - Duplicates (same date + amount + vendor)
  - Anomalies (unusual amounts, frequency)
  - Data integrity issues (missing fields, invalid formats)
  - Outliers (statistical anomaly detection)

Flags suspicious data without blocking ingestion (warnings only).
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.data_sync.schemas import (
    SyncBatch,
    SyncTransaction,
    DataQualityThresholds,
)

logger = logging.getLogger(__name__)


class DataQualityValidator:
    """Validates transaction batches against quality thresholds."""

    def __init__(self, thresholds: Optional[DataQualityThresholds] = None):
        """Initialize validator with quality thresholds."""
        self.thresholds = thresholds or DataQualityThresholds()
        self.historical_amounts: dict[str, list[int]] = {}  # vendor -> amounts
        self.recent_transactions: list[SyncTransaction] = []

    def validate_batch(self, batch: SyncBatch) -> SyncBatch:
        """
        Run all quality checks on batch.

        Adds warnings but does not reject transactions.
        Returns updated batch with quality_warnings list.
        """
        warnings = []

        # Check for duplicates within batch
        duplicate_warnings = self._check_duplicates_within_batch(batch.transactions)
        warnings.extend(duplicate_warnings)

        # Check for anomalies
        anomaly_warnings = self._check_anomalies(batch.transactions)
        warnings.extend(anomaly_warnings)

        # Check for outliers
        outlier_warnings = self._check_outliers(batch.transactions)
        warnings.extend(outlier_warnings)

        # Check data integrity
        integrity_warnings = self._check_data_integrity(batch.transactions)
        warnings.extend(integrity_warnings)

        # Update batch with warnings
        batch.warnings.extend(warnings)

        # Update historical data
        self._update_historical_data(batch.transactions)

        if warnings:
            logger.warning(f"Data quality: {len(warnings)} issues found")

        return batch

    def _check_duplicates_within_batch(self, transactions: list[SyncTransaction]) -> list[str]:
        """Check for duplicate transactions within batch."""
        warnings = []
        seen: dict[tuple, int] = {}  # (date, amount, vendor) -> count

        for tx in transactions:
            key = (tx.date.date(), tx.amount_cents, tx.vendor or "")
            count = seen.get(key, 0) + 1
            seen[key] = count

            if count > self.thresholds.max_consecutive_duplicates:
                warnings.append(
                    f"Duplicate detected: {tx.date.date()} {tx.vendor} "
                    f"{tx.amount_cents / 100:.2f} TRY (count: {count})"
                )

        return warnings

    def _check_anomalies(self, transactions: list[SyncTransaction]) -> list[str]:
        """Check for anomalies (unusual frequency, amounts)."""
        warnings = []

        # Check transaction frequency
        if len(transactions) > self.thresholds.max_daily_transactions:
            warnings.append(
                f"Unusually high transaction count: {len(transactions)} "
                f"(max: {self.thresholds.max_daily_transactions})"
            )

        # Check for suspicious amounts (using vendor history)
        for tx in transactions:
            if tx.vendor and tx.vendor in self.historical_amounts:
                historical = self.historical_amounts[tx.vendor]
                if historical:
                    avg = statistics.mean(historical)
                    max_allowed = avg * (self.thresholds.max_amount_increase_percent / 100)

                    if tx.amount_cents > max_allowed:
                        percent_increase = (tx.amount_cents / avg - 1) * 100
                        warnings.append(
                            f"Amount anomaly for {tx.vendor}: {tx.amount_cents / 100:.2f} TRY "
                            f"({percent_increase:.0f}% increase from average)"
                        )

        return warnings

    def _check_outliers(self, transactions: list[SyncTransaction]) -> list[str]:
        """Detect statistical outliers in amounts."""
        warnings = []

        if len(transactions) < 5:
            return warnings  # Need enough data for statistical analysis

        amounts = [t.amount_cents for t in transactions]

        try:
            mean = statistics.mean(amounts)
            stdev = statistics.stdev(amounts)

            if stdev == 0:
                return warnings  # All amounts are identical

            for i, tx in enumerate(transactions):
                z_score = abs((tx.amount_cents - mean) / stdev)

                if z_score > self.thresholds.outlier_stddev_threshold:
                    warnings.append(
                        f"Outlier detected: {tx.vendor or 'unknown'} "
                        f"{tx.amount_cents / 100:.2f} TRY (z-score: {z_score:.2f})"
                    )

        except (statistics.StatisticsError, ZeroDivisionError):
            pass  # Cannot compute stats, skip

        return warnings

    def _check_data_integrity(self, transactions: list[SyncTransaction]) -> list[str]:
        """Check for data integrity issues."""
        warnings = []

        for tx in transactions:
            # Check for empty description
            if not tx.description or len(tx.description.strip()) < 3:
                warnings.append(
                    f"Suspicious description: '{tx.description}' for "
                    f"{tx.date.date()} {tx.amount_cents / 100:.2f} TRY"
                )

            # Check for very old transactions
            if tx.date < datetime.now(timezone.utc) - timedelta(days=365):
                warnings.append(
                    f"Very old transaction: {tx.date.date()} "
                    f"{tx.amount_cents / 100:.2f} TRY"
                )

            # Check for future-dated transactions
            if tx.date > datetime.now(timezone.utc) + timedelta(days=1):
                warnings.append(
                    f"Future-dated transaction: {tx.date.date()} "
                    f"{tx.amount_cents / 100:.2f} TRY"
                )

        return warnings

    def _update_historical_data(self, transactions: list[SyncTransaction]) -> None:
        """Update historical amounts for future anomaly detection."""
        for tx in transactions:
            if tx.vendor:
                if tx.vendor not in self.historical_amounts:
                    self.historical_amounts[tx.vendor] = []

                self.historical_amounts[tx.vendor].append(tx.amount_cents)

                # Keep only last 100 transactions per vendor to prevent memory bloat
                if len(self.historical_amounts[tx.vendor]) > 100:
                    self.historical_amounts[tx.vendor].pop(0)

            self.recent_transactions.append(tx)

        # Keep only last 1000 transactions
        if len(self.recent_transactions) > 1000:
            self.recent_transactions = self.recent_transactions[-1000:]


class DuplicateDetector:
    """Detects duplicate transactions across sources."""

    def __init__(self):
        """Initialize detector."""
        self.seen_transactions: set[str] = set()

    def get_transaction_signature(self, tx: SyncTransaction) -> str:
        """
        Generate unique signature for transaction.

        Signature: date|amount|vendor (ignores source to catch cross-source dupes)
        """
        vendor = tx.vendor or "NONE"
        return f"{tx.date.date().isoformat()}|{tx.amount_cents}|{vendor}"

    def is_duplicate(self, tx: SyncTransaction) -> bool:
        """Check if transaction is duplicate (seen before)."""
        signature = self.get_transaction_signature(tx)
        is_dup = signature in self.seen_transactions
        self.seen_transactions.add(signature)
        return is_dup

    def detect_duplicates_in_batch(self, batch: SyncBatch) -> list[SyncTransaction]:
        """Return list of duplicate transactions in batch."""
        duplicates = []
        for tx in batch.transactions:
            if self.is_duplicate(tx):
                duplicates.append(tx)
        return duplicates

    def reset(self) -> None:
        """Clear duplicate detector cache."""
        self.seen_transactions.clear()


class ConflictResolver:
    """
    Resolves conflicts between sources (API data wins over manual uploads).

    When same transaction exists in multiple sources, picks the one with
    highest confidence:
      1. PSD2 Bank APIs (real-time, authoritative)
      2. Accounting software APIs (semi-real-time, verified)
      3. CSV exports (delayed, may have errors)
    """

    SOURCE_PRIORITY = {
        "garanti": 1,
        "akbank": 1,
        "parasut": 2,
        "netsis": 3,
        "mikro": 3,
        "logo_tiger": 3,
    }

    def resolve_conflicts(
        self,
        transactions: list[SyncTransaction],
    ) -> list[SyncTransaction]:
        """
        Remove lower-priority duplicates, keep highest-priority version.

        Returns filtered list with conflicts resolved.
        """
        groups: dict[str, list[SyncTransaction]] = {}

        # Group by signature
        for tx in transactions:
            sig = self._get_conflict_signature(tx)
            if sig not in groups:
                groups[sig] = []
            groups[sig].append(tx)

        resolved = []

        for sig, txs in groups.items():
            if len(txs) == 1:
                resolved.append(txs[0])
            else:
                # Multiple versions of same transaction — keep highest priority.
                # Lower SOURCE_PRIORITY number = higher trust (1 = bank API, 3 = CSV).
                winner = min(
                    txs,
                    key=lambda t: self.SOURCE_PRIORITY.get(
                        t.source_type.value, 999
                    ),
                )
                resolved.append(winner)
                logger.info(
                    f"Conflict: kept {winner.source_type} version of "
                    f"{winner.date.date()} {winner.amount_cents / 100:.2f} TRY"
                )

        return resolved

    @staticmethod
    def _get_conflict_signature(tx: SyncTransaction) -> str:
        """Generate signature for conflict detection (date + amount)."""
        return f"{tx.date.date().isoformat()}|{tx.amount_cents}"
