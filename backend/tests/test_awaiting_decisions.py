"""Two queues wait for a person's decision; the radar and the briefing present them together, unmerged.

Extracted rows (`held_transactions`, /bekleyen-kayitlar) and possible-duplicate documents (/onay) used
to be two unrelated lines on the radar, and the briefing named only the rows.
"""
from __future__ import annotations

import pytest_asyncio

from app.config import get_settings
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.held_transaction import HeldTransaction
from app.services.awaiting_decisions import block, briefing_note
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_radar_held_documents import _brief, _held_pair, _other_payable, _radar


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _hold_a_row(client, org_id: str) -> None:
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="a.csv", file_type="csv", org_id=org_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        db.add(HeldTransaction(job_id=job.id, org_id=org_id, row_key="k1", payload={"description": "x", "hold_reasons": []}))
        await db.commit()


def test_the_briefing_note_names_each_queue_once() -> None:
    assert briefing_note(2, 0, False) == " Not: 2 kayıt incelemenizi bekliyor; bu rakamlara dahil değil."
    assert briefing_note(0, 3, False) == " Not: 3 belge kararınızı bekliyor; radara dahil değil."
    both = briefing_note(2, 3, False)
    assert "2 kayıt incelemenizi bekliyor" in both and "3 belge kararınızı bekliyor" in both
    assert briefing_note(2, 3, True) == briefing_note(2, 0, False)       # the headline caveat already said the documents
    assert briefing_note(0, 3, True) == "" and briefing_note(0, 0, False) == ""


def test_the_block_has_two_labelled_lines_and_is_absent_when_nothing_waits() -> None:
    assert block(0, None, "") is None

    class Held:
        count = 2
        review_path = "/onay"

    got = block(3, Held(), "Karar bekleyen 2 belge")
    assert got is not None and got.rows.count == 3 and got.rows.path == "/bekleyen-kayitlar"
    assert got.documents.count == 2 and got.documents.path == "/onay" and got.documents.text == "Karar bekleyen 2 belge"
    assert block(0, Held(), "x").rows is None and block(1, None, "").documents is None


async def test_the_radar_carries_both_queues_in_one_block(client) -> None:
    _, org_id, _ = await kullanici(client, "awaitboth@example.com")
    await _held_pair(client, org_id, due_in=2, cents=100_000)
    await _hold_a_row(client, org_id)
    radar = await _radar(client, org_id)
    block_ = radar.awaiting_decision
    assert block_.rows.count == 1 and block_.rows.text in radar.not_included
    assert block_.documents.count == 1 and block_.documents.path == "/onay" and block_.documents.text in radar.not_included


async def test_the_radar_endpoint_exposes_the_block(client) -> None:
    headers, org_id, _ = await kullanici(client, "awaitapi@example.com")
    await _hold_a_row(client, org_id)
    data = (await client.get("/api/v1/ledger/cash-radar", headers=headers)).json()["data"]
    assert data["awaiting_decision"] == {
        "rows": {"count": 1, "text": "1 kayıt incelemenizi bekliyor", "path": "/bekleyen-kayitlar"}, "documents": None,
    }


async def test_the_briefing_covers_both_when_the_documents_are_small(client) -> None:
    _, org_id, _ = await kullanici(client, "awaitbrief@example.com")
    await _other_payable(client, org_id, 5_000_000)
    await _held_pair(client, org_id, due_in=2, cents=100_000)           # 2%: not material, so no headline caveat
    await _hold_a_row(client, org_id)
    brief = await _brief(client, org_id)
    assert "Karar bekleyen" not in brief.full_text
    assert "1 kayıt incelemenizi bekliyor ve 1 belge kararınızı bekliyor; bu rakamlara dahil değil" in brief.full_text


async def test_the_briefing_does_not_repeat_documents_its_headline_already_said(client) -> None:
    _, org_id, _ = await kullanici(client, "awaitonce@example.com")
    await _held_pair(client, org_id, due_in=2, cents=100_000)           # material: the headline says it
    await _hold_a_row(client, org_id)
    brief = await _brief(client, org_id)
    assert "Karar bekleyen 1 belge" in brief.full_text
    assert brief.full_text.count("1 belge") == 1
    assert "1 kayıt incelemenizi bekliyor; bu rakamlara dahil değil" in brief.full_text
    assert get_settings().radar_held_material_ratio == 0.10


async def test_an_all_held_company_is_told_once_per_queue_and_no_document_is_counted_twice(client) -> None:
    """PR #115's all-held briefing and PR #110's rows line together: each queue named once, the radar's
    held-documents line still carries its review path, and the held-only sentence is not repeated."""
    from sqlalchemy import select as _select

    from app.models.open_item import OpenItem
    from tests.test_g23_followups import _upload as g23_upload

    _, org_id, _ = await kullanici(client, "allheld@example.com")
    await g23_upload(client, org_id, who="Alfa Gıda", cents=100_000)
    await g23_upload(client, org_id, who="Alfa Gıdacılık", cents=100_000)
    async with client._maker() as db:
        for item in (await db.execute(_select(OpenItem).where(OpenItem.org_id == org_id))).scalars():
            await db.delete(item)
        await db.commit()
    await _hold_a_row(client, org_id)
    brief = await _brief(client, org_id)
    assert brief.has_data is True and "kararınızı bekliyor; radar bunlar olmadan boş" in brief.sentence_radar
    assert brief.full_text.count("1 belge") == 1                       # the document is said once
    assert "1 kayıt incelemenizi bekliyor; bu rakamlara dahil değil" in brief.full_text
    radar = await _radar(client, org_id)
    assert radar.held_documents.review_path == "/onay" and radar.awaiting_decision.documents.path == "/onay"
