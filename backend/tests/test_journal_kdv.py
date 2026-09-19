"""Brüt banka hareketi KDV'yi içinde taşır — ya ayrılır ya da söylenir.

A live run of the berat on the TechNova January 2024 fixture showed 159 000 TL
credited to 600 and nothing to 391. The rows are bank movements: a customer's
payment of 285 000 TL is gross, and for a domestic sale that includes the
output KDV. The engine had no idea of KDV at all, so revenue was overstated
by the tax, the KDV on the ledger was zero, and the berat carried both to GİB.

The rate is not in a bank line, and assuming one would put an invented number
on a filing. So the engine splits exactly what the source states, and holds
everything else for the accountant, marked.
"""
from __future__ import annotations

import pytest

from app.agents.accounting.double_entry import DoubleEntryEngine
from app.services.accounting.thp_classifier import THPClassifier
from app.services.edefter_xbrl import EDefterXBRLGenerator, LedgerOwner


@pytest.fixture
def engine():
    return DoubleEntryEngine()


@pytest.fixture
def clf():
    return THPClassifier()


def _entry(engine, clf, desc: str, amount: int, typ: str, **extra):
    tx = {"id": "tx", "amount_kurus": amount, "type": typ, "description": desc,
          "transaction_date": "2024-01-10T00:00:00+00:00", **extra}
    return engine.create_entry(tx, clf.classify(desc, amount, typ))


def _lines(kayit) -> dict[str, tuple[int, int]]:
    return {s.hesap_kodu: (s.borc, s.alacak) for s in kayit.satirlar}


def test_a_stated_sale_kdv_goes_to_391(engine, clf) -> None:
    k = _entry(engine, clf, "Ocak satış geliri", 120_000_00, "income", kdv_kurus=20_000_00)
    assert k.thp_hesap_kodu == "600"
    lines = _lines(k)
    assert lines["102"] == (120_000_00, 0)
    assert lines["600"] == (0, 100_000_00)
    assert lines["391"] == (0, 20_000_00)
    assert k.dengeli and k.kdv_durumu == "ayrildi"


def test_a_stated_purchase_kdv_goes_to_191(engine, clf) -> None:
    k = _entry(engine, clf, "Ocak ofis kirası", 12_000_00, "expense", kdv_kurus=2_000_00)
    lines = _lines(k)
    assert lines["770"] == (10_000_00, 0)
    assert lines["191"] == (2_000_00, 0)
    assert lines["102"] == (0, 12_000_00)
    assert k.dengeli and k.kdv_durumu == "ayrildi"


def test_a_gross_sale_with_no_stated_kdv_is_held_not_guessed(engine, clf) -> None:
    k = _entry(engine, clf, "Ocak satış geliri", 120_000_00, "income")
    assert "391" not in _lines(k), "oran uydurulmamalı"
    assert _lines(k)["600"] == (0, 120_000_00)
    assert k.kdv_durumu == "ayristirilmadi"
    assert k.onay_gerekli
    assert "KDV" in k.onay_neden


@pytest.mark.parametrize(("desc", "typ"), [
    ("Ocak maaş ödemeleri", "expense"),
    ("SGK primi ödemesi", "expense"),
    ("Ihracat geliri export", "income"),
])
def test_accounts_that_carry_no_kdv_are_not_flagged(engine, clf, desc: str, typ: str) -> None:
    k = _entry(engine, clf, desc, 10_000_00, typ)
    assert k.kdv_durumu == "yok", k.thp_hesap_kodu
    assert "KDV" not in k.onay_neden


def test_stated_zero_is_an_exemption_not_a_gap(engine, clf) -> None:
    k = _entry(engine, clf, "Ocak satış geliri", 50_000_00, "income", kdv_kurus=0)
    assert k.kdv_durumu == "ayrildi"
    assert "KDV" not in k.onay_neden


def test_kdv_not_smaller_than_the_amount_is_refused_as_a_split(engine, clf) -> None:
    k = _entry(engine, clf, "Ocak satış geliri", 1_000_00, "income", kdv_kurus=1_000_00)
    assert "391" not in _lines(k)
    assert k.kdv_durumu == "ayristirilmadi" and k.onay_gerekli
    assert k.dengeli


def test_the_flag_travels_with_the_journal(engine, clf) -> None:
    k = _entry(engine, clf, "Ocak satış geliri", 120_000_00, "income")
    assert k.to_dict()["kdv_durumu"] == "ayristirilmadi"


def test_the_ledger_says_how_many_entries_went_in_gross(engine, clf) -> None:
    rows = [
        _entry(engine, clf, "Ocak satış geliri", 120_000_00, "income").to_dict(),
        _entry(engine, clf, "Ocak satış geliri", 60_000_00, "income", kdv_kurus=10_000_00).to_dict(),
        _entry(engine, clf, "Ocak maaş ödemeleri", 10_000_00, "expense").to_dict(),
    ]
    owner = LedgerOwner(vkn="1234567808", title="TechNova A.Ş.")
    for build in (EDefterXBRLGenerator.generate_journal, EDefterXBRLGenerator.generate_ledger):
        pkg = build(rows, period="2024-01", owner=owner)
        assert pkg.kdv_unverified == 1
        assert any("KDV" in w for w in pkg.warnings)
        assert pkg.is_balanced
