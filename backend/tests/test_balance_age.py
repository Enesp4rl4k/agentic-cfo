"""How old a proven balance may be before the runway stops calling it known (PR #125 follow-up).

Rule: every balance states its date; a balance (or an account's balance, against the other accounts') older than
the runway's burn window (`BURN_WINDOW_DAYS`, three months of burn) is only `assumed`, with
"bakiye N gün önceki ekstreye ait". Older than the 7-day radar limit but inside the window it stays dated and
`known` (the existing "güncel olmayabilir" note).
"""
from __future__ import annotations

from datetime import date

import pytest_asyncio

from app.services.bank_balance import BURN_WINDOW_DAYS, aged_basis
from app.services.cash_radar import compute_cash_radar
from app.services.runway import RUNWAY_MIN_MONTHS
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import BURN, upload
from tests.radar_helpers import statement_meta as _stmt
from tests.test_bank_accounts import IBAN_A, IBAN_B, _two_banks


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def test_the_age_limit_is_the_burn_window_and_a_young_balance_keeps_its_basis() -> None:
    assert BURN_WINDOW_DAYS == RUNWAY_MIN_MONTHS * 31
    assert aged_basis("known", None, BURN_WINDOW_DAYS) == ("known", None)
    assert aged_basis(None, "x", 3) == ("known", "x")
    assert aged_basis("known", None, 94) == ("assumed", "bakiye 94 gün önceki ekstreye ait")
    assert aged_basis("assumed", "yalnızca 1 bakiye adımıyla doğrulandı", 200) == (
        "assumed", "yalnızca 1 bakiye adımıyla doğrulandı; bakiye 200 gün önceki ekstreye ait")


async def _radar(client, org_id: str, anchor: date):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=anchor)


async def test_a_very_old_account_makes_the_opening_and_the_runway_assumed_and_says_its_date(client) -> None:
    _, org_id, _ = await kullanici(client, "age1@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, filename="eski-banka.pdf", meta=_stmt(
        "2025-06-01", "2025-10-15", 30_000_00, 25_000_00, identity="iban:TR000000000000000000000001"))
    radar = await _radar(client, org_id, date(2026, 4, 3))
    old = next(a for a in radar.opening_cash.accounts if a["name"] == "eski-banka.pdf")
    assert (old["behind_days"], old["basis"]) == (167, "assumed")
    assert radar.opening_cash.basis == "assumed" and "bakiye 167 gün önceki ekstreye ait" in radar.opening_cash.basis_note
    block = radar.runway
    # The old account's statement ends in October: the burn months are not complete for it, so there is no runway
    # figure at all, and the balance it would have divided is stated with its date and as an assumption.
    assert block["balance_basis"] == "assumed" and block["runway_months"] is None
    assert "eski-banka.pdf bakiyesi 15 Ekim 2025 tarihli, diğerlerinden 167 gün eski" in block["message"]
    assert "bakiye 167 gün önceki ekstreye ait" in block["message"] and "varsayım" in block["message"]


async def test_one_statement_older_than_the_burn_window_cannot_make_the_runway_known(client) -> None:
    _, org_id, _ = await kullanici(client, "age2@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00, identity=IBAN_A))
    young = await _radar(client, org_id, date(2026, 6, 29))               # 90 days: inside the window, dated, known
    assert (young.opening_cash.age_days, young.opening_cash.stale, young.opening_cash.basis) == (90, True, "known")
    assert young.runway["balance_basis"] == "known" and "Bu bakiye 90 gün önceki ekstreden" in young.runway["message"]
    old = await _radar(client, org_id, date(2026, 8, 15))                 # 137 days: older than the burn window
    assert (old.opening_cash.age_days, old.opening_cash.basis) == (137, "assumed")
    assert old.opening_cash.basis_note == "bakiye 137 gün önceki ekstreye ait"
    assert old.runway["status"] == "computed" and old.runway["balance_basis"] == "assumed"
    assert old.runway["basis"] == "assumed"                            # never "known"
    assert "31 Mart 2026" in old.runway["message"] and "bakiye 137 gün önceki ekstreye ait" in old.runway["message"]


async def test_a_fresh_second_account_beside_an_inside_the_window_one_stays_known(client) -> None:
    _, org_id, _ = await kullanici(client, "age3@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, filename="orta.pdf", meta=_stmt(
        "2025-12-01", "2026-02-10", 30_000_00, 25_000_00, identity="iban:TR000000000000000000000001"))
    radar = await _radar(client, org_id, date(2026, 4, 3))
    assert radar.opening_cash.basis == "known" and radar.runway["balance_basis"] == "known"
    assert IBAN_B != IBAN_A
