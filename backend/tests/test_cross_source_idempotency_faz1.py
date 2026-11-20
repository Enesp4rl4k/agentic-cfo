"""Faz 1: Dış Veri Güvenliği ve Mükerrerlik Koruması (G2 & G17) Doğrulama Testleri.

Doğrulamalar:
1. Konnektör Kayıt Defteri (Registry): 'parasut' ve 'open_banking' adaptörlerinin varlığı.
2. Kanonik Fatura Kimliği Çözümleyici: GİB 16 haneli e-Fatura numarası ve serbest numara çıkarımı.
3. Çapraz Kaynak Mükerrerlik Koruması (G2): Dosya yüklemesi ile Paraşüt ERP'den gelen aynı faturanın
   tekilleştirilmesi; kuruşu kuruşuna tek işlem, sıfır çift sayım, tek açık kalem.
4. Açık Bankacılık PSD2 ve Paraşüt Adaptör Sağlık & Çekim Kontrolleri.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.main  # noqa: F401
from app.connectors import registry
from app.connectors.base import Watermark
from app.connectors.open_banking import OpenBankingConnectorAdapter
from app.connectors.parasut import ParasutConnectorAdapter
from app.core.invoice_identity import canonical_invoice_id
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services import ledger
from tests.db_helpers import gecici_oturum

# No global pytestmark = pytest.mark.asyncio to avoid warning on sync tests


@pytest_asyncio.fixture
async def db():
    async with gecici_oturum() as session:
        yield session


async def _create_org(db, org_id: str = "org-test-faz1") -> Organization:
    existing = await db.get(Organization, org_id)
    if existing:
        return existing
    org = Organization(id=org_id, name="Test Faz1 Corp", slug=f"slug-{org_id}")
    db.add(org)
    await db.commit()
    return org


def test_connectors_registered_in_registry():
    """1.1 Konnektör Çerçevesinin Standartlaştırılması."""
    assert registry.has_connector("parasut"), "ParasutConnectorAdapter registry'de kayıtlı olmalı"
    assert registry.has_connector("open_banking"), (
        "OpenBankingConnectorAdapter registry'de kayıtlı olmalı"
    )
    assert registry.has_connector("github"), "GitHubConnector registry'de kayıtlı olmalı"

    parasut = registry.get_connector("parasut")
    assert isinstance(parasut, ParasutConnectorAdapter)
    assert parasut.domain == "finance"
    assert parasut.kernel_role == "cfo"

    banking = registry.get_connector("open_banking")
    assert isinstance(banking, OpenBankingConnectorAdapter)
    assert banking.domain == "banking"
    assert banking.kernel_role == "cfo"


def test_canonical_invoice_id_resolution():
    """1.2 Deterministik Fatura Kimliği Çözümleyici (GİB 16 hane, serbest numara, UUID)."""
    # GİB 16-character format
    gib_no = "GIB2024000000001"
    assert canonical_invoice_id(None, gib_no, None) == gib_no
    assert canonical_invoice_id("doc:123", None, f"e-Fatura {gib_no} nolu fatura") == gib_no
    assert canonical_invoice_id(gib_no, None, "Açıklama") == gib_no

    # Alphanumeric invoice marker #A-1 or Fatura No:
    assert canonical_invoice_id(None, None, "Satış faturası #A-1") == "A-1"
    assert canonical_invoice_id(None, None, "Hizmet Bedeli Fatura No: 2024-0012") == "2024-0012"
    assert canonical_invoice_id(None, "INV-999", None) == "INV-999"

    # UUID fallback
    test_uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert canonical_invoice_id(test_uuid, None, "Düz fatura") == test_uuid


@pytest.mark.asyncio
async def test_cross_source_deduplication_file_vs_parasut(db):
    """G2 Çözümü: Bir dosya yüklemesi ile Paraşüt sync'i aynı faturayı gönderdiğinde
    ikincisi 'already' olarak sayılmalı ve mükerrer kayıt yaratılmamalıdır.
    """
    org = await _create_org(db, f"org-g2-{uuid.uuid4().hex[:8]}")
    org_id = org.id
    now = datetime.now(UTC)

    # 1. Kaynak: Dosya Yüklemesi Analiz İşi (Job 1)
    job1 = AnalysisJob(
        id=str(uuid.uuid4()),
        org_id=org_id,
        status=JobStatus.COMPLETED,
        filename="fatura_upload.csv",
        file_path="/tmp/fatura_upload.csv",
        file_type="csv",
    )
    db.add(job1)
    await db.flush()

    tx1 = Transaction(
        id=str(uuid.uuid4()),
        job_id=job1.id,
        transaction_date=now - timedelta(days=5),
        amount_kurus=1500000,  # 15.000,00 TL
        type="income",
        currency="TRY",
        category="Satış Geliri",
        vendor="Acme Corp",
        counterparty="Acme Corp",
        description="Satış faturası #GIB2024000000042",
        document_id="doc:GIB2024000000042",
        due_date=now + timedelta(days=25),
        date_is_estimated=False,
    )
    db.add(tx1)
    await db.commit()

    # Job 1'i deftere işle
    counts1 = await ledger.append_job(db, job1.id)
    assert counts1["new"] == 1
    assert counts1["already"] == 0
    assert counts1["possible_duplicate"] == 0

    # 2. Kaynak: Paraşüt Entegrasyonundan Gelen İkinci Analiz İşi (Job 2)
    # Farklı açıklama formatı, ancak aynı GİB fatura numarası (#GIB2024000000042)
    job2 = AnalysisJob(
        id=str(uuid.uuid4()),
        org_id=org_id,
        status=JobStatus.COMPLETED,
        filename="parasut_sync.csv",
        file_path="/tmp/parasut_sync.csv",
        file_type="csv",
    )
    db.add(job2)
    await db.flush()

    tx2 = Transaction(
        id=str(uuid.uuid4()),
        job_id=job2.id,
        transaction_date=now - timedelta(days=5),
        amount_kurus=1500000,  # Aynı tutar
        type="income",
        currency="TRY",
        category="Hizmet Satışı",
        vendor="Acme Corp A.Ş.",
        counterparty="Acme Corp A.Ş.",
        description="Paraşüt Otomasyon Çekimi GIB2024000000042 nolu e-fatura",
        document_id="GIB2024000000042",  # Paraşüt'ten ham fatura no gelmiş, doc: prefix'i yok
        due_date=now + timedelta(days=25),
        date_is_estimated=False,
    )
    db.add(tx2)
    await db.commit()

    # Job 2'yi deftere işle
    counts2 = await ledger.append_job(db, job2.id)
    # Kritik G2 Doğrulaması: Mükerrer transaction yazılmamalı, 'already' sayılmalı!
    assert counts2["new"] == 0, "Aynı fatura tekrar yeni olarak eklenmemeli"
    assert counts2["already"] == 1, "Aynı fatura 'already' olarak tanınmalı"
    assert counts2["possible_duplicate"] == 0, (
        "Fatura numarası eşleştiği için şüpheli mükerrer değil, kesin aynı kayıt olmalı"
    )

    # Defterdeki kanonik işlem sayısını kontrol et: Tam olarak 1 olmalı
    canonical_rows = (
        (
            await db.execute(
                select(CanonicalTransaction).where(CanonicalTransaction.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(canonical_rows) == 1
    assert canonical_rows[0].source_record_id == "doc:GIB2024000000042"
    assert canonical_rows[0].amount_cents == 1500000

    # Açık kalem (OpenItem) sayısını kontrol et: Tam olarak 1 olmalı
    open_items = (
        (await db.execute(select(OpenItem).where(OpenItem.org_id == org_id))).scalars().all()
    )
    assert len(open_items) == 1
    assert open_items[0].document_id == "GIB2024000000042"


@pytest.mark.asyncio
async def test_open_banking_adapter_health_and_fetch():
    """1.3 Açık Bankacılık PSD2 Adaptör Sağlık ve Çekim Doğrulaması."""
    adapter = OpenBankingConnectorAdapter()

    # Health check - missing token
    h_bad = await adapter.health(config={"bank": "garanti"}, secret={})
    assert not h_bad.ok
    assert "yetki anahtarı eksik" in h_bad.detail

    # Health check - valid token
    h_ok = await adapter.health(
        config={"bank": "garanti", "account_id": "TR1200062000001"},
        secret={"access_token": "mock-token-xyz"},
    )
    assert h_ok.ok
    assert "Garanti açık bankacılık" in h_ok.detail

    # Fetch with PSD2 mock payload
    payload = await adapter.fetch(
        org_id="org-1",
        config={
            "bank": "garanti",
            "account_id": "TR1200062000001",
            "mock_transactions": [
                {
                    "date": "2026-11-10",
                    "amount": 2500.50,
                    "reference": "EFT998877",
                    "description": "Tedarikçi Ödemesi",
                    "type": "expense",
                }
            ],
        },
        secret={"access_token": "mock-token-xyz"},
        since=Watermark(since=datetime(2026, 1, 1, tzinfo=UTC)),
    )
    assert len(payload.rows) == 1
    row = payload.rows[0]
    assert row.source_record_id == "ob:garanti:EFT998877"
    assert row.magnitude == 250050  # 2.500,50 TL -> 250.050 kuruş
    assert row.attributes["bank"] == "garanti"
