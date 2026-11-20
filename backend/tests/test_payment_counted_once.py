"""A payment is counted once, whatever runs twice.

`paid_cents` was a counter: `+= amount` on whatever copy of the row the caller
had read, with no lock and no unique match. Two passes over the same bank row
(two uploads finishing together, a reconcile racing a confirm) each added the
payment and the invoice read paid twice — the radar then dropped money still
owed. Now the confirmed matches are the record, `paid_cents` is their sum, and
the same (bank row, invoice) pair cannot be matched twice.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.services.reconciliation import CONFIRMED, settle_from_matches
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_bank_reconciliation import _bank, _item, _sale, _upload


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _settled(client, org_id: str) -> tuple[OpenItem, OpenItemMatch]:
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("EFT GIB2024000000001 NOLU FATURA ODEMESI"))
    async with client._maker() as db:
        match = (await db.execute(select(OpenItemMatch).where(OpenItemMatch.org_id == org_id))).scalars().one()
    return await _item(client, "A"), match


async def test_settling_again_from_the_same_matches_changes_nothing(client):
    _, org_id, _ = await kullanici(client, "bir-kez@example.com")
    item, _ = await _settled(client, org_id)
    assert (item.status, item.paid_cents) == ("settled", 285_000_00)

    async with client._maker() as db:
        await settle_from_matches(db, [item.id])
        await settle_from_matches(db, [item.id])
        await db.commit()
    again = await _item(client, "A")
    assert (again.status, again.paid_cents) == ("settled", 285_000_00)


async def test_a_paid_amount_that_drifted_is_put_back_to_what_the_matches_say(client):
    """A counter that was added to twice is corrected from the record."""
    _, org_id, _ = await kullanici(client, "sapma@example.com")
    item, _ = await _settled(client, org_id)
    async with client._maker() as db:
        row = await db.get(OpenItem, item.id)
        row.paid_cents = 2 * 285_000_00
        await db.commit()
        await settle_from_matches(db, [item.id])
        await db.commit()
    assert (await _item(client, "A")).paid_cents == 285_000_00


async def test_the_same_bank_row_cannot_pay_the_same_invoice_twice(client):
    _, org_id, _ = await kullanici(client, "cift@example.com")
    item, match = await _settled(client, org_id)
    async with client._maker() as db:
        db.add(OpenItemMatch(
            org_id=org_id, open_item_id=item.id, ledger_row_id=match.ledger_row_id,
            amount_cents=match.amount_cents, method=match.method, status=CONFIRMED,
            matched_on=match.matched_on,
        ))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_a_paid_amount_without_a_confirmed_match_falls_back_to_open(client):
    """No record, no payment: the item is open again rather than paid on a counter's word."""
    _, org_id, _ = await kullanici(client, "kayitsiz@example.com")
    await _upload(client, org_id, _sale("A"))
    async with client._maker() as db:
        item = (await db.execute(select(OpenItem).where(OpenItem.document_id == "A"))).scalars().one()
        item.paid_cents = item.amount_cents
        item.status = "settled"
        await db.commit()
        await settle_from_matches(db, [item.id])
        await db.commit()
    reopened = await _item(client, "A")
    assert (reopened.status, reopened.paid_cents) == ("open", 0)
