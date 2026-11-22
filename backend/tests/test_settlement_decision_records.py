"""Settlement answers leave a decision: a person's confirm / reject, and the built-in rule's auto-settle."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.open_item_match import OpenItemMatch
from app.services.decisions import DecisionError
from app.services.settlement_decisions import RULE_BY_NAME, RULE_BY_NUMBER
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.decision_helpers import decisions_of, record_fails
from tests.test_bank_reconciliation import _bank, _item, _sale, _upload

P = "/api/v1/ledger/settlements"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _proposed(client, headers) -> list[dict]:
    return (await client.get(f"{P}/proposed", headers=headers)).json()["data"]


async def _match(client, match_id: str) -> OpenItemMatch:
    async with client._maker() as db:
        return (await db.execute(select(OpenItemMatch).where(OpenItemMatch.id == match_id))).scalars().one()


async def test_a_rule_that_settles_by_invoice_number_records_itself_as_the_decider(client):
    _, org_id, _ = await kullanici(client, "kural-no@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("EFT GIB2024000000001 NOLU FATURA ODEMESI"))

    (d,) = await decisions_of(client, org_id, kind="settlement_match")
    assert (d.decided_via, d.decided_by, d.rule_id, d.outcome) == ("rule", None, RULE_BY_NUMBER, "confirmed")
    assert d.target_type == "open_item_match" and "built-in" in (d.reason or "")
    match = await _match(client, d.target_id)
    assert {r["type"] for r in d.evidence_refs} == {"open_item", "ledger_row"}
    assert {"type": "open_item", "id": match.open_item_id} in d.evidence_refs
    assert d.before["amount_cents"] == 285_000_00 and d.before["counterparty"] == "ABC Holding"
    assert d.after == {"status": "confirmed"}


async def test_the_name_and_amount_rule_has_its_own_rule_id(client):
    _, org_id, _ = await kullanici(client, "kural-isim@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN HAVALE ABC HOLDING A.S."))
    (d,) = await decisions_of(client, org_id, kind="settlement_match")
    assert (d.decided_via, d.rule_id) == ("rule", RULE_BY_NAME)


async def test_a_proposal_is_not_a_decision_until_a_person_answers(client):
    _, org_id, _ = await kullanici(client, "soru-kayit@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN EFT REF 88213"))
    assert await decisions_of(client, org_id) == []


async def test_a_failed_record_blocks_the_automatic_settlement(client, monkeypatch):
    _, org_id, _ = await kullanici(client, "kural-hata@example.com")
    await _upload(client, org_id, _sale("A"))
    record_fails(monkeypatch, "app.services.settlement_decisions")
    with pytest.raises(DecisionError):
        await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    monkeypatch.undo()
    assert (await _item(client, "A")).status == "open"
    async with client._maker() as db:
        assert (await db.execute(select(OpenItemMatch))).scalars().all() == []
    assert await decisions_of(client, org_id) == []


@pytest.mark.parametrize(("action", "outcome"), [("confirm", "confirmed"), ("reject", "rejected")])
async def test_a_person_answer_records_who_what_and_on_which_basis(client, action, outcome):
    headers, org_id, user_id = await kullanici(client, f"kisi-{action}@example.com", role="cfo")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN EFT REF 1"))
    proposal = (await _proposed(client, headers))[0]

    res = await client.post(f"{P}/{proposal['id']}/resolve", headers=headers, json={"action": action})
    assert res.status_code == 200, res.text
    (d,) = await decisions_of(client, org_id, kind="settlement_match")
    assert (d.decided_via, d.decided_by, d.rule_id, d.outcome) == ("human", user_id, None, outcome)
    assert res.json()["data"]["decision_ids"] == [d.id]
    assert d.target_id == proposal["id"] and d.org_id == org_id
    assert d.before["status"] == "proposed" and d.before["amount_cents"] == 285_000_00
    assert d.before["counterparty"] == "ABC Holding" and d.before["method"] == "amount_only"
    assert d.after == {"status": outcome, "acting_role": "cfo", "answered_as_lump": False}
    assert {r["type"] for r in d.evidence_refs} == {"open_item", "ledger_row"}


async def test_a_lump_answer_records_each_match_and_a_second_answer_adds_nothing(client):
    headers, org_id, _ = await kullanici(client, "toplu@example.com")
    await _upload(client, org_id, _sale("A", no="N1", amount=100_00), _sale("B", no="N2", amount=200_00, issued="2024-01-05"))
    await _upload(client, org_id, _bank("TOPLU ODEME ABC HOLDING", amount=300_00))
    proposal = (await _proposed(client, headers))[0]
    first = await client.post(f"{P}/{proposal['id']}/resolve", headers=headers, json={"action": "confirm"})
    assert first.status_code == 200, first.text
    records = await decisions_of(client, org_id, kind="settlement_match")
    assert len(records) == 2 and {r.after["answered_as_lump"] for r in records} == {True}
    assert sorted(r.before["amount_cents"] for r in records) == [100_00, 200_00]

    again = await client.post(f"{P}/{proposal['id']}/resolve", headers=headers, json={"action": "reject"})
    assert again.status_code == 409
    assert len(await decisions_of(client, org_id, kind="settlement_match")) == 2   # the refused answer left nothing


async def test_a_failed_record_blocks_the_answer(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "blok@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN EFT REF 1"))
    proposal = (await _proposed(client, headers))[0]
    record_fails(monkeypatch, "app.services.settlement_decisions")
    with pytest.raises(DecisionError):
        await client.post(f"{P}/{proposal['id']}/resolve", headers=headers, json={"action": "confirm"})
    monkeypatch.undo()
    assert (await _match(client, proposal["id"])).status == "proposed"
    assert (await _item(client, "A")).paid_cents == 0
    assert await decisions_of(client, org_id) == []


async def test_a_viewer_and_another_company_cannot_answer_and_leave_nothing(client):
    headers, org_id, _ = await kullanici(client, "ana@example.com")
    viewer, _, _ = await kullanici(client, "izleyici@example.com", role="viewer")
    other, other_org, _ = await kullanici(client, "diger@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN EFT REF 1"))
    pid = (await _proposed(client, headers))[0]["id"]
    assert (await client.post(f"{P}/{pid}/resolve", headers=viewer, json={"action": "confirm"})).status_code in (403, 404)
    assert (await client.post(f"{P}/{pid}/resolve", headers=other, json={"action": "confirm"})).status_code == 404
    assert await decisions_of(client, org_id) == [] and await decisions_of(client, other_org) == []


async def test_undo_is_its_own_decision_linked_to_the_one_it_takes_back(client):
    headers, org_id, user_id = await kullanici(client, "geri@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    (rule,) = await decisions_of(client, org_id, kind="settlement_match")

    res = await client.post(f"{P}/{rule.target_id}/undo", headers=headers)
    assert res.status_code == 200, res.text
    undone = [d for d in await decisions_of(client, org_id, kind="settlement_match") if d.outcome == "undone"]
    assert len(undone) == 1
    assert (undone[0].decided_by, undone[0].decided_via) == (user_id, "human")
    assert undone[0].supersedes_id == rule.id and undone[0].after["acting_role"] == "owner"
