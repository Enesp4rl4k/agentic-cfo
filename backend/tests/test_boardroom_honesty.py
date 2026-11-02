"""Plan v9 §K0 — with no model, the boardroom reports that; it does not invent a decision.

`run_boardroom_debate` answered any topic, without an API key, with a canned
consensus ("pazarlama bütçesi bu ay %15 artırılacak", confidence 0.85) and saved
it to the company's memory with action items an owner could approve.
"""
from __future__ import annotations

import json

import pytest

from app.config import get_settings
from app.platform.model_gateway import LLMUnavailable
from app.services.negotiation import boardroom, boardroom_memory
from app.services.negotiation.boardroom_memory import BoardroomMemoryService
from tests.api_helpers import bellek_istemcisi, kullanici

_SAHTE = ("Pazarlama bütçesi bu ay %15 oranında artırılacak ve bütçe yüksek ROI sağlayan "
          "Google Ads kampanyalarına yönlendirilecek.")


@pytest.fixture
def hafiza(monkeypatch, tmp_path) -> BoardroomMemoryService:
    svc = BoardroomMemoryService(storage_path=tmp_path / "debates.json")
    monkeypatch.setattr(boardroom, "get_boardroom_memory", lambda: svc)
    monkeypatch.setattr(boardroom_memory, "get_boardroom_memory", lambda: svc)
    monkeypatch.setattr(get_settings(), "openai_api_key", "llm-placeholder-dev")
    return svc


async def test_no_model_means_no_debate_and_nothing_saved(hafiza):
    with pytest.raises(LLMUnavailable):
        await boardroom.run_boardroom_debate("Yeni depo kiralayalım mı?", "bağlam", org_id="org-1")
    assert hafiza.list_recent_decisions("org-1") == []
    assert hafiza.list_pending_actions("org-1") == []


async def test_the_endpoint_says_503_llm_unavailable(hafiza):
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "kurul@example.com")
        res = await client.post("/api/v1/negotiation/boardroom/debate", headers=headers,
                                json={"topic": "Yeni depo", "context": "bağlam"})
    assert res.status_code == 503, res.text
    assert res.json()["error_code"] == "llm_unavailable"


def test_a_canned_decision_saved_earlier_is_no_precedent_and_cannot_be_approved(tmp_path):
    path = tmp_path / "debates.json"
    path.write_text(json.dumps([{
        "id": "d1", "topic": "Yeni depo", "context": "", "participating_agents": ["CFO", "CMO"],
        "resolution_status": "Uzlaşıldı", "final_decision": _SAHTE, "confidence_score": 0.85,
        "action_items": [{"id": "a1", "debate_id": "d1", "description": "CFO: Bütçe artışı",
                          "responsible_agent": "CFO", "status": "pending", "org_id": "org-1"}],
        "transcript": {}, "org_id": "org-1",
    }]), encoding="utf-8")

    svc = BoardroomMemoryService(storage_path=path)

    assert svc.list_pending_actions("org-1") == []
    assert svc.list_recent_decisions("org-1") == []
    assert _SAHTE not in svc.get_past_context_for_topic("Yeni depo", org_id="org-1")
