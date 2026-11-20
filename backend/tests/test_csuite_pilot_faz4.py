"""Plan v10 §4 (O5) & Plan v11 Faz 4 Testleri:
- C-Suite Defter Entegrasyonu (CHRO, COO, CTO)
- Pilot Metrikleri: 4 Haftalık Radar Backtesting ve Karar Defteri Başarı Oranları
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.cash_radar_snapshot import CashRadarSnapshot
from app.models.decision_log import DecisionLog
from app.services.csuite_ledger import (
    compute_chro_metrics,
    compute_coo_metrics,
    compute_cto_metrics,
)
from app.services.ledger import append_job
from app.services.pilot_metrics import compute_decision_success_metrics, compute_radar_backtesting
from tests.api_helpers import bellek_istemcisi, kullanici

ANCHOR = date(2025, 2, 1)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _statement(day: str, cents: int) -> dict[str, Any]:
    return {"closing_balance": {"date": day, "balance_cents": cents}}


async def _upload(
    client,
    org_id: str,
    *rows: dict[str, Any],
    meta: dict | None = None,
    status: JobStatus = JobStatus.COMPLETED,
) -> str:
    from app.models.transaction import Transaction

    async with client._maker() as db:
        job = AnalysisJob(
            filename="test.csv",
            file_path="/test.csv",
            file_type="csv",
            org_id=org_id,
            status=status,
            result_metadata=meta,
        )
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(
                Transaction(
                    job_id=job.id,
                    amount_kurus=r["amount_cents"],
                    currency=r.get("currency", "TRY"),
                    type=r["type"],
                    category=r.get("category", "other_expense"),
                    description=r.get("description"),
                    transaction_date=when,
                    date_is_estimated=estimated,
                    vendor=r.get("counterparty") or r.get("vendor"),
                )
            )
        await db.commit()
        await append_job(db, job.id)
        return job.id


@pytest.mark.asyncio
async def test_chro_metrics_derived_from_ledger():
    """CHRO: Defterdeki maaş/SGK harcamaları ile ciro oranı ve trendi hesaplanmalıdır."""
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "chro@test.com")

        # Geçmiş 3 ay için ciro ve maaş işlemleri
        await _upload(
            client,
            org_id,
            {
                "amount_cents": 500000_00,
                "transaction_date": "2024-11-15",
                "type": "income",
                "description": "Satış Ciro",
            },
            {
                "amount_cents": 150000_00,
                "transaction_date": "2024-11-30",
                "type": "expense",
                "category": "payroll",
                "description": "Maaş Ödemeleri",
            },
            {
                "amount_cents": 600000_00,
                "transaction_date": "2024-12-15",
                "type": "income",
                "description": "Satış Ciro",
            },
            {
                "amount_cents": 180000_00,
                "transaction_date": "2024-12-31",
                "type": "expense",
                "category": "payroll",
                "description": "Maaş Ödemeleri",
            },
            {
                "amount_cents": 550000_00,
                "transaction_date": "2025-01-15",
                "type": "income",
                "description": "Satış Ciro",
            },
            {
                "amount_cents": 165000_00,
                "transaction_date": "2025-01-31",
                "type": "expense",
                "category": "payroll",
                "description": "Maaş Ödemeleri",
            },
        )

        async with client._maker() as db:
            metrics = await compute_chro_metrics(db, org_id, months=6, anchor_date=ANCHOR)

        assert metrics.revenue_cents == 1650000_00
        assert metrics.payroll_cents == 495000_00
        assert metrics.payroll_ratio_pct == 30.0  # 495k / 1650k = 30%
        assert len(metrics.monthly_trend) == 3
        assert "Personel giderleri" in metrics.summary

        # API testi
        resp = await client.get(
            "/api/v1/csuite/chro?months=6&anchor_date=2025-02-01", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["payroll_ratio_pct"] == 30.0
        assert data["revenue_cents"] == 1650000_00


@pytest.mark.asyncio
async def test_coo_metrics_supplier_concentration():
    """COO: Tedarikçi harcama yoğunlaşması Pareto analiziyle hesaplanmalıdır."""
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "coo@test.com")

        # 3 büyük tedarikçi ve küçük tedarikçiler
        await _upload(
            client,
            org_id,
            {
                "amount_cents": 50000_00,
                "transaction_date": "2025-01-10",
                "type": "expense",
                "counterparty": "Tedarikçi A",
                "description": "Hammadde",
            },
            {
                "amount_cents": 30000_00,
                "transaction_date": "2025-01-12",
                "type": "expense",
                "counterparty": "Tedarikçi B",
                "description": "Lojistik",
            },
            {
                "amount_cents": 15000_00,
                "transaction_date": "2025-01-14",
                "type": "expense",
                "counterparty": "Tedarikçi C",
                "description": "Ambalaj",
            },
            {
                "amount_cents": 5000_00,
                "transaction_date": "2025-01-16",
                "type": "expense",
                "counterparty": "Tedarikçi D",
                "description": "Kırtasiye",
            },
        )

        async with client._maker() as db:
            coo = await compute_coo_metrics(db, org_id, days=90, anchor_date=ANCHOR)

        assert coo.total_expense_cents == 100000_00
        assert coo.top1_share_pct == 50.0  # Tedarikçi A: 50%
        assert coo.top3_share_pct == 95.0  # Top 3: 95%
        assert coo.concentration_risk == "HIGH"
        assert len(coo.top_suppliers) == 4

        # API testi
        resp = await client.get(
            "/api/v1/csuite/coo?days=90&anchor_date=2025-02-01", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["concentration_risk"] == "HIGH"
        assert data["top1_share_pct"] == 50.0


@pytest.mark.asyncio
async def test_cto_metrics_cloud_saas_trends():
    """CTO: Bulut ve yazılım abonelikleri defterden otomatik tanınmalıdır."""
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "cto@test.com")

        await _upload(
            client,
            org_id,
            {
                "amount_cents": 12000_00,
                "transaction_date": "2024-12-05",
                "type": "expense",
                "description": "AMAZON WEB SERVICES AWS CLOUD",
            },
            {
                "amount_cents": 3500_00,
                "transaction_date": "2024-12-10",
                "type": "expense",
                "description": "GITHUB INC SUBSCRIPTION",
            },
            {
                "amount_cents": 13000_00,
                "transaction_date": "2025-01-05",
                "type": "expense",
                "description": "AMAZON WEB SERVICES AWS CLOUD",
            },
            {
                "amount_cents": 3500_00,
                "transaction_date": "2025-01-10",
                "type": "expense",
                "description": "GITHUB INC SUBSCRIPTION",
            },
            {
                "amount_cents": 50000_00,
                "transaction_date": "2025-01-20",
                "type": "expense",
                "description": "Ofis Malzemesi",
            },
        )

        async with client._maker() as db:
            cto = await compute_cto_metrics(db, org_id, months=6, anchor_date=ANCHOR)

        assert cto.total_tech_spend_cents == 32000_00
        assert len(cto.recurring_tech_vendors) >= 2
        assert "yazılım ve bulut" in cto.summary

        # API testi
        resp = await client.get(
            "/api/v1/csuite/cto?months=6&anchor_date=2025-02-01", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_tech_spend_cents"] == 32000_00


@pytest.mark.asyncio
async def test_pilot_backtesting_and_decision_metrics():
    """Pilot: 4 haftalık tahmin sapması ve karar kabul oranları test edilir."""
    async with bellek_istemcisi() as client:
        headers, org_id, user_id = await kullanici(client, "pilot@test.com")

        # 4 hafta öncesi için bakiye
        await _upload(
            client,
            org_id,
            meta=_statement("2025-01-04", 100000_00),
        )

        # Hedef tarihte (2025-02-01) gerçekleşen bakiye
        await _upload(
            client,
            org_id,
            meta=_statement("2025-02-01", 95000_00),
        )

        async with client._maker() as db:
            # The backtest compares a forecast that was actually saved four weeks
            # earlier: anchor 2025-01-05, week 4 ending on the target 2025-02-01.
            db.add(
                CashRadarSnapshot(
                    org_id=org_id,
                    anchor_date=date(2025, 1, 5),
                    snapshot_hash="pilot-faz4-backtest",
                    snapshot_json={
                        "anchor_date": "2025-01-05",
                        "weeks": [
                            {"week": 1, "end_date": "2025-01-11", "end_balance_cents": 100000_00},
                            {"week": 2, "end_date": "2025-01-18", "end_balance_cents": 99500_00},
                            {"week": 3, "end_date": "2025-01-25", "end_balance_cents": 99000_00},
                            {"week": 4, "end_date": "2025-02-01", "end_balance_cents": 98000_00},
                        ],
                    },
                )
            )
            # Karar defterine 3 kayıt ekleyelim (2 done, 1 dismissed)
            job = AnalysisJob(
                filename="test.csv",
                file_path="/test.csv",
                file_type="csv",
                org_id=org_id,
                status=JobStatus.COMPLETED,
            )
            db.add(job)
            await db.flush()

            db.add(
                DecisionLog(
                    org_id=org_id,
                    job_id=job.id,
                    topic="Aksiyon 1",
                    chosen_option_id="opt1",
                    chosen_option_label="Yaptım",
                    expected={"source": "cash_radar", "expected_amount_cents": 20000_00},
                    actual={"owner_response": "done"},
                    status="closed",
                    created_by=user_id,
                )
            )
            db.add(
                DecisionLog(
                    org_id=org_id,
                    job_id=job.id,
                    topic="Aksiyon 2",
                    chosen_option_id="opt2",
                    chosen_option_label="Yaptım",
                    expected={"source": "cash_radar", "expected_amount_cents": 30000_00},
                    actual={"owner_response": "done"},
                    status="closed",
                    created_by=user_id,
                )
            )
            db.add(
                DecisionLog(
                    org_id=org_id,
                    job_id=job.id,
                    topic="Aksiyon 3",
                    chosen_option_id="opt3",
                    chosen_option_label="Gerek Yok",
                    expected={"source": "cash_radar", "expected_amount_cents": 10000_00},
                    actual={"owner_response": "dismissed"},
                    status="closed",
                    created_by=user_id,
                )
            )
            await db.commit()

        # 1. Backtesting servisi
        async with client._maker() as db:
            backtest = await compute_radar_backtesting(
                db, org_id, anchor_date=ANCHOR, lookback_weeks=4
            )

        assert backtest.target_date == "2025-02-01"
        assert backtest.actual_proven_balance_cents == 95000_00
        assert backtest.variance_cents is not None
        assert backtest.accuracy_tier in ("HIGH", "MODERATE")

        # 2. Decision metrics servisi
        async with client._maker() as db:
            dec_metrics = await compute_decision_success_metrics(db, org_id)

        assert dec_metrics.total_recommendations == 3
        assert dec_metrics.adopted_count == 2
        assert dec_metrics.dismissed_count == 1
        assert dec_metrics.adoption_rate_pct == 66.67
        assert dec_metrics.correction_rate_pct == 33.33
        assert dec_metrics.total_impact_cents == 50000_00

        # 3. HTTP API testleri
        resp_bt = await client.get(
            "/api/v1/pilot/radar-backtest?anchor_date=2025-02-01&lookback_weeks=4", headers=headers
        )
        assert resp_bt.status_code == 200
        assert resp_bt.json()["data"]["accuracy_tier"] in ("HIGH", "MODERATE")

        resp_dm = await client.get("/api/v1/pilot/decision-metrics", headers=headers)
        assert resp_dm.status_code == 200
        assert resp_dm.json()["data"]["adopted_count"] == 2
        assert resp_dm.json()["data"]["total_impact_cents"] == 50000_00
