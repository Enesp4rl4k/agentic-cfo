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
    assert asked[0]["options"] == ["mixed", "only_expense", "only_income"]
    assert [c["role"] for c in asked[0]["question"]["columns"]][:3] == ["date", "description", "amount"]
    assert asked[0]["question"]["samples"][0]["amount"] == "1500"
    rows = (await client.get("/api/v1/held-rows", headers=headers)).json()["data"]["rows"]
    assert {r["reason_labels"][0] for r in rows} == {"yön belirsiz"} and all(r["type"] is None for r in rows)

    res = await client.post("/api/v1/held-rows/file-direction", headers=headers, json={
        "job_id": job_id, "file_key": asked[0]["file_key"], "answer": "only_expense",
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
    assert len(file_answer) == 1 and file_answer[0].outcome == "only_expense"
    assert file_answer[0].before["rows"] == 2 and file_answer[0].after["remembered"] is False
    assert await _questions(client, headers) == []


def _bank(*rows: str, title: str = "AKBANK Hesap No: 1234567", header: str = "Tarih;Açıklama;Borç;Alacak;Para Birimi") -> str:
    return NL.join([title, header, *rows]) + NL


ACCOUNT_1 = _bank("01.03.2026;Kira;1.500,00;;TRY", "02.03.2026;Satış;;4.000,00;TRY")
ACCOUNT_2 = _bank("09.03.2026;Su;75,00;;TRY", "10.03.2026;Tahsilat;;300,00;TRY")


async def test_a_debit_credit_file_is_asked_first_and_the_answer_is_remembered_for_that_account(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f2@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=ACCOUNT_1, name="a.csv")
    assert await _transactions(client, job_id) == []                       # the first upload books nothing unasked
    asked = (await _questions(client, headers))[0]
    assert asked["reason"] == "convention_unverified" and asked["options"] == ["as_read", "inverted", "mixed"]
    assert asked["question"]["mapping"] == [{"label": "Borç", "means": "expense"}, {"label": "Alacak", "means": "income"}]
    assert asked["question"]["samples"][0]["description"] == "Kira"
    res = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                            json={"job_id": job_id, "file_key": asked["file_key"], "answer": "inverted"})
    assert res.json()["data"]["remembered"] and res.json()["data"]["resolved"] == 2
    assert sorted((t.type, t.amount_kurus) for t in await _transactions(client, job_id)) == [
        ("expense", 400000), ("income", 150000)]                          # the bank's view: Borç is money in

    mappings = (await client.get("/api/v1/held-rows/direction-mappings", headers=headers)).json()["data"]["mappings"]
    assert len(mappings) == 1 and mappings[0]["answer"] == "inverted"

    # the same account's next statement is not asked again, and is read the same way
    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=ACCOUNT_2, name="b.csv")
    assert await _questions(client, headers) == []
    assert sorted((t.type, t.amount_kurus) for t in await _transactions(client, job2)) == [
        ("expense", 30000), ("income", 7500)]

    # another account of the same bank, and a file that names no account at all, are asked: the memory is
    # specific, and without an identity it can never be checked
    job3, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, name="c.csv",
                            content=_bank("11.03.2026;Gaz;40,00;;TRY", title="AKBANK Hesap No: 7654321"))
    job4, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, name="d.csv",
                            content=_bank("12.03.2026;Gaz;40,00;;TRY", title="Hesap hareketleri"))
    assert {q["job_id"] for q in await _questions(client, headers)} == {job3, job4}

    # another organisation with the identical file is asked: the memory is per organisation
    headers2, org2, _ = await kullanici(client, "f2b@x.com")
    await _upload(client, tmp_path, monkeypatch, [], org2, content=ACCOUNT_2, name="e.csv")
    assert len(await _questions(client, headers2)) == 1
    assert (await client.delete(f"/api/v1/held-rows/direction-mappings/{mappings[0]['id']}", headers=headers2)).status_code == 404

    # revoke: that account is asked again, and the revocation is a decision
    assert (await client.delete(f"/api/v1/held-rows/direction-mappings/{mappings[0]['id']}", headers=headers)).status_code == 200
    await _upload(client, tmp_path, monkeypatch, [], org_id, name="f.csv",
                  content=_bank("13.03.2026;Gaz;40,00;;TRY"))
    assert len(await _questions(client, headers)) == 3
    assert sorted(d.outcome for d in await _decisions(client, DecisionKind.DIRECTION_MAPPING)) == ["remembered", "revoked"]
    async with client._maker() as db:      # revoked, never deleted: the decision that made it still has its subject
        assert (await db.execute(select(DirectionMapping).where(DirectionMapping.revoked_at.is_not(None)))).scalars().first()


async def test_a_no_signal_answer_is_never_remembered(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "f2n@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=FIRST, name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]
    res = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                            json={"job_id": job_id, "file_key": key, "answer": "only_expense", "remember": True})
    assert res.json()["data"]["remembered"] is None
    assert (await client.get("/api/v1/held-rows/direction-mappings", headers=headers)).json()["data"]["mappings"] == []
    await _upload(client, tmp_path, monkeypatch, [], org_id, content=SECOND, name="b.csv")
    assert len(await _questions(client, headers)) == 1                      # asked again: most statements are mixed


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
                            json={"job_id": job_id, "file_key": key, "answer": "only_expense", "remember": False})
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
    content = NL.join(["Tarih;Açıklama;Tutar", "01.03.2026;Kira;-1.500,00", "02.03.2026;Satış;250,00"]) + NL
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
        assert len(pending) == 2 and pending[0].payload.get("currency") is None   # and the row was not half-filled
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


# ── who may set a standing rule, and a memory that no longer fits ────────────

async def test_only_a_decider_or_the_accountant_remembers_or_forgets_a_mapping(env, monkeypatch):
    client, tmp_path = env
    cfo, org_id, _ = await kullanici(client, "r1@x.com", role="cfo")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=ACCOUNT_1, name="a.csv")
    listing = (await client.get("/api/v1/held-rows/file-questions", headers=cfo)).json()["data"]
    assert listing["can_remember"] is False
    key = listing["files"][0]["file_key"]
    res = await client.post("/api/v1/held-rows/file-direction", headers=cfo,
                            json={"job_id": job_id, "file_key": key, "answer": "as_read", "remember": True})
    data = res.json()["data"]
    assert data["resolved"] == 2 and data["remembered"] is None and data["remember_refused"] is True   # answering for the file is fine
    assert (await client.get("/api/v1/held-rows/direction-mappings", headers=cfo)).json()["data"]["mappings"] == []

    owner_headers, owner_org, _ = await kullanici(client, "r2@x.com", role="owner")
    job2, _ = await _upload(client, tmp_path, monkeypatch, [], owner_org, content=ACCOUNT_1, name="b.csv")
    listing = (await client.get("/api/v1/held-rows/file-questions", headers=owner_headers)).json()["data"]
    assert listing["can_remember"] is True
    await client.post("/api/v1/held-rows/file-direction", headers=owner_headers, json={
        "job_id": job2, "file_key": listing["files"][0]["file_key"], "answer": "as_read", "remember": True})
    mapping = (await client.get("/api/v1/held-rows/direction-mappings", headers=owner_headers)).json()["data"]["mappings"][0]

    # once the same person is only a writer (cfo), the mapping cannot be forgotten; as owner again it can
    from app.models.organization import OrgMembership
    from app.models.user import User

    async def become(role: str) -> None:
        async with client._maker() as db:
            user = (await db.execute(select(User).where(User.email == "r2@x.com"))).scalar_one()
            user.role = role
            for m in (await db.execute(select(OrgMembership).where(OrgMembership.user_id == user.id))).scalars():
                m.role = role
            await db.commit()
        from app.api.auth import _cache_invalidate

        _cache_invalidate(str(user.id))      # the user lookup is cached for a minute

    await become("cfo")
    assert (await client.delete(f"/api/v1/held-rows/direction-mappings/{mapping['id']}", headers=owner_headers)).status_code == 403
    await become("smmm")
    assert (await client.delete(f"/api/v1/held-rows/direction-mappings/{mapping['id']}", headers=owner_headers)).status_code == 200


async def test_a_remembered_reading_is_not_applied_when_the_new_files_balance_contradicts_it(env, monkeypatch):
    from app.models.direction_mapping import DirectionMapping as Mapping
    from app.parsers.direction import header_signature, statement_identity

    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "o1@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=ACCOUNT_1, name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]
    await client.post("/api/v1/held-rows/file-direction", headers=headers,
                      json={"job_id": job_id, "file_key": key, "answer": "as_read"})        # remembered: customer's view

    balance_header = "Tarih;Açıklama;Borç;Alacak;Bakiye;Para Birimi"
    contradicting = _bank(
        "01.03.2026;Satış;3.000,00;;13.000,00;TRY", "02.03.2026;Kira;;1.200,00;11.800,00;TRY",
        "03.03.2026;Satış;2.000,00;;13.800,00;TRY", header=balance_header)
    # the header words differ from the remembered file's, so this exercises the memory lookup directly too
    async with client._maker() as db:
        db.add(Mapping(org_id=org_id, signature=header_signature(
            ["tarih", "aciklama", "borc", "alacak", "bakiye", "para birimi"], statement_identity("AKBANK Hesap No: 1234567")),
            reason="convention_unverified", answer="as_read", columns="x"))
        await db.commit()
    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=contradicting, name="b.csv")
    asked = [q for q in await _questions(client, headers) if q["job_id"] == job2]
    assert len(asked) == 1 and asked[0]["reason"] == "balance_contradicts"           # held and asked again
    assert await _transactions(client, job2) == []
    assert [d.outcome for d in await _decisions(client, DecisionKind.DIRECTION_MAPPING) if d.outcome == "overridden"] == ["overridden"]


# ── round 4: the counts reach the user, and a sign memory is checked ─────────────────────────────────────────

SIGN_HEADER = "Tarih;Açıklama;Tutar;Bakiye;Para Birimi"


def _signs(*rows: str, title: str = "AKBANK Hesap No: 1234567") -> str:
    return NL.join([title, SIGN_HEADER, *rows]) + NL


def _mostly_out(positives: int) -> str:
    out = [f"{d:02d}.03.2026;Ödeme {d};-{d},00;;TRY" for d in range(1, 21)]
    return _signs(*out, *[f"{20 + d}.03.2026;Tahsilat {d};{d * 10},00;;TRY" for d in range(1, positives + 1)])


async def test_the_upload_result_says_where_every_row_went(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "c1@x.com")
    content = NL.join([
        "Tarih;Açıklama;Tutar;Bakiye;Para Birimi",
        ";Devreden Bakiye;;10.000,00;TRY",
        "02.03.2026;Kira;-400,00;9.600,00;TRY",
        "03.03.2026;Satış;1.000,00;10.600,00;TRY",
        "04.03.2026;Toplam fatura ödemesi;-250,00;10.350,00;TRY",
        ";Genel Toplam;;10.350,00;TRY",
    ]) + NL
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=content, name="a.csv")
    ingest = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]["ingest"]
    assert ingest["rows_read"] == 5 and ingest["processed"] == 3 and ingest["held"] == 0 and ingest["summary_lines_skipped"] == 2
    assert "5 satır okundu: 3 kaydedildi, 0 kararınızı bekliyor, 2 özet satırı atlandı" in ingest["summary"]
    assert [x["description"] for x in ingest["skipped_lines"]] == ["Devreden Bakiye", "Genel Toplam"]
    assert ingest["unaccounted"] == 0
    assert "Toplam fatura ödemesi" in {t.description for t in await _transactions(client, job_id)}


async def test_a_remembered_sign_answer_does_not_apply_to_a_file_with_no_negatives_or_a_contradicting_balance(env, monkeypatch):
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "c2@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_mostly_out(2), name="a.csv")
    asked = (await _questions(client, headers))[0]
    assert asked["reason"] == "sign_unconfirmed" and asked["options"] == ["mixed", "sign_correct"]
    done = await client.post("/api/v1/held-rows/file-direction", headers=headers,
                             json={"job_id": job_id, "file_key": asked["file_key"], "answer": "sign_correct"})
    assert done.json()["data"]["remembered"] and done.json()["data"]["resolved"] == 22

    # the same format and account, now a file whose amounts carry no negative sign at all: the memory is for the sign
    positives = _signs(*[f"{d:02d}.05.2026;Gider {d};{d},00;;TRY" for d in range(1, 8)])
    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=positives, name="b.csv")
    assert await _transactions(client, job2) == []
    assert [q["reason"] for q in await _questions(client, headers) if q["job_id"] == job2] == ["no_signal"]

    # and a file of the same format whose balance says the signs are backwards: asked, the override recorded
    balance, lines = 10_000, []
    for d in range(1, 7):
        balance += d * 10                       # the balance goes UP by every amount written as negative
        lines.append(f"{d:02d}.04.2026;Ödeme {d};-{d * 10},00;{balance},00;TRY")
    lines.append(f"07.04.2026;Tahsilat;70,00;{balance - 70},00;TRY")
    lines.append(f"08.04.2026;Tahsilat;80,00;{balance - 150},00;TRY")
    job3, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_signs(*lines), name="c.csv")
    asked3 = [q for q in await _questions(client, headers) if q["job_id"] == job3]
    assert [q["reason"] for q in asked3] == ["balance_contradicts"] and await _transactions(client, job3) == []
    assert [d.outcome for d in await _decisions(client, DecisionKind.DIRECTION_MAPPING) if d.outcome == "overridden"] == ["overridden"]
