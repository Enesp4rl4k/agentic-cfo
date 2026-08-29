"""
Tests for Advanced Capabilities:
1. Executive Board Deck PDF Exporter (ReportLab)
2. Inflation Accounting Engine (TMS 29 / VUK)
3. Multi-Channel Alert Dispatcher (Slack & Webhook)
4. Demo Data Seeder & Playground Engine
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.services.alert_dispatcher import AlertDispatcher
from app.services.board_deck_pdf import BoardDeckPDFExporter
from app.services.demo_seeder import DemoSeeder
from app.services.inflation_accounting import InflationAccountingEngine

# ── 1. Executive Board Deck PDF Exporter Tests ─────────────────────────────────

def test_board_deck_pdf_exporter_generates_valid_pdf():
    pnl = {
        "revenue": 50000000,
        "cogs": 20000000,
        "gross_profit": 30000000,
        "operating_expenses": 15000000,
        "net_income": 15000000,
        "gross_margin_pct": 60.0,
        "narrative": "Şirket bu çeyrekte güçlü nakit yaratımı ve kârlılık sergilemiştir.",
    }
    cashflow = {
        "operating": 12000000,
        "investing": -2000000,
        "financing": 0,
        "net_change": 10000000,
    }
    forecast = {
        "runway_months": 24,
    }
    anomalies = [{"severity": "high", "description": "Tedarikçi fatura mükerrerliği tespit edildi"}]
    alerts = [{"severity": "warning", "message": "KDV ödeme günü 3 gün sonra"}]

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = os.path.join(tmp_dir, "board_deck_test.pdf")
        exporter = BoardDeckPDFExporter()
        res_path = exporter.export(
            pnl=pnl,
            cashflow=cashflow,
            forecast=forecast,
            output_path=out_path,
            company_name="MegaTech Holding A.Ş.",
            period="2024-Q2",
            anomalies=anomalies,
            alerts=alerts,
        )

        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000  # Multi-page PDF generated


# ── 2. Inflation Accounting (TMS 29) Tests ────────────────────────────────────

def test_inflation_accounting_engine():
    balance_sheet = [
        {"name": "Banka TL Mevduat", "is_monetary": True, "is_liability": False, "amount_cents": 10000000},
        {"name": "Banka Kredi Borcu", "is_monetary": True, "is_liability": True, "amount_cents": 4000000},
        {"name": "Ticari Mallar (Stok)", "is_monetary": False, "is_liability": False, "acquisition_period": "2023-12", "amount_cents": 8000000},
        {"name": "Sermaye ve Özkaynak", "is_monetary": False, "is_liability": False, "acquisition_period": "2023-01", "amount_cents": 14000000},
    ]

    result = InflationAccountingEngine.calculate_adjustment(
        reporting_period="2024-06",
        balance_sheet_items=balance_sheet,
    )

    assert result.reporting_period == "2024-06"
    assert result.monetary_assets_cents == 10000000
    assert result.monetary_liabilities_cents == 4000000
    assert result.net_monetary_position_cents == 6000000
    assert result.net_monetary_loss_cents > 0
    assert len(result.adjusted_assets) == 4
    assert result.cfo_commentary != ""


# ── 3. Multi-Channel Alert Dispatcher Tests ───────────────────────────────────

@pytest.mark.asyncio
async def test_alert_dispatcher_slack_and_webhook():
    slack_alert = await AlertDispatcher.dispatch_slack(
        webhook_url="https://dummy.slack.webhook",
        title="Kritik Nakit Riski",
        message="Nakit Runway 2.4 aya düştü.",
        severity="critical",
        fields={"Runway": "2.4 Ay", "Aylık Açık": "₺450,000"},
    )
    assert slack_alert.channel == "slack"
    assert slack_alert.delivered is True
    assert slack_alert.severity == "critical"

    wh_alert = await AlertDispatcher.dispatch_webhook(
        webhook_url="https://dummy.webhook/cfo-events",
        event_type="TAX_DEADLINE_APPROACHING",
        data={"period": "2024-03", "kdv_due_date": "2024-04-26"},
    )
    assert wh_alert.channel == "webhook"
    assert wh_alert.delivered is True


# ── 4. Demo Data Seeder Tests ─────────────────────────────────────────────────

def test_demo_seeder_all_scenarios():
    saas = DemoSeeder.seed_scenario("saas_startup")
    assert saas.scenario_id == "saas_startup"
    assert len(saas.transactions) >= 5
    assert len(saas.invoices) >= 3
    assert saas.summary["runway_months"] == 24.0

    ecom = DemoSeeder.seed_scenario("ecommerce_scaleup")
    assert ecom.scenario_id == "ecommerce_scaleup"
    assert len(ecom.transactions) >= 2

    mfg = DemoSeeder.seed_scenario("manufacturing_sme")
    assert mfg.scenario_id == "manufacturing_sme"
    assert len(mfg.transactions) >= 2
