"""The database refuses money rows the code would misread.

There was no CHECK constraint anywhere: a misspelt status left a row in no total
(the ledger counts `active`, the journal files `onaylandi`) and nothing stopped a
negative paid amount. Migration 059 adds the checks; the models carry the same
ones so a fresh schema (and every test database) enforces them too.
"""
from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import IntegrityError

import app.main  # noqa: F401 — registers every model
from app.database import Base
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.smmm_onay import SMMMOnayKaydi
from tests.db_helpers import gecici_veritabani


def _migration() -> Any:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "059_money_check_constraints.py"
    spec = importlib.util.spec_from_file_location("m059", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_models_carry_the_checks_the_migration_adds() -> None:
    in_models = {
        (table.name, c.name, str(c.sqltext))
        for table in Base.metadata.sorted_tables
        for c in table.constraints
        if isinstance(c, CheckConstraint) and c.name and str(c.name).startswith("ck_")
    }
    assert set(_migration().CHECKS) <= in_models


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


def _item(**over: Any) -> OpenItem:
    return OpenItem(**{
        "org_id": "o1", "direction": "receivable", "document_id": "INV-1", "counterparty": "ABC",
        "amount_cents": 100_00, "issue_date": date(2026, 1, 1), "due_date": date(2026, 2, 1),
        "description": "fatura", **over,
    })


def _row(**over: Any) -> CanonicalTransaction:
    return CanonicalTransaction(**{
        "org_id": "o1", "source_type": "upload", "source_record_id": "r1",
        "transaction_date": datetime(2026, 1, 1, tzinfo=UTC), "amount_cents": 100_00,
        "direction": "income", **over,
    })


def _match(**over: Any) -> OpenItemMatch:
    return OpenItemMatch(**{
        "org_id": "o1", "open_item_id": "i1", "ledger_row_id": "r1", "amount_cents": 100_00,
        "method": "by_number", "status": "confirmed", "matched_on": date(2026, 1, 1), **over,
    })


def _onay(**over: Any) -> SMMMOnayKaydi:
    return SMMMOnayKaydi(**{"job_id": "j1", "kayit_id": "k1", "durum": "bekliyor", **over})


GOOD = [_item, _row, _match, _onay]
BAD = [
    lambda: _item(direction="income"),
    lambda: _item(status="kapali"),
    lambda: _item(paid_cents=-1),
    lambda: _match(status="maybe"),
    lambda: _match(amount_cents=0),
    lambda: _row(ledger_status="activ"),
    lambda: _row(basis="bank"),
    lambda: _onay(durum="onaylandı"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("make", GOOD)
async def test_a_row_the_code_writes_is_accepted(maker, make) -> None:
    async with maker() as db:
        db.add(make())
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("make", BAD)
async def test_a_row_the_code_would_misread_is_refused(maker, make) -> None:
    async with maker() as db:
        db.add(make())
        with pytest.raises(IntegrityError):
            await db.commit()
