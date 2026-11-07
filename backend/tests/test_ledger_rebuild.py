"""Plan v10 §13.4 E1 — derived data can be deleted and rebuilt; the order of arrival does not matter.

The company's view, the ledger card and the radar are computed from the ledger, and the
ledger from the uploads. If throwing the ledger away and re-reading the uploads gave other
figures, or if the order files arrived in changed them, no figure on a screen could be
trusted to mean the same thing tomorrow.

Expected figures come from `demo/data/logo_tiger_2024.csv` itself (`_file_revenue`) and
from amounts written here by hand.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import delete

from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.services.company_view import ledger_view
from app.services.ledger import backfill, ledger_summary
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_bank_reconciliation import _bank, _sale, _upload
from tests.test_ledger import _analysed, _append, _demo_rows, _file_revenue


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _figures(client, org_id: str) -> dict:
    """Everything a screen shows from the ledger, with nothing that is an identity."""
    async with client._maker() as db:
        summary = await ledger_summary(db, org_id)
        view = await ledger_view(db, org_id)
    return {
        "revenue": summary["revenue_cents"], "expense": summary["expense_cents"],
        "rows": summary["rows"], "months": summary["months"], "period": summary["period"],
        "open_items": summary["open_items"],
        "possible_duplicates": summary["possible_duplicates"],
        "signature": view.signature if view else None,
    }


async def _empty_the_ledger(client, org_id: str) -> None:
    async with client._maker() as db:
        for model in (OpenItemMatch, OpenItem, CanonicalTransaction):
            await db.execute(delete(model).where(model.org_id == org_id))
        await db.commit()


async def _a_company_with_every_kind_of_row(client, email: str):
    _, org_id, _ = await kullanici(client, email)
    await _append(client, await _analysed(client, org_id, _demo_rows("01", "02")))
    await _upload(client, org_id, _sale("F1", issued="2025-03-01", due="2025-03-31", no="GIB2025000000001"))
    await _upload(client, org_id, _bank("EFT GIB2025000000001 ODEME", 285_000_00, "2025-04-10"))
    await _upload(client, org_id, _bank("Tahsilat", 12_500_00, "2025-04-12"))
    return org_id


async def test_throwing_the_ledger_away_and_reading_the_uploads_again_gives_the_same_figures(client):
    org_id = await _a_company_with_every_kind_of_row(client, "yeniden@example.com")
    before = await _figures(client, org_id)
    assert before["revenue"] > 0 and before["open_items"]["receivable_cents"] >= 0

    await _empty_the_ledger(client, org_id)
    assert (await _figures(client, org_id))["rows"] == 0
    async with client._maker() as db:
        await backfill(db)

    after = await _figures(client, org_id)
    assert after == before


async def test_the_signature_names_what_the_figures_say_not_which_row_ids_say_it(client):
    org_id = await _a_company_with_every_kind_of_row(client, "imza@example.com")
    before = (await _figures(client, org_id))["signature"]
    await _empty_the_ledger(client, org_id)
    async with client._maker() as db:
        await backfill(db)
    # New rows, new ids, the same money: a view built from this ledger is the same view.
    assert (await _figures(client, org_id))["signature"] == before


async def test_the_signature_moves_when_the_money_does(client):
    org_id = await _a_company_with_every_kind_of_row(client, "hareket@example.com")
    before = (await _figures(client, org_id))["signature"]
    await _upload(client, org_id, _bank("Yeni tahsilat", 1_000_00, "2025-05-02"))
    assert (await _figures(client, org_id))["signature"] != before


async def test_the_order_files_arrive_in_does_not_change_the_figures(client):
    """Same three uploads, two orders, two companies: the same revenue, expense and cash."""
    invoice = _sale("F9", issued="2025-03-01", due="2025-03-31", no="GIB2025000000009")
    receipt = _bank("EFT GIB2025000000009 ODEME", 285_000_00, "2025-04-10")

    _, first, _ = await kullanici(client, "sira-bir@example.com")
    await _append(client, await _analysed(client, first, _demo_rows("01")))
    await _upload(client, first, invoice)
    await _upload(client, first, receipt)

    _, second, _ = await kullanici(client, "sira-iki@example.com")
    await _upload(client, second, receipt)
    await _upload(client, second, invoice)
    await _append(client, await _analysed(client, second, _demo_rows("01")))

    a, b = await _figures(client, first), await _figures(client, second)
    for key in ("revenue", "expense", "rows", "months", "period", "open_items", "possible_duplicates"):
        assert a[key] == b[key], key
    assert a["revenue"] == _file_revenue({"01"}) + 285_000_00


async def test_splitting_one_file_in_two_does_not_change_the_figures(client):
    rows = _demo_rows("01", "02", "03")

    _, whole, _ = await kullanici(client, "bir-dosya@example.com")
    await _append(client, await _analysed(client, whole, rows))

    _, split, _ = await kullanici(client, "iki-dosya@example.com")
    half = len(rows) // 2
    await _append(client, await _analysed(client, split, rows[:half]))
    await _append(client, await _analysed(client, split, rows[half:]))

    a, b = await _figures(client, whole), await _figures(client, split)
    for key in ("revenue", "expense", "rows", "months", "period"):
        assert a[key] == b[key], key
    assert a["revenue"] == _file_revenue({"01", "02", "03"})


async def test_an_unrelated_company_changes_nothing(client):
    org_id = await _a_company_with_every_kind_of_row(client, "ilgisiz@example.com")
    before = await _figures(client, org_id)
    _, other, _ = await kullanici(client, "baska@example.com")
    await _append(client, await _analysed(client, other, _demo_rows("05")))
    assert await _figures(client, org_id) == before
