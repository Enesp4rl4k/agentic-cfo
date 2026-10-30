"""Plan v8 §A1 — what an account code says, for every source that names one."""
from __future__ import annotations

import pytest

from app.core import tdhp
from app.parsers.accounting.logo_tiger import LogoTigerParser
from app.parsers.accounting.netsis import NetsisParser


@pytest.mark.parametrize(("kod", "rol", "kategori"), [
    ("600", "gelir", "revenue"),
    ("600.01.001", "gelir", "revenue"),
    ("610", "gelir_indirimi", "revenue"),
    ("642", "gelir", "other_income"),
    ("622", "gider", "cogs"),
    ("770", "gider", "other_expense"),
    ("691", "gider", "tax"),
    ("771", "yansitma", "transfer"),
    ("690", "kapanis", "transfer"),
    ("191", "bilanco", "tax_payment"),
    ("360", "bilanco", "tax_payment"),
    ("193", "bilanco", "tax_payment"),
    ("300", "bilanco", "transfer"),
    ("255", "bilanco", "transfer"),
])
def test_the_account_decides_the_role(kod, rol, kategori):
    h = tdhp.hesap(kod)
    assert h is not None and (h.rol, h.kategori) == (rol, kategori)


@pytest.mark.parametrize("kod", ["701", "800", "", "abc"])
def test_an_unknown_or_unreadable_account_is_not_guessed(kod):
    assert tdhp.hesap(kod) is None


def test_a_debit_on_a_sales_account_is_a_correction_that_reduces_revenue():
    assert tdhp.hareket(tdhp.hesap("600"), 50_00, 0) == ("income", -50_00)
    assert tdhp.hareket(tdhp.hesap("610"), 20_00, 0) == ("income", -20_00)


def test_a_paid_liability_is_cash_out_and_a_loan_drawn_is_cash_in():
    assert tdhp.hareket(tdhp.hesap("360"), 18_00, 0) == ("expense", 18_00)
    assert tdhp.hareket(tdhp.hesap("300"), 0, 500_00) == ("income", 500_00)


def test_transfer_postings_are_not_read():
    assert tdhp.hareket(tdhp.hesap("771"), 10_00, 0) is None


_LOGO = (
    "Tarih;Fiş No;Hesap Kodu;Açıklama;Borç;Alacak\n"
    "02.01.2024;G001;600;Lisans Geliri;;1000,00\n"
    "05.01.2024;F001;770;Kira;200,00;\n"
    "06.01.2024;F002;771;GYG Yansıtma;;200,00\n"
)


@pytest.mark.parametrize("parser", [LogoTigerParser, NetsisParser])
def test_accounting_parsers_read_sales_as_income_and_cost_accounts_as_expense(parser):
    """They read 6xx as expense and 7xx as revenue — the plan says the opposite."""
    rows = [(t.tx_type, t.amount_cents, t.account_code) for t in parser()._parse_csv(_LOGO)]
    assert ("income", 1000_00, "600") in rows
    assert ("expense", 200_00, "770") in rows
    assert all(code != "771" for *_, code in rows)


def test_erp_sync_classifies_by_the_account_and_never_across_directions():
    from app.services.classifier import classify_posting

    assert classify_posting("Ocak Maaş - Satış Ekibi", "expense") == "salary"
    assert classify_posting("Satış Ekibi Yemek", "expense") == "other_expense"
    assert classify_posting("Lisans", "income", "600") == "revenue"
    assert classify_posting("Google Ads", "expense", "760") == "marketing"
    assert classify_posting("Danışman", "expense", "770") == "other_expense"
    assert classify_posting("KDV Ödemesi", "expense", "360") == "tax_payment"
    assert classify_posting("KDV Ödemesi", "expense") == "tax_payment"
