"""A balance chain the reader could not verify proves no balance, no extent and so no runway.

PR #116's readers report `balance_check` ("verified" | "unverified" | None) and the rows they lost
(`unaccounted`). The chain test on the rows we hold is not enough when the reader itself says it could not
verify the chain (a text statement with an ambiguous direction) or when rows went missing.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest_asyncio

from app.models.analysis_job import JobStatus
from app.services.bank_accounts import proven_balance, proven_statements
from app.services.bank_balance import chain_verified
from app.services.coverage import extents_for
from app.services.runway import opening_cash_for
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import upload

ROWS = [
    {"transaction_date": "2026-02-02", "amount_cents": 1_000, "type": "income", "balance_cents": 11_000},
    {"transaction_date": "2026-02-09", "amount_cents": 500, "type": "expense", "balance_cents": 10_500},
]
# Three reconciling steps: enough for the reader to believe the chain, so an "unverified" verdict from
# it is about something else (a direction nobody could place) and is not overridden.
LONG = [
    *ROWS,
    {"transaction_date": "2026-02-10", "amount_cents": 200, "type": "expense", "balance_cents": 10_300},
    {"transaction_date": "2026-02-11", "amount_cents": 300, "type": "income", "balance_cents": 10_600},
]
TODAY = date(2026, 2, 12)


def test_chain_verified_reads_both_the_run_counts_and_the_stored_summary() -> None:
    assert chain_verified(None) and chain_verified({}) and chain_verified({"balance_check": None})
    assert chain_verified({"balance_check": "verified", "unaccounted": 0})
    assert not chain_verified({"balance_check": "unverified"})
    assert not chain_verified({"balance_check": "verified", "unaccounted": 2})  # rows the readers lost


def test_an_unverified_chain_gives_no_opening_cash_except_the_explicit_under_three_steps_assumption() -> None:
    """The old guarantee holds: a chain the reader could not verify proves nothing. The one exception is
    fewer than three reconciling steps, kept as an `assumed` balance with its reason (asserted below)."""
    assert opening_cash_for({"transactions": ROWS}, TODAY)["balance_cents"] == 10_500  # type: ignore[index]
    unverified = {"transactions": LONG, "ingest_counts": {"balance_check": "unverified"}}
    assert opening_cash_for(unverified, TODAY) is None
    # Fewer than three steps is thin evidence, not none: kept as an assumption with its reason, never as known.
    thin = opening_cash_for({"transactions": ROWS, "ingest_counts": {"balance_check": "unverified"}}, TODAY)
    assert thin is not None and thin["balance_cents"] == 10_500
    assert thin["basis"] == "assumed" and thin["basis_note"] == "yalnızca 1 bakiye adımıyla doğrulandı"
    verified = {"transactions": ROWS, "ingest_counts": {"balance_check": "verified", "unaccounted": 0}}
    assert opening_cash_for(verified, TODAY)["balance_cents"] == 10_500  # type: ignore[index]


def test_an_unverified_chain_gives_no_joinable_extent() -> None:
    chained = extents_for({"transactions": ROWS})
    assert chained[0]["opening_cents"] == 10_000 and chained[0]["closing_cents"] == 10_500
    (plain,) = extents_for({"transactions": LONG, "ingest_counts": {"balance_check": "unverified"}})
    assert "opening_cents" not in plain and (plain["start"], plain["end"]) == ("2026-02-02", "2026-02-11")


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _meta(check: str | None) -> dict[str, Any]:
    return {
        "closing_balance": {"date": "2026-02-09", "balance_cents": 10_500},
        "statement_extent": {"start": "2026-02-02", "end": "2026-02-09", "opening_cents": 10_000, "closing_cents": 10_500},
        "ingest": {"balance_check": check, "unaccounted": 0},
    }


async def test_the_companys_proven_balance_and_statements_skip_an_unverified_chain(client) -> None:
    _, org_id, _ = await kullanici(client, "zincir@example.com")
    await upload(client, org_id, meta=_meta("unverified"), status=JobStatus.COMPLETED)
    async with client._maker() as db:
        assert await proven_balance(db, org_id) is None
        assert await proven_statements(db, org_id) == []
    await upload(client, org_id, meta=_meta("verified"), status=JobStatus.COMPLETED)
    async with client._maker() as db:
        balance = await proven_balance(db, org_id)
        assert balance is not None and balance["balance_cents"] == 10_500
        assert len(await proven_statements(db, org_id)) == 1
