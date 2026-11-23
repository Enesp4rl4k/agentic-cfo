"""A balance is a fact about a past day; a runway answers "how long does today's cash last" (PR #140 review).

One rule (`bank_balance.aged_basis`): a balance older than the radar's staleness limit
(`radar_balance_stale_after_days`, 7 days, the limit `balance_age` flags with `stale`) is only `assumed` and says its
date and age; an assumed runway never raises a critical alert. A summed set of accounts is as old as its oldest
account. Every surface (radar, runway block, runway_for_display, cascade basis, alert) reads the same block.
"""
from __future__ import annotations

from datetime import date

import pytest_asyncio

from app.config import get_settings
from app.services.bank_balance import aged_basis
from app.services.cascade_inputs import baseline_from
from app.services.cash_radar import compute_cash_radar
from app.services.runway import compute_runway, runway_alert
from app.services.runway_display import runway_for_display
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import BURN, upload
from tests.radar_helpers import statement_meta as _stmt
from tests.test_bank_accounts import IBAN_A, _two_banks

LIMIT = get_settings().radar_balance_stale_after_days


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def test_the_boundary_is_the_radar_staleness_limit() -> None:
    assert LIMIT == 7
    assert aged_basis("known", None, LIMIT, "2026-03-31") == ("known", None)
    assert aged_basis(None, "x", 3) == ("known", "x")
    assert aged_basis("known", None, LIMIT + 1, "2026-03-31") == (
        "assumed", f"bakiye {LIMIT + 1} gün önceki ekstreye ait (2026-03-31)")
    assert aged_basis("assumed", "yalnızca 1 bakiye adımıyla doğrulandı", 200) == (
        "assumed", "yalnızca 1 bakiye adımıyla doğrulandı; bakiye 200 gün önceki ekstreye ait")


def _block(age: int):
    """The reviewer's case: ₺10,000 and ₺5,000 a month over three complete months."""
    basis, note = aged_basis("known", None, age, "2026-02-01")
    opening = {"balance_cents": 10_000_00, "as_of": "2026-02-01", "age_days": age, "stale": age > LIMIT,
               "stale_after_days": LIMIT, "filename": "e.csv", "basis": basis, "basis_note": note, "accounts": []}
    series = [{"month": f"2025-{m:02d}", "in": 0, "out": 5_000_00, "net": -5_000_00, "complete": True} for m in (11, 12)]
    series.append({"month": "2026-01", "in": 0, "out": 5_000_00, "net": -5_000_00, "complete": True})
    return compute_runway(opening, {"monthly_series": series}, "TRY")


def test_a_ninety_day_old_balance_is_assumed_not_critical_and_names_its_age() -> None:
    block = _block(90)
    assert (block["status"], block["runway_months"]) == ("computed", 2.0)
    assert block["balance_basis"] == "assumed" and block["basis"] == "assumed" and block["level"] == "warning"
    assert "bakiye 90 gün önceki ekstreye ait (2026-02-01)" in block["message"]
    alert = runway_alert(block)
    assert alert is not None and alert["level"] == "warning"


def test_a_three_day_old_balance_with_the_same_burn_is_known_and_critical() -> None:
    block = _block(3)
    assert (block["balance_basis"], block["basis"], block["level"]) == ("known", "known", "critical")


def test_every_age_past_the_limit_is_assumed_and_never_critical() -> None:
    for age in (LIMIT, LIMIT + 1, 30, 93, 94):
        block = _block(age)
        assert block["level"] == ("critical" if age == LIMIT else "warning"), age
        assert block["balance_basis"] == ("known" if age == LIMIT else "assumed"), age


def test_every_surface_reads_the_same_basis() -> None:
    block = _block(90)
    view = runway_for_display({"scenarios": {"base": {"runway_months": 2.0}}, "runway": block})
    assert view.basis == "assumed" and not view.proven and view.cap("critical") == "high"
    assert "bakiye 90 gün önceki ekstreye ait" in view.text()
    _, basis = baseline_from(block)
    assert basis.balance_basis == "assumed" and not basis.proven


async def _radar(client, org_id: str, anchor: date):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=anchor)


async def test_two_accounts_one_stale_the_oldest_decides_and_is_named(client) -> None:
    _, org_id, _ = await kullanici(client, "age1@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, filename="eski-banka.pdf", meta=_stmt(
        "2025-12-01", "2026-02-10", 30_000_00, 25_000_00, identity="iban:TR000000000000000000000001"))
    radar = await _radar(client, org_id, date(2026, 4, 3))
    assert radar.opening_cash.basis == "assumed" and "bakiye 49 gün önceki ekstreye ait (2026-02-10)" in radar.opening_cash.basis_note
    block = radar.runway
    assert block["balance_basis"] == "assumed" and block["level"] != "critical"
    assert "eski-banka.pdf bakiyesi 10 Şubat 2026 tarihli, diğerlerinden 49 gün eski" in block["message"]


async def test_accounts_within_the_limit_stay_known(client) -> None:
    _, org_id, _ = await kullanici(client, "age2@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, filename="yakin.pdf", meta=_stmt(
        "2026-03-01", "2026-03-28", 30_000_00, 25_000_00, identity="iban:TR000000000000000000000001"))
    radar = await _radar(client, org_id, date(2026, 4, 3))
    assert radar.opening_cash.basis == "known" and radar.runway["balance_basis"] == "known"


async def test_one_statement_older_than_the_limit_is_assumed_with_its_date(client) -> None:
    _, org_id, _ = await kullanici(client, "age3@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00, identity=IBAN_A))
    fresh = await _radar(client, org_id, date(2026, 4, 7))                 # 7 days: inside the limit
    assert (fresh.opening_cash.age_days, fresh.opening_cash.basis, fresh.runway["level"]) == (7, "known", "critical")
    old = await _radar(client, org_id, date(2026, 4, 8))                   # 8 days
    assert (old.opening_cash.basis, old.runway["balance_basis"]) == ("assumed", "assumed")
    assert old.runway["level"] != "critical" and "bakiye 8 gün önceki ekstreye ait (2026-03-31)" in old.runway["message"]
