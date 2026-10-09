"""
API Contract Tests for Semantic Spine (Phase 1).

Contracts tested:
  - POST /api/v1/semantic/me/rebuild -> 200, metrics > 0
  - GET  /api/v1/semantic/me         -> snapshot with period_key set
  - GET  /api/v1/semantic/me/brief   -> decision brief with headline + health_score
  - GET  /api/v1/negotiation/conflicts/{org_id} -> conflicts list
  - POST /api/v1/chat/agent          -> grounded answer with evidence / meta
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.canonical_transaction import CanonicalTransaction
from app.services.company_context import CompanyContext, save_company_context
from tests.api_helpers import bellek_istemcisi, kullanici

PERIOD_KEY = "2026-08"
TX_DATE = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


async def _seed_data(session, org_id: str):
    ctx = CompanyContext(org_id=org_id)
    ctx.company_name = "Semantic Contract Org"
    ctx.reporting_period = PERIOD_KEY
    ctx.last_cfo_result = {
        "pnl": {"revenue_cents": 1_600_000, "net_margin": 0.05, "gross_margin": 0.4},
        "cashflow": {"operating": 10_000},
        "forecast": {"scenarios": {"base": {"runway_months": 3.0}}},
        "anomalies": [],
    }
    ctx.last_cmo_result = {
        "campaigns": {"overall_roas": 4.0},
    }
    await save_company_context(ctx, session)

    session.add(
        CanonicalTransaction(
            org_id=org_id,
            source_type="crm_export",
            source_record_id="in-1",
            transaction_date=TX_DATE,
            amount_cents=1_000_000,
            currency="USD",
            direction="inflow",
            confidence=90,
        )
    )
    session.add(
        CanonicalTransaction(
            org_id=org_id,
            source_type="crm_export",
            source_record_id="out-1",
            transaction_date=TX_DATE,
            amount_cents=200_000,
            currency="USD",
            direction="outflow",
            confidence=90,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_semantic_api_contract_rebuild_and_read():
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "admin@semantic-test.com", role="admin")
        assert org_id is not None

        # Seed contradiction / canonical transactions
        async with client._maker() as session:
            await _seed_data(session, org_id)

        # 1. POST /semantic/me/rebuild -> 200, metrics length > 0
        res_rebuild = await client.post("/api/v1/semantic/me/rebuild", headers=headers)
        assert res_rebuild.status_code == 200, res_rebuild.text
        data_rebuild = res_rebuild.json().get("data")
        assert data_rebuild is not None
        assert "metrics" in data_rebuild
        assert len(data_rebuild["metrics"]) > 0

        # 2. GET /semantic/me -> snapshot with period_key set
        res_get = await client.get("/api/v1/semantic/me", headers=headers)
        assert res_get.status_code == 200
        data_get = res_get.json().get("data")
        assert data_get is not None
        assert data_get["snapshot"] is not None
        assert data_get["period_key"] == PERIOD_KEY

        # 3. GET /semantic/me/brief -> decision brief
        res_brief = await client.get("/api/v1/semantic/me/brief", headers=headers)
        assert res_brief.status_code == 200
        data_brief = res_brief.json().get("data")
        assert data_brief is not None
        brief = data_brief.get("brief")
        assert brief is not None
        assert "headline" in brief
        assert "health_score" in brief

        # 4. GET /negotiation/conflicts/{org_id} -> list returns
        res_conflicts = await client.get(f"/api/v1/negotiation/conflicts/{org_id}", headers=headers)
        assert res_conflicts.status_code == 200
        conflicts_payload = res_conflicts.json().get("data")
        assert isinstance(conflicts_payload, dict)
        conflicts_list = conflicts_payload.get("conflicts", [])
        assert isinstance(conflicts_list, list)
        # Contradiction seed has CFO revenue 1_600_000 vs inflow 1_000_000 -> conflict expected
        assert len(conflicts_list) >= 1
        assert any(
            "revenue" in c.get("topic", "") or "growth" in c.get("topic", "")
            for c in conflicts_list
        )


@pytest.mark.asyncio
async def test_chat_agent_runway_grounded():
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "ceo@semantic-chat-test.com", role="cfo")
        assert org_id is not None

        async with client._maker() as session:
            await _seed_data(session, org_id)

        # First rebuild snapshot so semantic metrics exist
        await client.post("/api/v1/semantic/me/rebuild", headers=headers)

        # Mock chat_with_cfo response
        mock_llm_response = "Şirketinizin güncel finansal projeksiyonuna göre nakit pisti (runway) 3.0 aydır."

        with patch("app.agents.chat_agent.chat_with_cfo", new=AsyncMock(return_value=mock_llm_response)):
            res_chat = await client.post(
                "/api/v1/chat/agent",
                headers=headers,
                json={"question": "Kaç aylık nakit pistim (runway) kaldı?", "agent_filter": "cfo"},
            )
            assert res_chat.status_code == 200, res_chat.text
            body = res_chat.json()
            assert "data" in body
            assert body["data"] is not None
            assert "3.0" in body["data"]["answer"]
