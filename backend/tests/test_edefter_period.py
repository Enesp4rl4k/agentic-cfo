"""Bir defterin dönemi, kayıtlarının tarihidir — yüklendiği ay değil.

The e-Defter routes took the period from a `donem` field no code ever wrote,
and fell back to the job's creation month. A live run showed it: the TechNova
January 2024 books came back as `1234567808-202609-Y-000000.xml` — the right
movements, filed as September 2026. On a legal document that is not a label
error; it is a filing for the wrong month, and an empty one for the right one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.edefter_xbrl import (
    EDefterError,
    EDefterXBRLGenerator,
    LedgerOwner,
    ledger_period,
)

OWNER = LedgerOwner(vkn="1234567808", title="TechNova A.Ş.")


def _e(tarih: str | None, n: int = 1) -> dict:
    return {
        "kayit_id": f"e{n}",
        "tarih": tarih,
        "aciklama": "x",
        "satirlar": [
            {"hesap_kodu": "770.01", "hesap_adi": "Gider", "borc": 100, "alacak": 0},
            {"hesap_kodu": "102.01", "hesap_adi": "Banka", "borc": 0, "alacak": 100},
        ],
    }


def test_the_period_is_the_month_the_entries_are_in() -> None:
    period, chosen = ledger_period([_e("2024-01-05T00:00:00"), _e("2024-01-31", 2)])
    assert period == "2024-01"
    assert len(chosen) == 2


def test_entries_spanning_months_are_not_silently_merged() -> None:
    with pytest.raises(EDefterError, match="2 aya"):
        ledger_period([_e("2024-01-05"), _e("2024-02-01", 2)])


def test_a_named_month_selects_its_entries() -> None:
    period, chosen = ledger_period([_e("2024-01-05"), _e("2024-02-01", 2)], "2024-02")
    assert period == "2024-02"
    assert [e["kayit_id"] for e in chosen] == ["e2"]


def test_a_named_month_with_nothing_in_it_is_refused() -> None:
    with pytest.raises(EDefterError, match="kayıt yok"):
        ledger_period([_e("2024-01-05")], "2024-03")


@pytest.mark.parametrize("bad", ["2024-1", "2024-13", "ocak"])
def test_a_named_month_must_be_a_month(bad: str) -> None:
    with pytest.raises(EDefterError):
        ledger_period([_e("2024-01-05")], bad)


def test_an_undated_entry_cannot_be_placed() -> None:
    with pytest.raises(EDefterError, match="tarihi yok"):
        ledger_period([_e("2024-01-05"), _e(None, 2)])


@pytest.mark.parametrize("kind", ["journal", "ledger"])
def test_the_generator_refuses_an_entry_outside_its_period(kind: str) -> None:
    """The last line of defence: whatever the caller passes as the period,
    a posting dated in another month cannot go into this month's ledger."""
    build = (
        EDefterXBRLGenerator.generate_journal if kind == "journal"
        else EDefterXBRLGenerator.generate_ledger
    )
    with pytest.raises(EDefterError, match="dönem"):
        build([_e("2024-01-05")], period="2026-09", owner=OWNER)


def test_the_routes_no_longer_fall_back_to_the_job_date() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "muhasebe.py").read_text(
        encoding="utf-8"
    )
    assert 'journal.get("donem")' not in src, "hiçbir kodun yazmadığı alan okunuyor"
    assert 'created_at.strftime("%Y-%m")' not in src, "dönem işin oluşturulma ayından türetiliyor"
