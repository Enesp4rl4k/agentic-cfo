"""
Integration tests for multi-source data sync pipeline.

Tests:
  - Accounting software parsers (Paraşüt, Netsis, Mikro, Logo Tiger)
  - Banking PSD2 clients (Garanti, Akbank)
  - Data validators (quality checks, duplicates, conflicts)
  - Orchestrator (full pipeline)
  - Audit trail logging
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.data_sync.schemas import (
    SyncSourceType,
    SyncTransaction,
    SyncBatch,
    TransactionType,
    DataQualityThresholds,
)
from app.services.data_sync.accounting.parasut import ParasutClient
from app.services.data_sync.accounting.importers import (
    NetsisImporter,
    MikroImporter,
    LogoTigerImporter,
)
from app.services.data_sync.banking.psd2 import GarantiPSD2Client, AkbankPSD2Client
from app.services.data_sync.validators import (
    DataQualityValidator,
    DuplicateDetector,
    ConflictResolver,
)
from app.services.data_sync.orchestrator import DataSyncOrchestrator


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_transaction():
    """Create sample transaction."""
    return SyncTransaction(
        date=datetime.now(timezone.utc),
        description="Test Transaction",
        amount_cents=100000,
        tx_type=TransactionType.INCOME,
        currency="TRY",
        vendor="Test Vendor",
        source_type=SyncSourceType.PARASUT,
        source_id="TX-123",
    )


@pytest.fixture
def sample_batch():
    """Create sample batch."""
    return SyncBatch(
        source_type=SyncSourceType.PARASUT,
        sync_timestamp=datetime.now(timezone.utc),
        transactions=[],
    )


@pytest.fixture
def parasut_csv_sample():
    """Sample Paraşüt CSV export."""
    return """Paraşüt İşlem Raporu
Tarih,Tip,Kategori,Açıklama,Tutar,Döviz,Hesap
2026-01-15,Gelir,Müşteri,Proje A Faturalandırması,5000.00,TRY,Banka
2026-01-16,Gider,Masraf,Ofis Malzemeleri,-2500.00,TRY,Kasa
"""


@pytest.fixture
def netsis_csv_sample():
    """Sample Netsis CSV export."""
    return """NETSİS Hesap Hareketleri
Tarih;Evrak No;Açıklama;Borç;Alacak;Bakiye
15.01.2026;F001;Satış Faturası;;5000;100000
16.01.2026;G001;Masraf Ödemesi;2500;;97500
"""


@pytest.fixture
def mikro_csv_sample():
    """Sample Mikro CSV export."""
    return """MİKRO Hesap Hareketleri
Tarih,Evrak No,Açıklama,Giriş,Çıkış,Bakiye
15.01.2026,T001,Müşteri Tahsilatı,5000,0,100000
16.01.2026,G001,Tedarikçi Ödemesi,0,2500,97500
"""


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Accounting Software Importers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_netsis_importer_parses_csv(netsis_csv_sample):
    """Test Netsis importer parses CSV correctly."""
    importer = NetsisImporter()
    batch = await importer.sync(netsis_csv_sample)

    assert batch.source_type == SyncSourceType.NETSIS
    assert len(batch.transactions) == 2
    assert batch.transactions[0].tx_type == TransactionType.INCOME
    assert batch.transactions[1].tx_type == TransactionType.EXPENSE
    assert batch.transactions[0].amount_cents == 500000


@pytest.mark.asyncio
async def test_mikro_importer_parses_csv(mikro_csv_sample):
    """Test Mikro importer parses CSV correctly."""
    importer = MikroImporter()
    batch = await importer.sync(mikro_csv_sample)

    assert batch.source_type == SyncSourceType.MIKRO
    assert len(batch.transactions) == 2
    assert batch.transactions[0].tx_type == TransactionType.INCOME
    assert batch.transactions[1].tx_type == TransactionType.EXPENSE


@pytest.mark.asyncio
async def test_logo_tiger_importer_parses_csv():
    """Test Logo Tiger importer parses CSV correctly."""
    csv_content = """LOGO Fiş Listesi
Tarih;Fiş No;Açıklama;Borç;Alacak;Bakiye
15.01.2026;F001;Satış;0;5000;100000
16.01.2026;G001;Gider;2500;0;97500
"""
    importer = LogoTigerImporter()
    batch = await importer.sync(csv_content)

    assert batch.source_type == SyncSourceType.LOGO_TIGER
    assert len(batch.transactions) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Data Validators
# ═══════════════════════════════════════════════════════════════════════════


def test_data_quality_validator_detects_duplicates():
    """Test validator detects duplicate transactions."""
    validator = DataQualityValidator()

    tx1 = SyncTransaction(
        date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        description="Test",
        amount_cents=100000,
        tx_type=TransactionType.INCOME,
        currency="TRY",
        vendor="Vendor A",
        source_type=SyncSourceType.PARASUT,
    )

    tx2 = SyncTransaction(
        date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        description="Test",
        amount_cents=100000,
        tx_type=TransactionType.INCOME,
        currency="TRY",
        vendor="Vendor A",
        source_type=SyncSourceType.PARASUT,
    )

    batch = SyncBatch(
        source_type=SyncSourceType.PARASUT,
        sync_timestamp=datetime.now(timezone.utc),
        transactions=[tx1, tx2, tx2, tx2, tx2],  # tx2 appears 4 times
    )

    validated = validator.validate_batch(batch)
    assert any("Duplicate" in w for w in validated.warnings)


def test_data_quality_validator_detects_anomalies():
    """Test validator detects amount anomalies."""
    validator = DataQualityValidator()

    # Build history
    for i in range(5):
        tx = SyncTransaction(
            date=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            description="Normal",
            amount_cents=100000,  # 1000 TRY
            tx_type=TransactionType.INCOME,
            currency="TRY",
            vendor="Vendor A",
            source_type=SyncSourceType.PARASUT,
        )
        validator._update_historical_data([tx])

    # Anomaly: 10x normal amount
    anomaly_tx = SyncTransaction(
        date=datetime(2026, 1, 10, tzinfo=timezone.utc),
        description="Anomaly",
        amount_cents=1000000,  # 10,000 TRY
        tx_type=TransactionType.INCOME,
        currency="TRY",
        vendor="Vendor A",
        source_type=SyncSourceType.PARASUT,
    )

    batch = SyncBatch(
        source_type=SyncSourceType.PARASUT,
        sync_timestamp=datetime.now(timezone.utc),
        transactions=[anomaly_tx],
    )

    validated = validator.validate_batch(batch)
    assert any("anomaly" in w.lower() for w in validated.warnings)


def test_duplicate_detector_identifies_duplicates():
    """Test duplicate detector identifies same transactions."""
    detector = DuplicateDetector()

    tx = SyncTransaction(
        date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        description="Test",
        amount_cents=100000,
        tx_type=TransactionType.INCOME,
        currency="TRY",
        vendor="Vendor A",
        source_type=SyncSourceType.PARASUT,
    )

    assert not detector.is_duplicate(tx)
    assert detector.is_duplicate(tx)  # Second time = duplicate


def test_conflict_resolver_prioritizes_api_data():
    """Test conflict resolver prioritizes PSD2 API data."""
    resolver = ConflictResolver()

    # Same transaction from different sources
    bank_tx = SyncTransaction(
        date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        description="Transaction",
        amount_cents=100000,
        tx_type=TransactionType.INCOME,
        currency="TRY",
        source_type=SyncSourceType.GARANTI,
        source_id="BANK-001",
    )

    csv_tx = SyncTransaction(
        date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        description="Transaction",
        amount_cents=100000,
        tx_type=TransactionType.INCOME,
        currency="TRY",
        source_type=SyncSourceType.NETSIS,
        source_id="CSV-001",
    )

    resolved = resolver.resolve_conflicts([bank_tx, csv_tx])

    assert len(resolved) == 1
    assert resolved[0].source_type == SyncSourceType.GARANTI


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Orchestrator
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_orchestrator_processes_batches():
    """Test orchestrator processes multiple batches."""
    orchestrator = DataSyncOrchestrator()

    batch1 = SyncBatch(
        source_type=SyncSourceType.PARASUT,
        sync_timestamp=datetime.now(timezone.utc),
        transactions=[
            SyncTransaction(
                date=datetime(2026, 1, 15, tzinfo=timezone.utc),
                description="TX1",
                amount_cents=100000,
                tx_type=TransactionType.INCOME,
                currency="TRY",
                source_type=SyncSourceType.PARASUT,
            )
        ],
    )

    batch2 = SyncBatch(
        source_type=SyncSourceType.GARANTI,
        sync_timestamp=datetime.now(timezone.utc),
        transactions=[
            SyncTransaction(
                date=datetime(2026, 1, 16, tzinfo=timezone.utc),
                description="TX2",
                amount_cents=50000,
                tx_type=TransactionType.EXPENSE,
                currency="TRY",
                source_type=SyncSourceType.GARANTI,
            )
        ],
    )

    processed = await orchestrator.process_batches([batch1, batch2])

    assert len(processed) == 2
    assert processed[0].source_type == SyncSourceType.PARASUT
    assert processed[1].source_type == SyncSourceType.GARANTI


def test_orchestrator_get_batch_summary(sample_batch, sample_transaction):
    """Test orchestrator generates batch summary."""
    orchestrator = DataSyncOrchestrator()
    sample_batch.transactions.append(sample_transaction)

    summary = orchestrator.get_batch_summary(sample_batch)

    assert summary["source"] == "parasut"
    assert summary["transactions"] == 1
    assert summary["errors"] == 0
    assert "data_hash" in summary


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Audit Trail
# ═══════════════════════════════════════════════════════════════════════════


def test_audit_trail_computes_batch_hash(sample_batch, sample_transaction):
    """Test audit trail computes consistent hash."""
    from app.services.data_sync.audit import AuditTrail

    sample_batch.transactions.append(sample_transaction)

    hash1 = AuditTrail.compute_batch_hash(sample_batch)
    hash2 = AuditTrail.compute_batch_hash(sample_batch)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex string


def test_audit_trail_creates_sync_log(sample_batch):
    """Test audit trail creates sync log entry."""
    from app.services.data_sync.audit import AuditTrail

    started = datetime.now(timezone.utc)
    ended = started + timedelta(seconds=5)

    log = AuditTrail.create_sync_log(
        sample_batch,
        status="success",
        started_at=started,
        ended_at=ended,
    )

    assert log.source_type == SyncSourceType.PARASUT
    assert log.status == "success"
    assert log.duration_ms == 5000
