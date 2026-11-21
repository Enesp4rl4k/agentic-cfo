"""An approved action that nothing can carry out says so, and records nothing as done.

The runner used to answer "ödeme emri taslağı yazıldı" (slip SLIP-2026-08-994), "+15%" and
"takvim planlandı" without calling anything. No action kind has a connector today, so
approval must never produce a success, an invented id, amount or percentage.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from app.services.execution import action_runner
from app.services.negotiation.boardroom import BoardroomConsensus, BoardroomDebateResult
from app.services.negotiation.boardroom_memory import BoardroomMemoryService
from tests.api_helpers import bellek_istemcisi, kullanici

ITEMS = {
    "marketing_budget": "CMO: Google Ads bütçesini artır.",
    "payment_draft": "CFO: Vergi ödemesi için EFT taslağı hazırla.",
    "schedule": "COO: Ara değerlendirme toplantısı planla.",
    "generic": "CTO: Sunucuları gözden geçir.",
}


def _debate(items: list[str]) -> BoardroomDebateResult:
    return BoardroomDebateResult(
        topic="t",
        round_1_statements=[],
        round_2_statements=[],
        consensus=BoardroomConsensus(
            topic="t", resolution_status="Uzlaşıldı", final_decision="x",
            confidence_score=0.9, action_items=items,
        ),
    )


@pytest.fixture
def memory(tmp_path: Path, monkeypatch) -> BoardroomMemoryService:
    svc = BoardroomMemoryService(storage_path=tmp_path / "d.json")
    monkeypatch.setattr(action_runner, "get_boardroom_memory", lambda: svc)
    monkeypatch.setattr("app.api.actions.get_boardroom_memory", lambda: svc)
    monkeypatch.setattr(action_runner, "_global_action_runner", None)
    return svc


@pytest.mark.parametrize("kind", sorted(ITEMS))
async def test_runner_never_reports_success_for_an_unconnected_action(memory, kind) -> None:
    record = memory.save_debate("t", "", ["x"], _debate([ITEMS[kind]]), org_id="o1")
    action_id = record.action_items[0].id

    result = await action_runner.ActionRunner().execute_action(action_id)

    assert result.success is False
    assert result.outcome == action_runner.NOT_CONNECTED
    assert result.action_kind == kind
    assert result.payload == {}
    assert memory.get_action_by_id(action_id).status == "pending"  # nothing recorded as done


def test_runner_source_has_no_invented_results() -> None:
    source = Path(action_runner.__file__).read_text(encoding="utf-8")
    for invented in ("SLIP-", "+15%", "success=True", "ACTIVE_APPLIED", "15 days from now"):
        assert invented not in source


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_approve_endpoint_is_501_not_connected_and_nothing_is_done(client, memory) -> None:
    headers, org_id, _ = await kullanici(client, "ceo@example.com", role="owner")
    record = memory.save_debate("t", "", ["x"], _debate([ITEMS["payment_draft"]]), org_id=org_id)
    action_id = record.action_items[0].id

    resp = await client.post(f"/api/v1/actions/{action_id}/approve", headers=headers, json={})

    assert resp.status_code == 501
    body = resp.json()
    assert body["error_code"] == "action_not_connected"
    assert body["executed"] is False
    assert "hiçbir şey yapılmadı" in body["detail"]
    assert "result" not in body and "status" not in body
    assert memory.get_action_by_id(action_id).status == "pending"
