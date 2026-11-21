"""G23 follow-ups from the review of #107: nothing vanishes, a human decides what the machine cannot.

(a) same number + amount, a different name, is held; (b) one invoice read under an ETTN and under a
free-form number is held; (c) the overflow of a key's versions is held and listed; (d) revoking an
alias restores the aliases it re-pointed; (e) an organisation whose every document is held still gets
a briefing that says so.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.core.invoice_identity import party_token
from app.models.counterparty_alias import CounterpartyAlias
from app.models.open_item import OpenItem
from app.models.user import User
from app.services.duplicate_resolution import confirm_alias, revoke_alias
from app.services.ledger_documents import MAX_VARIANTS, load_aliases
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_alias_flow import _row
from tests.test_duplicate_resolution_radar import SHORT, _radar_out, _rows, _upload
from tests.test_radar_held_documents import _brief, _radar

UUID = "F47AC10B-58CC-4372-A567-0E02B2C3D479"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _listed(client, headers):
    return (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]


# -- (a) ------------------------------------------------------------------------------------

async def test_a_longer_form_of_the_name_or_a_typo_is_held_with_its_own_reason(client):
    for n, (first, second) in enumerate([("Alfa Gıda", "Alfa Gıdacılık"), ("Alfa Gıda", "Alfa Gdıa")]):
        headers, org_id, _ = await kullanici(client, f"g23a{n}@example.com")
        await _upload(client, org_id, who=first)
        _, counts = await _upload(client, org_id, who=second)
        assert (counts["new"], counts["possible_duplicate"]) == (0, 1)
        assert await _radar_out(client, org_id) == 100_000                     # the payable is counted once
        (row,) = await _listed(client, headers)
        assert row["reason"] == "same_number_different_name"
        assert row["reason_text"] == "aynı numara ve tutar, farklı unvan"
        radar = await _radar(client, org_id)
        assert radar.held_documents is not None
        assert radar.held_documents.by_reason == {"same_number_different_name": 1}
        assert any("aynı numara ve tutar, farklı unvan: 1" in line for line in radar.not_included)


async def test_the_same_number_with_another_amount_is_still_a_separate_invoice(client):
    _, org_id, _ = await kullanici(client, "g23a-amount@example.com")
    await _upload(client, org_id, who="Alfa Gıda", cents=100_000)
    _, counts = await _upload(client, org_id, who="Zeta Tekstil", cents=250_000)
    assert (counts["new"], counts["possible_duplicate"]) == (1, 0)


# -- (b) ------------------------------------------------------------------------------------

async def test_one_invoice_read_under_an_ettn_and_a_free_form_number_is_held(client):
    headers, org_id, _ = await kullanici(client, "g23b@example.com")
    await _upload(client, org_id, number=UUID, who="Alfa Gıda A.Ş.")
    _, counts = await _upload(client, org_id, number="A-1", who="Alfa Gıda A.Ş.")
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)
    assert await _radar_out(client, org_id) == 100_000
    (row,) = await _listed(client, headers)
    assert row["reason"] == "same_document_different_id"


async def test_the_mixed_pair_needs_the_same_counterparty_amount_and_date(client):
    _, org_id, _ = await kullanici(client, "g23b-neg@example.com")
    await _upload(client, org_id, number=UUID, who="Alfa Gıda A.Ş.")
    _, other_party = await _upload(client, org_id, number="A-1", who="Beta Tekstil A.Ş.")
    _, other_amount = await _upload(client, org_id, number="A-2", who="Alfa Gıda A.Ş.", cents=130_000)
    _, far = await _upload(client, org_id, number="A-3", who="Alfa Gıda A.Ş.", days_ago=20)
    for counts in (other_party, other_amount, far):
        assert (counts["new"], counts["possible_duplicate"]) == (1, 0)


async def test_two_ettn_invoices_or_two_numbered_ones_are_never_paired_on_amount_and_date(client):
    _, org_id, _ = await kullanici(client, "g23b-two@example.com")
    _, org_two, _ = await kullanici(client, "g23b-two2@example.com")
    await _upload(client, org_id, number=UUID, who="Alfa Gıda A.Ş.")
    _, a = await _upload(client, org_id, number="E47AC10B-58CC-4372-A567-0E02B2C3D479", who="Alfa Gıda A.Ş.")
    await _upload(client, org_two, number="N-1", who="Alfa Gıda A.Ş.")
    _, b = await _upload(client, org_two, number="N-2", who="Alfa Gıda A.Ş.")
    assert a["possible_duplicate"] == 0 and b["possible_duplicate"] == 0


# -- (c) ------------------------------------------------------------------------------------

async def test_the_overflow_of_a_keys_versions_is_held_listed_and_never_merged(client):
    headers, org_id, _ = await kullanici(client, "g23c@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    amounts = [110_000 + i * 10_000 for i in range(MAX_VARIANTS)] + [333_333]
    for cents in amounts:
        await _upload(client, org_id, who=SHORT, cents=cents)
    rows = await _rows(client, org_id)
    assert len(rows) == 1 + len(amounts)
    assert sum(r.amount_cents for r in rows if r.ledger_status == "possible_duplicate") == sum(amounts)
    assert 333_333 in {r.amount_cents for r in rows}                           # its amount did not vanish
    listed = await _listed(client, headers)
    assert len(listed) == len(amounts) and {x["reason"] for x in listed} == {"many_versions"}
    held = (await _radar(client, org_id)).held_documents
    assert held is not None and held.count == len(amounts)
    assert held.by_reason == {"many_versions": len(amounts)}
    assert held.payable_cents == sum(amounts)
    assert await _radar_out(client, org_id) == 100_000                          # only the first counts


# -- (d) ------------------------------------------------------------------------------------

async def test_revoking_b_to_c_gives_a_its_original_target_back(client):
    _, org_id, user_id = await kullanici(client, "g23d@example.com")
    names = ("Alfa Gıda A.Ş.", "Beta Tekstil A.Ş.", "Gamma Metal A.Ş.")
    a, b, c = (party_token(org_id, n) for n in names)
    kept, held = _row(org_id, names[2]), _row(org_id, names[1])
    held.ledger_status, held.duplicate_of = "excluded", kept.id
    async with client._maker() as db:
        db.add_all([kept, held, CounterpartyAlias(org_id=org_id, alias_token=a, canonical_token=b)])
        await db.commit()
    async with client._maker() as db:
        user = await db.get(User, user_id)
        row = await db.get(type(held), held.id)
        out = await confirm_alias(db, user=user, row=row)            # B -> C re-points A -> B to A -> C
        await db.commit()
        assert await load_aliases(db, org_id) == {a: c, b: c}
        beta_to_gamma = await db.get(CounterpartyAlias, out["alias"]["id"])
        res = await revoke_alias(db, user=user, alias=beta_to_gamma)
        await db.commit()
        assert res["restored_aliases"]
        assert await load_aliases(db, org_id) == {a: b}              # A reads as B again; B is its own supplier


# -- (e) ------------------------------------------------------------------------------------

async def test_a_company_whose_every_document_is_held_gets_a_briefing_that_says_so(client):
    _, org_id, _ = await kullanici(client, "g23e@example.com")
    await _upload(client, org_id, who="Alfa Gıda", cents=100_000)
    await _upload(client, org_id, who="Alfa Gıdacılık", cents=100_000)
    async with client._maker() as db:                                           # only the held row remains
        for item in (await db.execute(select(OpenItem).where(OpenItem.org_id == org_id))).scalars():
            await db.delete(item)
        await db.commit()
    brief = await _brief(client, org_id)
    assert brief.has_data is True
    assert "kararınızı bekliyor; radar bunlar olmadan boş" in brief.sentence_radar
    assert "1 belge" in brief.sentence_radar
