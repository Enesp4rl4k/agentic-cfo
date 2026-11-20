"""G6 — one bank transfer that pays several invoices of one customer.

Small companies pay (and get paid) in lumps. The amounts are written by hand.
The rule under test: a lump is only ever a *proposal*, never an automatic
settlement, and only when the answer is unambiguous.
"""

from __future__ import annotations

import pytest_asyncio

from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_bank_reconciliation import _bank, _item, _sale, _summary, _upload


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _proposed(client, headers) -> list[dict]:
    return (await client.get("/api/v1/ledger/settlements/proposed", headers=headers)).json()["data"]


async def test_a_lump_paying_two_invoices_is_one_proposal_and_settles_nothing_alone(client):
    headers, org_id, _ = await kullanici(client, "toplu1@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=185_000_00, no="N2", issued="2024-01-05", due="2024-02-05"),
    )
    counts = await _upload(client, org_id, _bank("HAVALE ABC HOLDING", amount=285_000_00))

    assert (counts["settled"], counts["proposed"]) == (0, 1)
    assert {(await _item(client, "A")).status, (await _item(client, "B")).status} == {"open"}
    proposals = await _proposed(client, headers)
    assert len(proposals) == 1
    assert sorted(i["amount_cents"] for i in proposals[0]["items"]) == [100_000_00, 185_000_00]
    # Until a person answers, the lump is not revenue on top of the invoices.
    assert (await _summary(client, org_id))["revenue_cents"] == 285_000_00


async def test_confirming_the_lump_settles_every_invoice_in_it(client):
    headers, org_id, _ = await kullanici(client, "toplu2@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=185_000_00, no="N2", issued="2024-01-05", due="2024-02-05"),
    )
    await _upload(client, org_id, _bank("HAVALE ABC HOLDING", amount=285_000_00))
    proposal = (await _proposed(client, headers))[0]

    res = await client.post(f"/api/v1/ledger/settlements/{proposal['id']}/resolve", headers=headers,
                            json={"action": "confirm"})
    assert res.status_code == 200, res.text
    assert (await _item(client, "A")).status == "settled"
    assert (await _item(client, "B")).status == "settled"
    assert await _proposed(client, headers) == []
    assert (await _summary(client, org_id))["open_items"]["receivable_cents"] == 0


async def test_rejecting_the_lump_frees_every_invoice_and_counts_it_as_its_own_money(client):
    headers, org_id, _ = await kullanici(client, "toplu3@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=185_000_00, no="N2", issued="2024-01-05", due="2024-02-05"),
    )
    await _upload(client, org_id, _bank("HAVALE ABC HOLDING", amount=285_000_00))
    proposal = (await _proposed(client, headers))[0]

    res = await client.post(f"/api/v1/ledger/settlements/{proposal['id']}/resolve", headers=headers,
                            json={"action": "reject"})
    assert res.status_code == 200, res.text
    assert {(await _item(client, "A")).status, (await _item(client, "B")).status} == {"open"}
    assert await _proposed(client, headers) == []
    assert (await _summary(client, org_id))["revenue_cents"] == 570_000_00


async def test_no_combination_that_adds_up_means_no_proposal(client):
    _, org_id, _ = await kullanici(client, "toplu4@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=185_000_00, no="N2", issued="2024-01-05", due="2024-02-05"),
    )
    counts = await _upload(client, org_id, _bank("HAVALE ABC HOLDING", amount=284_999_99))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_invoices_of_different_customers_are_never_combined(client):
    _, org_id, _ = await kullanici(client, "toplu5@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1", customer="ABC Holding"),
        _sale("B", amount=185_000_00, no="N2", customer="Zeta Tekstil", issued="2024-01-05", due="2024-02-05"),
    )
    counts = await _upload(client, org_id, _bank("HAVALE ABC HOLDING ZETA TEKSTIL", amount=285_000_00))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_a_lump_without_the_customers_name_is_not_guessed(client):
    _, org_id, _ = await kullanici(client, "toplu6@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=185_000_00, no="N2", issued="2024-01-05", due="2024-02-05"),
    )
    counts = await _upload(client, org_id, _bank("GELEN EFT REF 5521", amount=285_000_00))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_two_different_combinations_with_the_same_total_are_not_chosen_between(client):
    _, org_id, _ = await kullanici(client, "toplu7@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=200_000_00, no="N2", issued="2024-01-03", due="2024-02-03"),
        _sale("C", amount=150_000_00, no="N3", issued="2024-01-04", due="2024-02-04"),
        _sale("D", amount=150_000_00, no="N4", issued="2024-01-05", due="2024-02-05"),
    )
    # 100+200 == 150+150: either pair would "fit".
    counts = await _upload(client, org_id, _bank("HAVALE ABC HOLDING", amount=300_000_00))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_uploading_again_does_not_repeat_the_lump_question(client):
    headers, org_id, _ = await kullanici(client, "toplu8@example.com")
    await _upload(
        client, org_id,
        _sale("A", amount=100_000_00, no="N1"),
        _sale("B", amount=185_000_00, no="N2", issued="2024-01-05", due="2024-02-05"),
    )
    await _upload(client, org_id, _bank("HAVALE ABC HOLDING", amount=285_000_00))
    await _upload(client, org_id, _bank("BASKA", amount=7_00, day="2024-03-01"))
    assert len(await _proposed(client, headers)) == 1
