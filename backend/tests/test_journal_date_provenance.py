"""Uydurulmuş bir tarih beyan edilemez.

A transaction whose date would not parse was silently dated *today*. That date
then flowed into the journal entry, into the sealed defensibility packet, and
into the e-Defter's `postingDate` — so a January transaction could be filed as
September, in the wrong accounting period, on a legal document, with nothing
said about it anywhere.

It was not an edge case either: the CSV parser emits `transaction_date=None`
for every date it cannot read, and the fixture corpus has such rows on purpose.

The period an entry belongs to is exactly the kind of fact a reviewer can
settle from the source document and the machine cannot, so the entry is kept,
marked, and held — and the ledger refuses to carry it until someone has looked.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.accounting.double_entry import DoubleEntryEngine
from app.services.accounting.thp_classifier import THPClassifier
from app.services.edefter_xbrl import (
    EDefterError,
    EDefterXBRLGenerator,
    LedgerOwner,
)

OWNER = LedgerOwner(vkn="1234567808", title="TechNova A.Ş.")


def _entry(engine: DoubleEntryEngine, clf: THPClassifier, tx_date):
    tx = {
        "amount_kurus": 2_850_000,
        "type": "expense",
        "description": "Ocak ofis kirasi",
        "id": "tx-1",
        "transaction_date": tx_date,
    }
    return engine.create_entry(tx, clf.classify(tx["description"], tx["amount_kurus"], tx["type"]))


@pytest.fixture
def engine():
    return DoubleEntryEngine()


@pytest.fixture
def clf():
    return THPClassifier()


# ── Where the date came from ─────────────────────────────────────────────────

def test_a_real_date_is_kept_and_marked_as_the_transaction_s_own(engine, clf) -> None:
    kayit = _entry(engine, clf, "2024-01-20T00:00:00+00:00")
    assert kayit.tarih.date().isoformat() == "2024-01-20"
    assert kayit.tarih_kaynagi == "islem"


@pytest.mark.parametrize("bad", [None, "gecersiz", "2024-13-45", ""])
def test_an_unreadable_date_is_marked_uncertain(engine, clf, bad) -> None:
    """It used to become today's date and say nothing."""
    kayit = _entry(engine, clf, bad)
    assert kayit.tarih_kaynagi == "belirsiz"


def test_an_uncertain_date_sends_the_entry_to_a_human(engine, clf) -> None:
    kayit = _entry(engine, clf, None)
    assert kayit.onay_gerekli, "belirsiz tarihli kayıt otomatik geçmemeli"
    assert "tarih" in kayit.onay_neden.lower()


def test_the_authority_rationale_is_kept_alongside_the_date_note(engine, clf) -> None:
    """The matrix may already have a reason; the date note is added, not
    substituted, or a reviewer loses half the story."""
    tx = {
        "amount_kurus": 5_000_000_00,   # far over the approval limit
        "type": "expense",
        "description": "Bilinmeyen buyuk odeme",
        "id": "tx-2",
        "transaction_date": None,
    }
    kayit = engine.create_entry(
        tx, clf.classify(tx["description"], tx["amount_kurus"], tx["type"])
    )
    assert kayit.onay_gerekli
    assert "tarih" in kayit.onay_neden.lower()
    assert ";" in kayit.onay_neden, "matrisin kendi gerekçesi de kalmalı"


def test_the_provenance_survives_serialisation(engine, clf) -> None:
    """The journal is persisted as a report and read back by the packet and the
    ledger, so the flag has to travel with it."""
    assert _entry(engine, clf, None).to_dict()["tarih_kaynagi"] == "belirsiz"
    assert _entry(engine, clf, "2024-01-20T00:00:00+00:00").to_dict()[
        "tarih_kaynagi"
    ] == "islem"


# ── The ledger refuses to file one ───────────────────────────────────────────

def _rows(tarih_kaynagi: str) -> list[dict]:
    return [{
        "kayit_id": "e1",
        "tarih": datetime(2024, 1, 15, tzinfo=UTC).isoformat(),
        "aciklama": "Ocak kirasi",
        "kaynak_islem_id": "tx-1",
        "tarih_kaynagi": tarih_kaynagi,
        "satirlar": [
            {"hesap_kodu": "770.01", "hesap_adi": "Genel Yönetim", "borc": 2_850_000, "alacak": 0},
            {"hesap_kodu": "102.01", "hesap_adi": "Bankalar", "borc": 0, "alacak": 2_850_000},
        ],
    }]


def test_a_certain_date_files_normally() -> None:
    pkg = EDefterXBRLGenerator.generate_journal(
        _rows("islem"), period="2024-01", owner=OWNER
    )
    assert ">2024-01-15<" in pkg.xml


@pytest.mark.parametrize("kind", ["journal", "ledger"])
def test_neither_ledger_will_carry_an_invented_posting_date(kind: str) -> None:
    build = (
        EDefterXBRLGenerator.generate_journal if kind == "journal"
        else EDefterXBRLGenerator.generate_ledger
    )
    with pytest.raises(EDefterError, match="belirsiz"):
        build(_rows("belirsiz"), period="2024-01", owner=OWNER)


def test_rows_without_the_field_are_treated_as_certain() -> None:
    """Journals sealed before this flag existed carry no `tarih_kaynagi`.
    Refusing them would make old packets unfileable over a field they could not
    have had; the default is the honest reading of what they meant."""
    rows = _rows("islem")
    del rows[0]["tarih_kaynagi"]
    pkg = EDefterXBRLGenerator.generate_journal(rows, period="2024-01", owner=OWNER)
    assert pkg.is_balanced


def test_a_database_row_flagged_as_estimated_is_believed(engine, clf) -> None:
    """The other shape.

    The in-memory pipeline passes None for a date it could not read. The
    database cannot hold a null, so a row persisted with a placeholder carries
    `date_is_estimated` instead — and the engine used to see a perfectly
    ordinary datetime and book it into whatever period `now()` fell in.
    """
    tx = {
        "amount_kurus": 2_850_000,
        "type": "expense",
        "description": "Ocak ofis kirasi",
        "id": "tx-db",
        # A real, parseable date — and a flag saying it was invented upstream.
        "transaction_date": "2026-09-10T21:00:00+00:00",
        "date_is_estimated": True,
    }
    kayit = engine.create_entry(
        tx, clf.classify(tx["description"], tx["amount_kurus"], tx["type"])
    )
    assert kayit.tarih_kaynagi == "belirsiz"
    assert kayit.onay_gerekli


def test_muhasebe_passes_the_flag_out_of_the_database() -> None:
    """The engine cannot honour a flag the API never puts in the dict, and this
    is exactly where the first version of the fix stopped working."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "muhasebe.py").read_text(
        encoding="utf-8"
    )
    assert '"date_is_estimated"' in src, (
        "muhasebe/analiz işlem sözlüğünde date_is_estimated taşımıyor — "
        "veritabanından gelen yol bayrağı kaybediyor"
    )
