"""Belgenin söylediği KDV ve stopaj yevmiyeye ulaşır.

A live upload of an e-SMM PDF became a transaction of the net payable, and
the approval queue then said "KDV not split — no rate in the source" about a
document that stated KDV and stopaj to the kuruş. The stopaj was not booked
at all. The amounts now travel on the transaction (`kdv_kurus`,
`stopaj_kurus`), and the engine books them where they belong.
"""
from __future__ import annotations

import pytest

from app.agents.accounting.double_entry import DoubleEntryEngine
from app.services.accounting.thp_classifier import THPClassifier


@pytest.fixture
def engine():
    return DoubleEntryEngine()


@pytest.fixture
def clf():
    return THPClassifier()


def _k(engine, clf, desc, amount, typ, **extra):
    tx = {"id": "tx", "amount_kurus": amount, "type": typ, "description": desc,
          "transaction_date": "2026-09-01T00:00:00+00:00", **extra}
    return engine.create_entry(tx, clf.classify(desc, amount, typ))


def _lines(k):
    return {s.hesap_kodu: (s.borc, s.alacak) for s in k.satirlar}


def test_the_client_books_the_gross_fee_the_kdv_and_the_stopaj_owed() -> None:
    """e-SMM, client side: fee 1 000, KDV 200, stopaj 200, paid 1 000."""
    k = _k(DoubleEntryEngine(), THPClassifier(), "e-SMM CDE1: 9876543210 — Hukuki danışmanlık",
           100_000, "expense", kdv_kurus=20_000, stopaj_kurus=20_000)
    lines = _lines(k)
    assert lines[k.thp_hesap_kodu] == (100_000, 0), "gider brüt ücret olmalı"
    assert lines["191"] == (20_000, 0)
    assert lines["360"] == (0, 20_000)
    assert lines["102"] == (0, 100_000)
    assert k.dengeli
    assert k.kdv_durumu == "ayrildi"
    assert "KDV ayrıştırılmadı" not in k.onay_neden


def test_the_professional_books_revenue_kdv_and_prepaid_stopaj(engine, clf) -> None:
    k = _k(engine, clf, "Serbest meslek satış geliri", 100_000, "income",
           kdv_kurus=20_000, stopaj_kurus=20_000)
    lines = _lines(k)
    assert lines["102"] == (100_000, 0)
    assert lines["193"] == (20_000, 0)
    assert lines["391"] == (0, 20_000)
    assert lines[k.thp_hesap_kodu] == (0, 100_000)
    assert k.dengeli


def test_a_stated_kdv_is_split_even_on_an_account_outside_the_list(engine, clf) -> None:
    """The document is right about its own KDV whatever account the
    classifier picked; the list only decides when to *ask* for one."""
    k = _k(engine, clf, "Ocak maaş ödemeleri", 12_000_00, "expense", kdv_kurus=2_000_00)
    assert k.kdv_durumu == "ayrildi"
    assert _lines(k)["191"] == (2_000_00, 0)
    assert k.dengeli


def test_no_stopaj_stated_means_none_booked(engine, clf) -> None:
    k = _k(engine, clf, "Ocak ofis kirası", 12_000_00, "expense", kdv_kurus=2_000_00)
    assert "360" not in _lines(k) and "193" not in _lines(k)


def test_ingestion_carries_the_invoice_kdv_only_when_nothing_else_is_in_play(monkeypatch) -> None:
    """GİB's own sample: a plain sale carries its KDV; a withheld one does not."""
    from pathlib import Path

    from app.agents.data_ingestion import _try_parse_ubl_xml
    from app.config import get_settings

    xml = Path(__file__).resolve().parent / "fixtures" / "gib_corpus" / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"
    sale = xml / "YTB_Satıs_EArşiv.xml"
    withheld = xml / "YTB_Tevkıfat_EArşiv.xml"
    if not sale.is_file():
        pytest.skip("GİB UBL-TR paketi yok")

    import re
    ours = "1234567808"
    monkeypatch.setattr(get_settings(), "gib_vkn", ours)

    def as_seller(p: Path) -> str:
        raw = p.read_text(encoding="utf-8")
        s = raw.index("<cac:AccountingSupplierParty>")
        e = raw.index("</cac:AccountingSupplierParty>")
        return raw[:s] + re.sub(r'(schemeID="VKN">)\d+', rf"\g<1>{ours}", raw[s:e]) + raw[e:]

    assert _try_parse_ubl_xml(as_seller(sale))[0]["kdv_cents"] == 30_000
    assert _try_parse_ubl_xml(as_seller(withheld))[0]["kdv_cents"] is None


def test_the_columns_exist_on_the_model_and_in_a_migration() -> None:
    from pathlib import Path

    from app.models.transaction import Transaction

    assert {"kdv_kurus", "stopaj_kurus"} <= set(Transaction.__table__.columns.keys())
    mig = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "035_transaction_tax_amounts.py"
    assert "kdv_kurus" in mig.read_text(encoding="utf-8")
