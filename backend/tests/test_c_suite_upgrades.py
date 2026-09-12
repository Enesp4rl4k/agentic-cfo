"""
Tests for Agentic C-Suite Upgrades:
1. Long-Term Boardroom Memory
2. Action Execution & Human-in-the-Loop Engine
3. Autonomous Ingestion Webhooks
"""
from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.services.execution.action_runner import ActionRunner
from app.services.negotiation.boardroom import (
    BoardroomConsensus,
    BoardroomDebateResult,
    BoardroomStatement,
)
from app.services.negotiation.boardroom_memory import (
    BoardroomMemoryService,
)

SAMPLE_UBL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>GIB2026000009999</cbc:ID>
    <cbc:IssueDate>2026-08-27</cbc:IssueDate>
    <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>AWS Cloud Hizmetleri A.Ş.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingSupplierParty>
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>Agentic CFO Tech Ltd.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>
    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="TRY">20000.00</cbc:TaxAmount>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="TRY">100000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="TRY">20000.00</cbc:TaxAmount>
            <cbc:Percent>20</cbc:Percent>
            <cac:TaxCategory>
                <cac:TaxScheme>
                    <cbc:Name>KDV</cbc:Name>
                    <cbc:TaxTypeCode>0015</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="TRY">100000.00</cbc:LineExtensionAmount>
        <cbc:TaxExclusiveAmount currencyID="TRY">100000.00</cbc:TaxExclusiveAmount>
        <cbc:TaxInclusiveAmount currencyID="TRY">120000.00</cbc:TaxInclusiveAmount>
        <cbc:PayableAmount currencyID="TRY">120000.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
</Invoice>"""


@pytest.mark.asyncio
async def test_boardroom_memory_and_past_context(tmp_path: Path):
    mem_file = tmp_path / "debates_test.json"
    memory_svc = BoardroomMemoryService(storage_path=mem_file)

    mock_debate = BoardroomDebateResult(
        topic="Pazarlama Bütçesi ve Vergi Ödemeleri",
        round_1_statements=[
            BoardroomStatement(agent_name="CMO", argument="Bütçe %30 artmalı", proposed_solution="Aşama aşama artıralım"),
            BoardroomStatement(agent_name="CFO", argument="Nakit akışı sıkışık", proposed_solution="%10 artıralım"),
        ],
        round_2_statements=[
            BoardroomStatement(agent_name="CMO", argument="Tamam %15 olsun", proposed_solution="%15 artış"),
            BoardroomStatement(agent_name="CFO", argument="Kabul", proposed_solution="15 gün sonra ROI kontrolü"),
        ],
        consensus=BoardroomConsensus(
            topic="Pazarlama Bütçesi ve Vergi Ödemeleri",
            resolution_status="Uzlaşıldı",
            final_decision="Bütçe bu ay %15 artırılacak.",
            confidence_score=0.90,
            action_items=[
                "CMO: Google Ads bütçesini %15 artır.",
                "CFO: Muhasebede bütçe kalemi oluştur.",
            ],
        ),
    )

    record = memory_svc.save_debate(
        topic="Pazarlama Bütçesi ve Vergi Ödemeleri",
        context="Nakit akışı ve büyüme",
        agents=["CMO", "CFO"],
        debate_result=mock_debate,
        org_id="org-A",
    )

    assert record.id.startswith("deb-")
    assert len(record.action_items) == 2
    assert record.action_items[0].responsible_agent == "CMO"
    assert record.action_items[0].status == "pending"

    # Test context retrieval for new debate
    past_ctx = memory_svc.get_past_context_for_topic("pazarlama bütçesi", org_id="org-A")
    assert "Geçmiş Yönetim Kurulu Kararları" in past_ctx
    assert "Bütçe bu ay %15 artırılacak." in past_ctx

    # Another company's debate is primed with none of it. The memory used to be
    # one pool, sent to the LLM for every organisation.
    other = memory_svc.get_past_context_for_topic("pazarlama bütçesi", org_id="org-B")
    assert "Bütçe bu ay %15 artırılacak." not in other
    assert memory_svc.list_pending_actions("org-B") == []
    assert len(memory_svc.list_pending_actions("org-A")) == 2


@pytest.mark.asyncio
async def test_action_runner_execution_and_rejection(tmp_path: Path):
    mem_file = tmp_path / "debates_test2.json"
    memory_svc = BoardroomMemoryService(storage_path=mem_file)

    mock_debate = BoardroomDebateResult(
        topic="Google Ads Kampanya Artışı",
        round_1_statements=[],
        round_2_statements=[],
        consensus=BoardroomConsensus(
            topic="Google Ads Kampanya Artışı",
            resolution_status="Uzlaşıldı",
            final_decision="Google Ads onaylandı.",
            confidence_score=0.85,
            action_items=["CMO: Google Ads bütçesini artır."],
        ),
    )

    record = memory_svc.save_debate(
        topic="Google Ads Kampanya Artışı",
        context="",
        agents=["CMO"],
        debate_result=mock_debate,
    )

    action_id = record.action_items[0].id

    runner = ActionRunner()
    runner.memory = memory_svc

    # Approve & execute
    result = await runner.execute_action(action_id, approved_by_user_id="CEO@agentic.ai")
    assert result.success is True
    assert result.target_system == "GoogleAdsAPI"
    assert "Google Ads API" in result.message

    # Verify status changed in memory
    updated_act = memory_svc.get_action_by_id(action_id)
    assert updated_act.status == "executed"
    assert updated_act.execution_result["approved_by"] == "CEO@agentic.ai"


@pytest.mark.asyncio
async def test_autonomous_efatura_webhook_parsing():
    invoice = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_XML)
    assert invoice is not None
    assert invoice.invoice_number == "GIB2026000009999"
    assert invoice.supplier.title == "AWS Cloud Hizmetleri A.Ş."
    assert invoice.payable_amount == Decimal("120000.00")
    assert invoice.tax_inclusive_total == Decimal("120000.00")
