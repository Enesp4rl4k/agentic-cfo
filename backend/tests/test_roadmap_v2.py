"""
Master Roadmap 2.0 Feature Tests:
1. Epic 1: Two-Way ERP Sync Engine (Logo, Mikro, Paraşüt Journal Voucher Pusher)
2. Epic 2: Financial RAG & Contract Intelligence Engine (Terms, Penalties, CPI Clauses)
3. Epic 3: Prescriptive Cashflow Recommender (Dynamic Discounts, Term Extensions)
4. Epic 4: Multi-Entity & Holding Consolidation Engine (Intercompany Eliminations & Minority Share)
5. Epic 5: Omnichannel CFO Bot Gateway (WhatsApp & Slack Interactive Approval)
"""
from __future__ import annotations

import pytest

from app.services.bot_gateways import OmnichannelCFOBotGateway
from app.services.consolidation_engine import (
    ConsolidationEngine,
    EntityFinancialData,
    IntercompanyTransaction,
)
from app.services.erp.two_way_sync import ERPJournalPusher
from app.services.financial_rag import FinancialRAGEngine
from app.services.prescriptive_recommender import PrescriptiveRecommender

# ── Epic 1: Two-Way ERP Sync Tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_erp_journal_pusher_balanced_entry():
    lines = [
        {"account_code": "102.01", "debit_cents": 1000000, "credit_cents": 0},
        {"account_code": "600.01", "debit_cents": 0, "credit_cents": 1000000},
    ]
    res = await ERPJournalPusher.push_journal_entry(
        erp_type="logo",
        voucher_date="2024-03-31",
        journal_lines=lines,
    )
    assert res.status == "synced"
    assert res.voucher_no.startswith("YVM-")
    assert res.total_debit_cents == 1000000
    assert res.total_credit_cents == 1000000


@pytest.mark.asyncio
async def test_erp_journal_pusher_unbalanced_entry_rejected():
    lines = [
        {"account_code": "102.01", "debit_cents": 1000000, "credit_cents": 0},
        {"account_code": "600.01", "debit_cents": 0, "credit_cents": 800000},
    ]
    res = await ERPJournalPusher.push_journal_entry(
        erp_type="mikro",
        voucher_date="2024-03-31",
        journal_lines=lines,
    )
    assert res.status == "failed"
    assert "dengesiz" in res.error_message.lower()


# ── Epic 2: Financial RAG & Contract Intelligence Tests ───────────────────────

def test_financial_rag_contract_clauses():
    contract_sample = """
    TARAFLAR ARASINDAKİ TİCARİ SÖZLEŞME
    1. Ödeme Vadesi: Faturaların bedeli fatura tarihinden itibaren 45 gün içinde ödenecektir.
    2. Gecikme Faizi: Vadesinde ödenmeyen tutarlara aylık %3 gecikme faizi uygulanır.
    3. Yıllık Fiyat Artışı: Hizmet bedeli her yıl TÜİK TÜFE 12 aylık ortalama enflasyon artışı oranında revize edilir.
    """
    res = FinancialRAGEngine.analyze_document_text(
        document_id="doc-123",
        document_title="Tedarikçi Hizmet Sözleşmesi",
        text=contract_sample,
    )
    assert res.document_id == "doc-123"
    assert len(res.detected_clauses) == 3
    clause_types = [c.clause_type for c in res.detected_clauses]
    assert "payment_term" in clause_types
    assert "penalty" in clause_types
    assert "price_escalation" in clause_types


# ── Epic 3: Prescriptive Cashflow Recommender Tests ───────────────────────────

def test_prescriptive_cashflow_recommender():
    report = PrescriptiveRecommender.analyze_and_prescribe(
        cash_balance_cents=50000000,       # 500,000 TL
        monthly_burn_cents=20000000,       # 200,000 TL / ay (2.5 ay runway)
        receivables_cents=60000000,        # 600,000 TL alacak
        payables_cents=40000000,           # 400,000 TL borç
        target_runway_months=12.0,
    )
    assert report.current_runway_months == 2.5
    assert len(report.actions) >= 2
    assert report.total_recoverable_cash_try > 0
    assert report.projected_runway_after_actions > report.current_runway_months


# ── Epic 4: Multi-Entity Consolidation Tests ─────────────────────────────────

def test_consolidation_engine_with_eliminations():
    entities = [
        EntityFinancialData(
            entity_id="ent-a",
            entity_name="Ana Şirket A.Ş.",
            ownership_pct=100.0,
            revenue_cents=100000000,
            cogs_cents=50000000,
            operating_expenses_cents=20000000,
            net_income_cents=30000000,
            cash_cents=40000000,
            receivables_cents=20000000,
            payables_cents=15000000,
        ),
        EntityFinancialData(
            entity_id="ent-b",
            entity_name="Bağlı Ortaklık B Ltd.",
            ownership_pct=80.0,
            revenue_cents=40000000,
            cogs_cents=20000000,
            operating_expenses_cents=10000000,
            net_income_cents=10000000,
            cash_cents=15000000,
            receivables_cents=10000000,
            payables_cents=8000000,
        ),
    ]
    intercompany = [
        IntercompanyTransaction(
            seller_entity_id="ent-b",
            buyer_entity_id="ent-a",
            amount_cents=15000000,
            transaction_type="sales",
        )
    ]
    res = ConsolidationEngine.consolidate(
        reporting_period="2024-Q1",
        entities=entities,
        intercompany_txs=intercompany,
    )
    assert res.entities_count == 2
    assert res.gross_combined_revenue_cents == 140000000
    assert res.intercompany_eliminations_revenue_cents == 15000000
    assert res.consolidated_revenue_cents == 125000000
    assert res.minority_interest_cents == 2000000  # %20 of 10,000,000 net income


# ── Epic 5: Omnichannel CFO Bot Gateway Tests ─────────────────────────────────

def test_bot_gateway_commands():
    ctx = {
        "revenue_cents": 200000000,
        "cash_cents": 120000000,
        "runway_months": 18.0,
        "vat_payable_cents": 3500000,
    }
    # 1. Nakit komutu
    cash_resp = OmnichannelCFOBotGateway.handle_command(
        channel="whatsapp",
        sender_id="+905551234567",
        message_text="nakit durumu nedir?",
        financial_context=ctx,
    )
    assert "Kasa & Banka" in cash_resp.reply_text
    assert "18.0" in cash_resp.reply_text

    # 2. Vergi komutu
    vat_resp = OmnichannelCFOBotGateway.handle_command(
        channel="whatsapp",
        sender_id="+905551234567",
        message_text="bu ayki kdv ne kadar?",
        financial_context=ctx,
    )
    assert "KDV" in vat_resp.reply_text

    # 3. Onay komutu
    approval_resp = OmnichannelCFOBotGateway.handle_command(
        channel="slack",
        sender_id="U12345",
        message_text="fatura onayı",
        financial_context=ctx,
    )
    assert approval_resp.action_type == "approval_requested"
    assert len(approval_resp.interactive_blocks) >= 2
