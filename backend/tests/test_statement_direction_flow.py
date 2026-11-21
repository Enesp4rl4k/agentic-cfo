# ruff: noqa: F811
"""A statement file nobody could place: one question for the file, one answer, remembered and revocable.

Also the review of PR #110: the confirmation of the company currency is one transaction, a generic
PATCH cannot change it, a correction is validated, ids of another organisation are 404.
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision, DecisionKind
from app.models.direction_mapping import DirectionMapping
from app.models.held_transaction import HeldTransaction
from app.models.organization import Organization
from app.models.transaction import Transaction
from tests.api_helpers import kullanici
from tests.test_ingest_no_silent_defaults import (  # noqa: F401  (a fixture, reused below)
    NL,
    _upload,
    ortam,
)

pytestmark = pytest.mark.real_currency

@pytest_asyncio.fixture
async def env(ortam):  # the shared in-memory client of the ingest tests
    yield ortam


HEADER = "Tarih;Açıklama;Tutar;Para Birimi"


def _statement(*rows: str, header: str = HEADER) -> str:
    return NL.join([header, *rows]) + NL


FIRST = _statement("01.03.2026;Kira;1.500,00;TRY", "02.03.2026;Elektrik;250,00;TRY")
SECOND = _statement("09.03.2026;Su;75,00;TRY", "10.03.2026;İnternet;300,00;TRY")


async def _questions(client, headers) -> list[dict[str, Any]]:
    return (await client.get("/api/v1/held-rows/file-questions", headers=headers)).json()["data"]["files"]


async def _transactions(client, job_id: str) -> list[Transaction]:
    async with client._maker() as db:
        return list((await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars())


async def _decisions(client, kind: DecisionKind) -> list[Decision]:
    async with client._maker() as db:
        return list((await db.execute(select(Decision).where(Decision.kind == kind.value))).scalars())


async def test_an_unplaceable_file_is_one_question_and_the_answer_applies_to_every_row(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f1@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=FIRST, name="ekstre.csv")

    assert await _transactions(client, job_id) == []                       # nothing booked as income
    asked = await _questions(client, headers)
    assert len(asked) == 1 and asked[0]["rows"] == 2 and asked[0]["reason"] == "no_signal"
    assert asked[0]["options"] == ["all_expense", "all_income", "mixed"]
    assert [c["role"] for c in asked[0]["question"]["columns"]][:3] == ["date", "description", "amount"]
    assert asked[0]["question"]["samples"][0]["amount"] == "1500"
    rows = (await client.get("/api/v1/held-rows", headers=headers)).json()["data"]["rows"]
    assert {r["reason_labels"][0] for r in rows} == {"yön belirsiz"} and all(r["type"] is None for r in rows)

    res = await client.post("/api/v1/held-rows/file-direction", headers=headers, json={
        "job_id": job_id, "file_key": asked[0]["file_key"], "answer": "all_expense",
    })
    data = res.json()["data"]
    assert res.status_code == 200 and data["resolved"] == 2 and data["still_waiting"] == 0
    booked = await _transactions(client, job_id)
    assert sorted((t.type, t.amount_kurus, t.currency) for t in booked) == [("expense", 25000, "TRY"), ("expense", 150000, "TRY")]
    assert all(t.category for t in booked)
    # every row's change and the file's answer are recorded
    per_row = await _decisions(client, DecisionKind.HELD_ROW_RESOLUTION)
    assert len(per_row) == 2 and {d.outcome for d in per_row} == {"corrected_released"}
    assert (per_row[0].before["type"], per_row[0].after["type"]) == (None, "expense")
    file_answer = await _decisions(client, DecisionKind.FILE_DIRECTION_ANSWER)
    assert len(file_answer) == 1 and file_answer[0].outcome == "all_expense"
    assert file_answer[0].before["rows"] == 2 and file_answer[0].after["remembered"] is True
    assert await _questions(client, headers) == []


async def test_the_answer_is_remembered_for_the_same_format_and_revocable(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f2@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=FIRST, name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]
    await client.post("/api/v1/held-rows/file-direction", headers=headers,
                      json={"job_id": job_id, "file_key": key, "answer": "all_expense"})

    mappings = (await client.get("/api/v1/held-rows/direction-mappings", headers=headers)).json()["data"]["mappings"]
    assert len(mappings) == 1 and mappings[0]["answer"] == "all_expense" and "Tutar" in mappings[0]["columns"].title()

    # the next upload of that bank's format is not asked again
    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=SECOND, name="b.csv")
    assert await _questions(client, headers) == []
    assert sorted(t.type for t in await _transactions(client, job2)) == ["expense", "expense"]

    # another organisation's identical format is asked: the memory is per organisation
    headers2, org2, _ = await kullanici(client, "f2b@x.com")
    await _upload(client, tmp_path, monkeypatch, [], org2, content=SECOND, name="c.csv")
    assert len(await _questions(client, headers2)) == 1
    assert (await client.get("/api/v1/held-rows/direction-mappings", headers=headers2)).json()["data"]["mappings"] == []
    gone = await client.delete(f"/api/v1/held-rows/direction-mappings/{mappings[0]['id']}", headers=headers2)
    assert gone.status_code == 404                                              # not theirs

    # revoke: the format is asked again, and the revocation is a decision
    assert (await client.delete(f"/api/v1/held-rows/direction-mappings/{mappings[0]['id']}", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/held-rows/direction-mappings", headers=headers)).json()["data"]["mappings"] == []
    await _upload(client, tmp_path, monkeypatch, [], org_id, content=_statement("11.03.2026;Gaz;40,00;TRY"), name="d.csv")
    assert len(await _questions(client, headers)) == 1
    outcomes = sorted(d.outcome for d in await _decisions(client, DecisionKind.DIRECTION_MAPPING))
    assert outcomes == ["remembered", "revoked"]
    async with client._maker() as db:      # revoked, never deleted: the decision that made it still has its subject
        assert (await db.execute(select(DirectionMapping).where(DirectionMapping.revoked_at.is_not(None)))).scalars().first()


async def test_not_remembering_asks_again_and_mixed_leaves_the_rows_to_be_decided_one_by_one(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f3@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=FIRST, name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]
    bad = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                            json={"job_id": job_id, "file_key": key, "answer": "balance"})
    assert bad.status_code == 422                                       # not an option for this file
    unknown = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                                json={"job_id": job_id, "file_key": "nope", "answer": "mixed"})
    assert unknown.status_code == 404
    done = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                             json={"job_id": job_id, "file_key": key, "answer": "mixed", "remember": True})
    assert done.json()["data"]["resolved"] == 0 and done.json()["data"]["remembered"] is None
    rows = (await client.get("/api/v1/held-rows", headers=headers)).json()["data"]["rows"]
    assert len(rows) == 2 and all(r["reasons"] == ["direction_unknown"] and r["direction_file"] is None for r in rows)
    assert await _questions(client, headers) == []
    # each can then be answered on its own, as before
    res = await client.post("/api/v1/held-rows/release", headers=headers, json={
        "corrections": {rows[0]["id"]: {"type": "expense"}, rows[1]["id"]: {"type": "income"}},
    })
    assert res.json()["data"]["resolved"] == 2
    assert sorted(t.type for t in await _transactions(client, job_id)) == ["expense", "income"]


async def test_a_balance_contradiction_is_asked_once_and_the_balance_answer_books_the_file(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f4@x.com")
    text = NL.join([
        "Tarih;Açıklama;Borç;Alacak;Bakiye;Para Birimi",
        "01.03.2026;Satış;3.000,00;;13.000,00;TRY",
        "02.03.2026;Kira;;1.200,00;11.800,00;TRY",
        "03.03.2026;Satış;2.000,00;;13.800,00;TRY",
    ]) + NL
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=text, name="banka.csv")
    asked = (await _questions(client, headers))[0]
    assert asked["reason"] == "balance_contradicts" and asked["options"] == ["as_read", "balance", "mixed"]
    res = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                            json={"job_id": job_id, "file_key": asked["file_key"], "answer": "balance"})
    assert res.json()["data"]["resolved"] == 3
    assert sorted((t.type, t.amount_kurus) for t in await _transactions(client, job_id)) == [
        ("expense", 120000), ("income", 200000), ("income", 300000)]


async def test_rows_that_keep_waiting_for_another_reason_record_the_change(env, monkeypatch):
    """The file is answered, but its rows still lack a currency: the answer is stored and recorded, not lost."""
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f5@x.com")
    content = NL.join(["Tarih;Açıklama;Tutar", "01.03.2026;Kira;1.500,00", "02.03.2026;Elektrik;250,00"]) + NL
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=content, name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]
    res = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                            json={"job_id": job_id, "file_key": key, "answer": "all_expense", "remember": False})
    assert res.json()["data"]["resolved"] == 0 and res.json()["data"]["still_waiting"] == 2
    rows = (await client.get("/api/v1/held-rows", headers=headers)).json()["data"]["rows"]
    assert all(r["type"] == "expense" and r["reasons"] == ["currency_unknown"] for r in rows)
    updated = [d for d in await _decisions(client, DecisionKind.HELD_ROW_RESOLUTION) if d.outcome == "updated"]
    assert len(updated) == 2 and updated[0].before["type"] is None and updated[0].after["type"] == "expense"

    # confirming the company currency now releases them, in one transaction, each change recorded
    res = await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "try"})
    assert res.json()["data"]["released"]["resolved"] == 2
    booked = await _transactions(client, job_id)
    assert {(t.type, t.currency, t.currency_assumed) for t in booked} == {("expense", "TRY", True)}


# ── review of PR #110, items 3 to 6 ──────────────────────────────────────────

async def test_the_generic_patch_cannot_change_the_company_currency(env):
    client, _ = env
    headers, org_id, _ = await kullanici(client, "p1@x.com")
    same = await client.patch("/api/v1/org/me", headers=headers, json={"base_currency": "usd", "locale": "en-US"})
    assert same.status_code == 200                                        # the form that always sends it still saves
    other = await client.patch("/api/v1/org/me", headers=headers, json={"base_currency": "EUR"})
    assert other.status_code == 422 and "base-currency" in other.text
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        assert org.base_currency == "USD" and org.base_currency_confirmed_at is None
    assert await _decisions(client, DecisionKind.BASE_CURRENCY_CONFIRMATION) == []

    done = await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "EUR"})
    assert done.status_code == 200
    decision = (await _decisions(client, DecisionKind.BASE_CURRENCY_CONFIRMATION))[0]
    assert decision.before == {"currency": "USD", "confirmed": False} and decision.after == {"currency": "EUR", "confirmed": True}
    assert (await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "ZZZ"})).status_code == 422


async def test_rows_assumed_under_the_old_currency_are_listed_not_rewritten(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "p2@x.com")
    content = NL.join(["Tarih;Açıklama;Tutar", "01.03.2026;Kira;-1.500,00", "02.03.2026;Satış;250,00"]) + NL
    await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "TRY"})
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=content, name="a.csv")
    assert {(t.currency, t.currency_assumed) for t in await _transactions(client, job_id)} == {("TRY", True)}
    changed = await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "EUR"})
    review = changed.json()["data"]["assumed_for_review"]
    assert review["count"] == 2 and review["by_currency"] == {"TRY": 2}
    assert {(t.currency, t.currency_assumed) for t in await _transactions(client, job_id)} == {("TRY", True)}


async def test_confirmation_is_one_transaction(env, monkeypatch):
    from app.services import held_rows

    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "t1@x.com")
    content = NL.join(["Tarih;Açıklama;Tutar", "01.03.2026;Kira;-1.500,00"]) + NL
    await _upload(client, tmp_path, monkeypatch, [], org_id, content=content, name="a.csv")

    async def boom(*a: Any, **k: Any):
        raise RuntimeError("the rows could not be released")

    monkeypatch.setattr(held_rows, "resolve_uncommitted", boom)
    with pytest.raises(RuntimeError):
        await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "TRY"})
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        assert org.base_currency_confirmed_at is None                         # the confirmation did not survive
        pending = (await db.execute(select(HeldTransaction).where(HeldTransaction.status == "pending"))).scalars().all()
        assert len(pending) == 1 and pending[0].payload.get("currency") is None   # and the row was not half-filled
    assert await _decisions(client, DecisionKind.BASE_CURRENCY_CONFIRMATION) == []


async def test_correct_and_accept_validates_the_correction(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "c1@x.com")
    content = NL.join(["Tarih;Açıklama;Tutar;Para Birimi", "01.03.2026;Kira;100,00;TRY"]) + NL
    await _upload(client, tmp_path, monkeypatch, [], org_id, content=content, name="a.csv")
    row = (await client.get("/api/v1/held-rows", headers=headers)).json()["data"]["rows"][0]

    async def attempt(fix: dict[str, Any]) -> int:
        res = await client.post("/api/v1/held-rows/release", headers=headers,
                                json={"ids": [row["id"]], "corrections": {row["id"]: {"type": "expense", **fix}}})
        return res.status_code

    assert await attempt({"amount_cents": -500}) == 422                     # a negative amount: the direction is the type
    assert await attempt({"amount_cents": 0}) == 422
    assert await attempt({"transaction_date": "1970-01-01"}) == 422
    assert await attempt({"transaction_date": "2999-01-01"}) == 422
    assert await attempt({"currency": "ZZZ"}) == 422
    assert (await client.get("/api/v1/held-rows", headers=headers)).json()["data"]["count"] == 1   # nothing was written
    assert await attempt({"amount_cents": 12345, "currency": "usd", "transaction_date": "2026-03-01"}) == 200
    booked = (await _transactions(client, row["job_id"]))[0]
    assert (booked.amount_kurus, booked.currency, booked.currency_assumed) == (12345, "USD", False)


def test_a_corrected_currency_clears_the_assumed_flag():
    from app.services.held_rows import apply_corrections

    payload = {"currency": "TRY", "currency_assumed": True, "hold_reasons": ["confidence_low"], "type": "expense"}
    assert "currency_assumed" not in apply_corrections(payload, {"currency": "USD"})
    assert apply_corrections(payload, {})["currency_assumed"] is True


async def test_another_organisations_ids_and_the_read_guard(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "g1@x.com")
    other, _, _ = await kullanici(client, "g2@x.com")
    orphan, _, _ = await kullanici(client, "g3@x.com", attach_org=False)
    content = NL.join(["Tarih;Açıklama;Tutar", "01.03.2026;Kira;100,00"]) + NL
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=content, name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]

    assert (await client.get("/api/v1/held-rows", headers=orphan)).status_code == 400   # nothing to read without an organisation
    assert (await client.get("/api/v1/held-rows/file-questions", headers=orphan)).status_code == 400
    assert await _questions(client, other) == []                                       # another organisation's file is invisible
    res = await client.post("/api/v1/held-rows/file-direction", headers=other,
                            json={"job_id": job_id, "file_key": key, "answer": "mixed"})
    assert res.status_code == 404
