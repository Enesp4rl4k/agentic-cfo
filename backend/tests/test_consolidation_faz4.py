"""Faz 4: Konsolide Grup & İlişkili Taraf Eliminasyonu Doğrulama Testleri.

Doğrulamalar:
1. Şirket A ve Şirket B arasındaki karşılıklı alacak ve borcun konsolide radarda kuruşu kuruşuna elenmesi.
2. Çift sayımın sıfırlanması: Brüt giriş/çıkıştan elenen tutarlar düşülerek net dışsal nakit akışının hesaplanması.
3. Kanıtlanabilirlik: Eliminasyon tablosunda hangi açık kalemin neden elendiğinin belgelenmesi.
4. API Endpoint Doğrulaması: POST /api/v1/consolidation/radar uçtan uca testi.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.open_item import OpenItem
from app.models.organization import Organization
from app.models.related_party import RelatedParty
from app.services.consolidation_engine import compute_consolidated_cash_radar
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.db_helpers import gecici_oturum


@pytest.mark.asyncio
async def test_intercompany_elimination_between_two_sister_orgs():
    """4.1 & 4.2: Şirket A'nın Şirket B'den olan alacağı konsolide radarda elenmeli."""
    async with gecici_oturum() as db:
        org_a_id = f"org-a-{uuid.uuid4().hex[:6]}"
        org_b_id = f"org-b-{uuid.uuid4().hex[:6]}"

        org_a = Organization(id=org_a_id, name="Holding Enerji A.Ş.", slug=f"slug-{org_a_id}")
        org_b = Organization(
            id=org_b_id, name="Holding Lojistik Ltd. Şti.", slug=f"slug-{org_b_id}"
        )
        db.add_all([org_a, org_b])
        await db.commit()

        # Şirket A, Şirket B'yi ilişkili taraf olarak kaydetmiş
        rp = RelatedParty(
            id=str(uuid.uuid4()),
            org_id=org_a_id,
            name="Holding Lojistik Ltd. Şti.",
            normalized_name="holding lojistik",
            relationship_type="istirak",
            tax_id="1111222233",
            active=True,
        )
        db.add(rp)

        now = datetime.now(UTC).date()
        target_due = now + timedelta(days=14)  # 3. haftaya denk gelsin

        # Şirket A: Şirket B'den ₺250.000 alacaklı (receivable)
        item_a = OpenItem(
            id=str(uuid.uuid4()),
            org_id=org_a_id,
            direction="receivable",
            instrument="invoice",
            document_id="INV-GRP-001",
            counterparty="Holding Lojistik Ltd. Şti.",
            amount_cents=25000000,  # ₺250.000
            paid_cents=0,
            currency="TRY",
            issue_date=now,
            due_date=target_due,
            status="open",
            created_at=datetime.now(UTC),
        )

        # Şirket B: Şirket A'ya ₺250.000 borçlu (payable)
        item_b = OpenItem(
            id=str(uuid.uuid4()),
            org_id=org_b_id,
            direction="payable",
            instrument="invoice",
            document_id="INV-GRP-001",
            counterparty="Holding Enerji A.Ş.",
            amount_cents=25000000,  # ₺250.000
            paid_cents=0,
            currency="TRY",
            issue_date=now,
            due_date=target_due,
            status="open",
            created_at=datetime.now(UTC),
        )

        # Şirket B: Dışarıdan üçüncü şahsa (Harici Müşteri) ₺100.000 alacak (receivable)
        item_external = OpenItem(
            id=str(uuid.uuid4()),
            org_id=org_b_id,
            direction="receivable",
            instrument="invoice",
            document_id="INV-EXT-002",
            counterparty="Harici Müşteri Ltd.",
            amount_cents=10000000,  # ₺100.000
            paid_cents=0,
            currency="TRY",
            issue_date=now,
            due_date=target_due,
            status="open",
            created_at=datetime.now(UTC),
        )

        db.add_all([item_a, item_b, item_external])
        await db.commit()

        # Konsolide radarı hesapla
        consolidated = await compute_consolidated_cash_radar(
            db,
            org_ids=[org_a_id, org_b_id],
            group_name="Holding Grubu",
            anchor_date=now,
        )

        # Doğrulamalar:
        assert consolidated.group_name == "Holding Grubu"
        assert len(consolidated.participating_org_ids) == 2

        # Eliminasyon kontrolü:
        # Şirket A'nın alacağı ve Şirket B'nin borcu tespit edilip elenmeli
        assert len(consolidated.eliminations) >= 2
        assert consolidated.total_eliminated_cents >= 50000000  # ₺250k alacak + ₺250k borç elendi

        # Hedef haftadaki (3. hafta) net giriş ve çıkış kontrolü:
        target_week_idx = (target_due - now).days // 7
        target_week = consolidated.weeks[target_week_idx]

        # Brüt giriş = 250k (grup içi) + 100k (harici) = 350.000 TL
        # Elenen giriş = 250k (grup içi alacak)
        # Net giriş = Tam olarak 100.000 TL olmalı!
        assert target_week.net_inflow_cents == 10000000, (
            f"Beklenen net giriş ₺100.000, hesaplanan ₺{target_week.net_inflow_cents / 100:,.2f}"
        )

        # Brüt çıkış = 250k (grup içi)
        # Elenen çıkış = 250k (grup içi borç)
        # Net çıkış = Tam olarak 0 TL olmalı!
        assert target_week.net_outflow_cents == 0, (
            f"Beklenen net çıkış ₺0, hesaplanan ₺{target_week.net_outflow_cents / 100:,.2f}"
        )


@pytest.mark.asyncio
async def test_api_consolidated_radar_endpoint():
    """4.3: POST /api/v1/consolidation/radar API testi."""
    async with bellek_istemcisi() as client:
        headers, org_id, _user_id = await kullanici(client, "holding_ceo@holding.com")

        resp = await client.post(
            "/api/v1/consolidation/radar",
            headers=headers,
            json={
                "org_ids": [org_id],
                "group_name": "Ana Holding",
            },
        )
        assert resp.status_code == 200, f"Hata: {resp.text}"
        data = resp.json()["data"]
        assert data["group_name"] == "Ana Holding"
        assert "weeks" in data
        assert len(data["weeks"]) == 13
        assert "eliminations" in data
        assert len(data["insights"]) >= 1
