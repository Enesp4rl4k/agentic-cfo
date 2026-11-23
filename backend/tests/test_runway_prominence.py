"""Certainty is not prominence (PR #140 re-review).

CERTAINTY (known / assumed) decides whether "kritik" and the top alert severity may be used. PROMINENCE decides how
visibly the user is told: a computed runway at or below RUNWAY_ATTENTION_MONTHS is the first thing said (briefing,
radar, alert) whether it is known or assumed. Each assumption has its own sentence, carried from the one block.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest_asyncio

from app.config import get_settings
from app.services.bank_balance import aged_basis
from app.services.cash_radar import compute_cash_radar
from app.services.monday_briefing import assemble_monday_briefing
from app.services.runway import (
    RUNWAY_ATTENTION_MONTHS,
    RUNWAY_CRITICAL_MONTHS,
    UPLOAD_PROMPT,
    compute_runway,
    runway_alert,
    runway_line,
)
from app.services.runway_display import runway_for_display
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import BURN, statement_meta, upload

LIMIT = get_settings().radar_balance_stale_after_days
FORBIDDEN = ("kritik", "kanıtlı", "zayıf kanıt")


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _series(assumed: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = [{"month": f"2026-0{m}", "in": 0, "out": 5_000_00, "net": -5_000_00, "complete": True} for m in (1, 2, 3)]
    if assumed:
        out[0]["assumed"] = assumed
    return out


def _opening(cents: int, age: int, *, basis: str | None = "known", note: str | None = None, **extra: Any) -> dict[str, Any]:
    b, n = aged_basis(basis, note, age, "2026-03-31")
    return {"balance_cents": cents, "as_of": "2026-03-31", "age_days": age, "stale": age > LIMIT, "stale_after_days": LIMIT,
            "filename": "e.csv", "basis": b, "basis_note": n, "accounts": [], **extra}


def _block(opening: dict[str, Any], series: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return compute_runway(opening, {"monthly_series": series or _series()}, "TRY")


def _clean(text: str) -> None:
    assert not any(w in text.lower() for w in FORBIDDEN), text


def test_one_constant_for_attention_and_the_cap_is_still_certainty() -> None:
    assert RUNWAY_ATTENTION_MONTHS == RUNWAY_CRITICAL_MONTHS == 3


def test_a_low_runway_on_an_old_balance_is_attention_never_critical_and_is_sent() -> None:
    block = _block(_opening(7_500_00, 25))                                  # 1,5 months of cash, balance 25 days old
    assert (block["runway_months"], block["level"], block["attention"], block["balance_basis"]) == (1.5, "warning", True, "assumed")
    line = runway_line(block)
    assert line.startswith("DİKKAT: Son ekstreye göre nakit pisti yaklaşık 1,5 ay")
    assert "Bu bakiye 25 gün önceki ekstreden (31 Mart 2026)" in line and UPLOAD_PROMPT in line
    _clean(line)
    assert runway_alert(block) == {"level": "warning", "message": line, "basis": "runway"}   # not silent, capped, same text


def test_a_known_current_low_runway_is_critical_and_first() -> None:
    block = _block(_opening(7_500_00, 3))
    assert (block["level"], block["attention"]) == ("critical", True)
    assert runway_line(block).startswith("KRİTİK: Nakit pisti yaklaşık 1,5 ay")
    assert (runway_alert(block) or {})["level"] == "critical"


def test_a_long_assumed_runway_is_not_promoted() -> None:
    block = _block(_opening(50_000_00, 25))                                  # 10 months
    assert (block["runway_months"], block["attention"]) == (10.0, False)
    assert not runway_line(block).startswith(("DİKKAT", "KRİTİK"))
    assert block["level"] is None


def test_the_boundary_is_three_months() -> None:
    assert _block(_opening(15_000_00, 25))["attention"] is True               # exactly 3,0 months
    assert _block(_opening(15_500_00, 25))["attention"] is False


def test_the_class_follows_the_figure_as_printed() -> None:
    # 3.04 months prints "3,0 ay": the class is decided by that figure, so text and class agree.
    known = _block(_opening(15_200_00, 3))
    assert known["runway_months"] == 3.0 and (known["level"], known["attention"]) == ("critical", True)
    assert "yaklaşık 3,0 ay" in known["message"] and runway_line(known).startswith("KRİTİK: Nakit pisti yaklaşık 3,0 ay")
    # 3.06 prints "3,1 ay": past the boundary, no attention, no critical.
    over = _block(_opening(15_300_00, 3))
    assert over["runway_months"] == 3.1 and (over["level"], over["attention"]) == ("warning", False)
    # the standing rule: an assumed balance at the same figure is capped, worded DİKKAT, never kritik/kanıtlı
    assumed = _block(_opening(15_200_00, 25))
    assert (assumed["level"], assumed["attention"]) == ("warning", True)
    line = runway_line(assumed)
    assert line.startswith("DİKKAT: Son ekstreye göre nakit pisti yaklaşık 3,0 ay")
    _clean(line)


def test_a_runway_under_a_month_is_said_as_that_not_as_zero() -> None:
    near_zero = _block(_opening(1_00, 3))                                     # ₺1 against a ₺5.000 burn
    assert near_zero["runway_months"] == 0.0
    for text in (near_zero["message"], runway_line(near_zero),
                 runway_for_display({"scenarios": {"base": {"runway_months": 0.0}}, "runway": near_zero}).text()):
        assert "1 aydan az (2 günden az)" in text and "yaklaşık 0,0 ay" not in text and " 0 ay" not in text, text
    half = _block(_opening(2_500_00, 3))                                      # half a month of cash
    assert "1 aydan az (yaklaşık 15 gün)" in half["message"]
    assert runway_line(half).startswith("KRİTİK: Nakit pisti 1 aydan az (yaklaşık 15 gün)")
    old = _block(_opening(2_500_00, 25))                                      # same on an old balance
    line = runway_line(old)
    assert line.startswith("DİKKAT: Son ekstreye göre nakit pisti 1 aydan az (yaklaşık 15 gün)") and old["level"] == "warning"
    _clean(line)
    assert "1,0 ay" in _block(_opening(5_000_00, 3))["message"]                # a full month is still a month


def test_unknown_stays_unknown_with_no_number() -> None:
    block = compute_runway(None, {"monthly_series": _series()}, "TRY")
    assert block["attention"] is False and block["runway_months"] is None
    assert runway_for_display({"scenarios": {"base": {"runway_months": 2.0}}, "runway": block}).text() == "bilinmiyor"


# Each reason has its OWN sentence, on every surface that reads the block.
CASES = {
    "old_balance": (lambda: _block(_opening(7_500_00, 25)), "Bu bakiye 25 gün önceki ekstreden"),
    "thin_proof": (lambda: _block(_opening(7_500_00, 3, basis="assumed", note="yalnızca 2 bakiye adımıyla doğrulandı")),
                   "Bakiye zayıf kanıta dayanıyor (yalnızca 2 bakiye adımıyla doğrulandı)"),
    "identity_unresolved": (lambda: _block(_opening(7_500_00, 3, basis="assumed", uncertain=True,
                                                    identity_note="2 ekstrenin aynı hesaba mı ait olduğu bilinmiyor")),
                            "2 ekstrenin aynı hesaba mı ait olduğu bilinmiyor"),
    "edge_tolerance": (lambda: _block(_opening(7_500_00, 3), _series([{"edge": "start", "days": 2}])),
                       "ay tam sayıldı (varsayım)"),
}


def test_each_assumption_reason_has_its_own_sentence_on_every_surface() -> None:
    for code, (make, sentence) in CASES.items():
        block = make()
        assert code in {r["code"] for r in block["reasons"]}, code
        forecast = {"scenarios": {"base": {"runway_months": block["runway_months"]}}, "runway": block}
        surfaces = {
            "block message (dashboard, chat context)": block["message"],
            "briefing line": runway_line(block),
            "display text (PDF, prompts)": runway_for_display(forecast).text(),
            "alert": (runway_alert(block) or {})["message"],
        }
        for where, text in surfaces.items():
            assert sentence in text, (code, where, text)
        if code != "thin_proof":
            for text in surfaces.values():
                assert "Bakiye zayıf kanıta dayanıyor" not in text, code   # "zayıf kanıt" is the thin-proof reason only
    old = CASES["old_balance"][0]()
    assert UPLOAD_PROMPT in old["message"] and UPLOAD_PROMPT in runway_line(old)
    assert "zayıf kanıt" not in runway_for_display({"scenarios": {"base": {"runway_months": 1.5}}, "runway": old}).text()


# ── through the real briefing and radar ──────────────────────────────────────────────────────────────────────────

async def _company(client, tag: str, closing: int) -> str:
    _, org_id, _ = await kullanici(client, f"{tag}@example.com")
    await upload(client, org_id, *BURN, filename="ekstre.pdf",
                 meta=statement_meta("2026-01-01", "2026-03-31", 170_000_00, closing))
    return org_id


async def _briefing(client, org_id: str, anchor: date):
    async with client._maker() as db:
        return await assemble_monday_briefing(db, org_id, anchor_date=anchor, candidate_narrative=None)


async def test_the_reviewers_case_is_the_first_thing_in_the_briefing_and_flagged_in_the_radar(client) -> None:
    org_id = await _company(client, "p1", 45_000_00)                         # 1,5 months of a 30.000 burn
    anchor = date(2026, 4, 25)                                              # the statement is 25 days old
    b = await _briefing(client, org_id, anchor)
    assert (b.runway_level, b.runway_attention, b.runway_basis) == ("warning", True, "assumed")
    assert b.full_text.startswith(b.runway_line) and b.runway_line.startswith("DİKKAT: Son ekstreye göre nakit pisti yaklaşık 1,5 ay")
    assert "25 gün önceki ekstreden" in b.runway_line and UPLOAD_PROMPT in b.runway_line
    _clean(b.runway_line)
    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=anchor)
    assert radar.runway["attention"] is True and radar.runway["level"] == "warning" and radar.runway["upload_path"] == "/upload"
    assert (runway_alert(radar.runway) or {})["level"] == "warning"


async def test_a_known_current_runway_of_the_same_size_is_critical_and_first(client) -> None:
    org_id = await _company(client, "p2", 45_000_00)
    b = await _briefing(client, org_id, date(2026, 4, 6))                    # six days old
    assert (b.runway_level, b.runway_attention) == ("critical", True)
    assert b.full_text.startswith("KRİTİK: Nakit pisti yaklaşık 1,5 ay")


async def test_a_long_assumed_runway_in_the_briefing_is_not_first(client) -> None:
    org_id = await _company(client, "p3", 300_000_00)                        # ten months
    b = await _briefing(client, org_id, date(2026, 4, 25))
    assert (b.runway_basis, b.runway_attention) == ("assumed", False)
    assert not b.full_text.startswith(b.runway_line)
