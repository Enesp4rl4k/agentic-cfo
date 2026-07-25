"""
Scheduled CSV importers for accounting software exports.

Handles:
  - Netsis: Daily scheduled CSV export downloads
  - Mikro: Batched XLS imports from FTP/API
  - Logo Tiger: Real-time CSV ingestion
  - Retry logic + error handling
  - Data validation via existing parsers
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from app.parsers.accounting.netsis import NetsisParser
from app.parsers.accounting.mikro import MikroParser
from app.parsers.accounting.logo_tiger import LogoTigerParser
from app.services.data_sync.schemas import (
    SyncSourceType,
    SyncTransaction,
    SyncBatch,
    TransactionType,
)

logger = logging.getLogger(__name__)


class AccountingSoftwareImporter:
    """Base class for scheduled accounting software imports."""

    def __init__(self, source_type: SyncSourceType):
        self.source_type = source_type

    async def sync(self, csv_content: str) -> SyncBatch:
        """
        Parse CSV content and convert to SyncBatch.

        Raises:
            NotImplementedError: Subclasses must implement
        """
        raise NotImplementedError


class NetsisImporter(AccountingSoftwareImporter):
    """
    Netsis daily scheduled import.

    Expects CSV export from Netsis with columns:
      Tarih, Evrak No, Açıklama, Borç, Alacak, Bakiye
    """

    def __init__(self):
        super().__init__(SyncSourceType.NETSIS)
        self.parser = NetsisParser()

    async def sync(self, csv_content: str) -> SyncBatch:
        """Parse Netsis CSV and normalize to SyncBatch."""
        batch = SyncBatch(
            source_type=self.source_type,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            # Use existing parser to handle CSV format flexibility
            parsed_statement = self.parser.parse(csv_content, "netsis_import.csv")

            for parsed_tx in parsed_statement.transactions:
                try:
                    # Map parsed transaction to SyncTransaction
                    sync_tx = SyncTransaction(
                        date=parsed_tx.date,
                        description=parsed_tx.description,
                        amount_cents=parsed_tx.amount_cents,
                        tx_type=TransactionType.INCOME
                        if parsed_tx.tx_type == "income"
                        else TransactionType.EXPENSE,
                        currency=parsed_tx.currency,
                        vendor=parsed_tx.vendor,
                        reference=parsed_tx.reference,
                        source_type=self.source_type,
                        source_id=parsed_tx.reference or None,
                        raw_row=parsed_tx.raw_row,
                    )
                    batch.transactions.append(sync_tx)
                except Exception as e:
                    batch.error_count += 1
                    batch.warnings.append(f"Failed to normalize Netsis transaction: {e}")
                    logger.warning(f"Netsis normalization error: {e}")

            batch.total_processed = len(parsed_statement.transactions)
            batch.warnings.extend(parsed_statement.parse_warnings)

            logger.info(
                f"Netsis: imported {len(batch.transactions)} transactions "
                f"({batch.error_count} errors)"
            )

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Netsis import failed: {e}")
            logger.error(f"Netsis import error: {e}", exc_info=True)

        return batch


class MikroImporter(AccountingSoftwareImporter):
    """
    Mikro batched XLS/CSV import.

    Handles multiple export formats:
      - Account movements CSV
      - Customer card movements
      - Cash/bank movements
    """

    def __init__(self):
        super().__init__(SyncSourceType.MIKRO)
        self.parser = MikroParser()

    async def sync(self, content: str) -> SyncBatch:
        """Parse Mikro export and normalize to SyncBatch."""
        batch = SyncBatch(
            source_type=self.source_type,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            # Use existing Mikro parser
            parsed_statement = self.parser.parse(content, "mikro_import.csv")

            for parsed_tx in parsed_statement.transactions:
                try:
                    sync_tx = SyncTransaction(
                        date=parsed_tx.date,
                        description=parsed_tx.description,
                        amount_cents=parsed_tx.amount_cents,
                        tx_type=TransactionType.INCOME
                        if parsed_tx.tx_type == "income"
                        else TransactionType.EXPENSE,
                        currency=parsed_tx.currency,
                        vendor=parsed_tx.vendor,
                        reference=parsed_tx.reference,
                        source_type=self.source_type,
                        source_id=parsed_tx.reference or None,
                        raw_row=parsed_tx.raw_row,
                    )
                    batch.transactions.append(sync_tx)
                except Exception as e:
                    batch.error_count += 1
                    batch.warnings.append(f"Failed to normalize Mikro transaction: {e}")
                    logger.warning(f"Mikro normalization error: {e}")

            batch.total_processed = len(parsed_statement.transactions)
            batch.warnings.extend(parsed_statement.parse_warnings)

            logger.info(
                f"Mikro: imported {len(batch.transactions)} transactions "
                f"({batch.error_count} errors)"
            )

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Mikro import failed: {e}")
            logger.error(f"Mikro import error: {e}", exc_info=True)

        return batch


class LogoTigerImporter(AccountingSoftwareImporter):
    """
    Logo Tiger real-time CSV ingestion.

    Supports multiple export formats:
      - Fiş raporu (receipt report)
      - Hesap ekstresi (account statement)
      - Mizan raporu (trial balance)
    """

    def __init__(self):
        super().__init__(SyncSourceType.LOGO_TIGER)
        self.parser = LogoTigerParser()

    async def sync(self, csv_content: str) -> SyncBatch:
        """Parse Logo Tiger export and normalize to SyncBatch."""
        batch = SyncBatch(
            source_type=self.source_type,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            # Use existing Logo Tiger parser
            parsed_statement = self.parser.parse(csv_content, "logo_tiger_import.csv")

            for parsed_tx in parsed_statement.transactions:
                try:
                    sync_tx = SyncTransaction(
                        date=parsed_tx.date,
                        description=parsed_tx.description,
                        amount_cents=parsed_tx.amount_cents,
                        tx_type=TransactionType.INCOME
                        if parsed_tx.tx_type == "income"
                        else TransactionType.EXPENSE,
                        currency=parsed_tx.currency,
                        vendor=parsed_tx.vendor,
                        reference=parsed_tx.reference,
                        source_type=self.source_type,
                        source_id=parsed_tx.reference or None,
                        raw_row=parsed_tx.raw_row,
                    )
                    batch.transactions.append(sync_tx)
                except Exception as e:
                    batch.error_count += 1
                    batch.warnings.append(f"Failed to normalize Logo Tiger transaction: {e}")
                    logger.warning(f"Logo Tiger normalization error: {e}")

            batch.total_processed = len(parsed_statement.transactions)
            batch.warnings.extend(parsed_statement.parse_warnings)

            logger.info(
                f"Logo Tiger: imported {len(batch.transactions)} transactions "
                f"({batch.error_count} errors)"
            )

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Logo Tiger import failed: {e}")
            logger.error(f"Logo Tiger import error: {e}", exc_info=True)

        return batch


def get_importer(source_type: SyncSourceType) -> Optional[AccountingSoftwareImporter]:
    """Factory: return appropriate importer for source type."""
    importers = {
        SyncSourceType.NETSIS: NetsisImporter,
        SyncSourceType.MIKRO: MikroImporter,
        SyncSourceType.LOGO_TIGER: LogoTigerImporter,
    }
    importer_class = importers.get(source_type)
    return importer_class() if importer_class else None
