"""
Main orchestrator for multi-source data sync pipeline.

Coordinates:
  - Phase 1: Accounting software syncs (Paraşüt, Netsis, Mikro, Logo Tiger)
  - Phase 2: Banking APIs (Garanti, Akbank)
  - Phase 3: Data quality validation + conflict resolution + audit logging

Entry point: sync_all_sources() → runs all enabled sources in parallel.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.data_sync.schemas import (
    SyncSourceType,
    SyncBatch,
    SyncStatus,
    AccountingSourceConfig,
    BankingSourceConfig,
)
from app.services.data_sync.accounting.parasut import ParasutClient
from app.services.data_sync.accounting.importers import get_importer
from app.services.data_sync.banking.psd2 import GarantiPSD2Client, AkbankPSD2Client
from app.services.data_sync.validators import (
    DataQualityValidator,
    DuplicateDetector,
    ConflictResolver,
)
from app.services.data_sync.audit import AuditTrail

logger = logging.getLogger(__name__)


class DataSyncOrchestrator:
    """
    Orchestrates multi-source data sync with quality checks and conflict resolution.

    Workflow:
      1. Fetch data from all sources in parallel (accounting + banking)
      2. Normalize to SyncTransaction format
      3. Run data quality validators
      4. Detect duplicates across sources
      5. Resolve conflicts (API data wins)
      6. Persist transactions to database
      7. Log audit trail with integrity hash
    """

    def __init__(self):
        """Initialize orchestrator."""
        self.duplicate_detector = DuplicateDetector()
        self.conflict_resolver = ConflictResolver()
        self.quality_validator = DataQualityValidator()
        self.audit_trail = AuditTrail()

    async def sync_parasut(
        self,
        config: AccountingSourceConfig,
        date_range_days: int = 90,
    ) -> SyncBatch:
        """Sync transactions from Paraşüt API."""
        if not config.is_enabled:
            logger.info("Paraşüt sync disabled")
            return SyncBatch(source_type=SyncSourceType.PARASUT)

        try:
            if not (config.oauth_client_id and config.oauth_client_secret):
                logger.error("Paraşüt: missing OAuth credentials")
                batch = SyncBatch(source_type=SyncSourceType.PARASUT)
                batch.warnings.append("Missing OAuth credentials")
                return batch

            # TODO: get company_id from config or database
            company_id = "123456"  # Placeholder

            client = ParasutClient(
                client_id=config.oauth_client_id,
                client_secret=config.oauth_client_secret,
                refresh_token=config.oauth_refresh_token or "",
                company_id=company_id,
            )

            date_to = datetime.now(timezone.utc)
            date_from = date_to - timedelta(days=date_range_days)

            # Fetch transactions and invoices
            tx_batch = await client.sync_transactions(date_from, date_to)
            inv_batch = await client.sync_invoices(date_from, date_to)

            # Merge batches
            merged = SyncBatch(
                source_type=SyncSourceType.PARASUT,
                sync_timestamp=datetime.now(timezone.utc),
                transactions=tx_batch.transactions + inv_batch.transactions,
                warnings=tx_batch.warnings + inv_batch.warnings,
                error_count=tx_batch.error_count + inv_batch.error_count,
                total_processed=tx_batch.total_processed + inv_batch.total_processed,
            )

            return merged

        except Exception as e:
            logger.error(f"Paraşüt sync failed: {e}", exc_info=True)
            batch = SyncBatch(source_type=SyncSourceType.PARASUT)
            batch.warnings.append(f"Paraşüt sync exception: {e}")
            return batch

    async def sync_accounting_csv(
        self,
        source_type: SyncSourceType,
        csv_content: str,
    ) -> SyncBatch:
        """Sync transactions from accounting software CSV export."""
        try:
            importer = get_importer(source_type)
            if not importer:
                batch = SyncBatch(source_type=source_type)
                batch.warnings.append(f"No importer for {source_type}")
                return batch

            batch = await importer.sync(csv_content)
            return batch

        except Exception as e:
            logger.error(f"{source_type} import failed: {e}", exc_info=True)
            batch = SyncBatch(source_type=source_type)
            batch.warnings.append(f"{source_type} import exception: {e}")
            return batch

    async def sync_garanti(
        self,
        config: BankingSourceConfig,
        date_range_days: int = 90,
    ) -> SyncBatch:
        """Sync transactions from Garanti PSD2 API."""
        if not config.is_enabled:
            logger.info("Garanti sync disabled")
            return SyncBatch(source_type=SyncSourceType.GARANTI)

        try:
            client = GarantiPSD2Client(
                client_id=config.client_id,
                client_secret=config.client_secret,
                sandbox_mode=config.sandbox_mode,
            )

            # Fetch accounts
            accounts = await client.fetch_accounts()
            if not accounts:
                batch = SyncBatch(source_type=SyncSourceType.GARANTI)
                batch.warnings.append("No accounts found")
                return batch

            # Filter by account_ids if specified
            if config.account_ids:
                account_ids = {
                    a.get("id")
                    for a in accounts
                    if a.get("id") in config.account_ids
                }
            else:
                account_ids = {a.get("id") for a in accounts if a.get("id")}

            # Fetch transactions for each account
            date_to = datetime.now(timezone.utc)
            date_from = date_to - timedelta(days=date_range_days)

            all_transactions = []
            all_warnings = []
            total_errors = 0

            for account_id in account_ids:
                batch = await client.fetch_transactions(
                    account_id, date_from, date_to
                )
                all_transactions.extend(batch.transactions)
                all_warnings.extend(batch.warnings)
                total_errors += batch.error_count

            merged = SyncBatch(
                source_type=SyncSourceType.GARANTI,
                sync_timestamp=datetime.now(timezone.utc),
                transactions=all_transactions,
                warnings=all_warnings,
                error_count=total_errors,
                total_processed=len(all_transactions),
            )

            return merged

        except Exception as e:
            logger.error(f"Garanti sync failed: {e}", exc_info=True)
            batch = SyncBatch(source_type=SyncSourceType.GARANTI)
            batch.warnings.append(f"Garanti sync exception: {e}")
            return batch

    async def sync_akbank(
        self,
        config: BankingSourceConfig,
        date_range_days: int = 90,
    ) -> SyncBatch:
        """Sync transactions from Akbank PSD2 API."""
        if not config.is_enabled:
            logger.info("Akbank sync disabled")
            return SyncBatch(source_type=SyncSourceType.AKBANK)

        try:
            client = AkbankPSD2Client(
                client_id=config.client_id,
                client_secret=config.client_secret,
                sandbox_mode=config.sandbox_mode,
            )

            # Fetch accounts
            accounts = await client.fetch_accounts()
            if not accounts:
                batch = SyncBatch(source_type=SyncSourceType.AKBANK)
                batch.warnings.append("No accounts found")
                return batch

            # Filter by account_ids if specified
            if config.account_ids:
                account_ids = {
                    a.get("id")
                    for a in accounts
                    if a.get("id") in config.account_ids
                }
            else:
                account_ids = {a.get("id") for a in accounts if a.get("id")}

            # Fetch transactions for each account
            date_to = datetime.now(timezone.utc)
            date_from = date_to - timedelta(days=date_range_days)

            all_transactions = []
            all_warnings = []
            total_errors = 0

            for account_id in account_ids:
                batch = await client.fetch_transactions(
                    account_id, date_from, date_to
                )
                all_transactions.extend(batch.transactions)
                all_warnings.extend(batch.warnings)
                total_errors += batch.error_count

            merged = SyncBatch(
                source_type=SyncSourceType.AKBANK,
                sync_timestamp=datetime.now(timezone.utc),
                transactions=all_transactions,
                warnings=all_warnings,
                error_count=total_errors,
                total_processed=len(all_transactions),
            )

            return merged

        except Exception as e:
            logger.error(f"Akbank sync failed: {e}", exc_info=True)
            batch = SyncBatch(source_type=SyncSourceType.AKBANK)
            batch.warnings.append(f"Akbank sync exception: {e}")
            return batch

    async def process_batches(
        self,
        batches: list[SyncBatch],
    ) -> list[SyncBatch]:
        """
        Process all batches through quality checks and conflict resolution.

        Steps:
          1. Validate each batch
          2. Detect duplicates
          3. Resolve conflicts (API data wins)
          4. Return processed batches
        """
        processed = []

        for batch in batches:
            # Run data quality checks
            batch = self.quality_validator.validate_batch(batch)

            # Detect duplicates within batch
            duplicates = self.duplicate_detector.detect_duplicates_in_batch(batch)
            if duplicates:
                batch.warnings.append(
                    f"Detected {len(duplicates)} duplicates within batch"
                )

            processed.append(batch)

        # Resolve conflicts across all batches
        all_transactions = []
        for batch in processed:
            all_transactions.extend(batch.transactions)

        resolved = self.conflict_resolver.resolve_conflicts(all_transactions)

        # Reconstruct batches after conflict resolution
        # (Group by source for audit purposes)
        result_batches = {}
        for tx in resolved:
            source = tx.source_type
            if source not in result_batches:
                result_batches[source] = SyncBatch(
                    source_type=source,
                    sync_timestamp=datetime.now(timezone.utc),
                )
            result_batches[source].transactions.append(tx)

        return list(result_batches.values())

    def get_batch_summary(self, batch: SyncBatch) -> dict:
        """Get summary stats for batch."""
        return {
            "source": batch.source_type.value,
            "transactions": len(batch.transactions),
            "errors": batch.error_count,
            "warnings": len(batch.warnings),
            "data_hash": self.audit_trail.compute_batch_hash(batch),
        }
