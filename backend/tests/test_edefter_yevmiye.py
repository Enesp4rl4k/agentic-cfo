"""Yevmiye → accrual income statement.

Nothing here read a company's own e-Defter: the journal went through /baglan
and the analysis ended with no transactions. The owner chose the accrual basis
(2026-09-27): income and expense accounts, not cash accounts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parsers.edefter.yevmiye import NotAJournal, yevmiye_oku

GIB_Y = (Path(__file__).parent / "fixtures" / "gib_corpus" / "e_defter" / "e-Defter Paketi" / "xml"
         / "1234567808-201804-Y-000000.xml")


def _yevmiye(*kayitlar: list[tuple[str, str, str]], tur: str = "journal", kok: str = "defter") -> bytes:
    """A journal with the given entries: each entry is [(account, D|C, amount)]."""
    govde = []
    for n, satirlar in enumerate(kayitlar, start=1):
        detay = "".join(
            f"<gl-cor:entryDetail><gl-cor:account><gl-cor:accountMainID>{h}</gl-cor:accountMainID>"
            f"</gl-cor:account><gl-cor:amount>{t}</gl-cor:amount>"
            f"<gl-cor:debitCreditCode>{dc}</gl-cor:debitCreditCode>"
            f"<gl-cor:postingDate>2026-03-{n:02d}</gl-cor:postingDate></gl-cor:entryDetail>"
            for h, dc, t in satirlar
        )
        govde.append(f"<gl-cor:entryHeader><gl-cor:entryNumber>{n:06d}</gl-cor:entryNumber>"
                     f"<gl-cor:entryComment>kayıt {n}</gl-cor:entryComment>{detay}</gl-cor:entryHeader>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<edefter:{kok} xmlns:edefter="http://www.edefter.gov.tr" '
        'xmlns:gl-cor="http://www.xbrl.org/int/gl/cor/2006-10-25"><gl-cor:accountingEntries>'
        f"<gl-cor:documentInfo><gl-cor:entriesType>{tur}</gl-cor:entriesType></gl-cor:documentInfo>"
        + "".join(govde) + f"</gl-cor:accountingEntries></edefter:{kok}>"
    ).encode("utf-8")


def _ozet(sonuc) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for t in sonuc.islemler:
        out[(t["type"], t["category"])] = out.get((t["type"], t["category"]), 0) + t["amount_cents"]
    return out


def test_a_sale_is_income_when_invoiced_and_its_cost_an_expense():
    s = yevmiye_oku(_yevmiye(
        [("120", "D", "1200"), ("600", "C", "1000"), ("391", "C", "200")],   # sale on credit
        [("621", "D", "600"), ("153", "C", "600")],                          # its cost
    ))
    assert _ozet(s) == {("income", "revenue"): 100_000, ("expense", "cogs"): 60_000}
    assert all(t["basis"] == "tahakkuk" for t in s.islemler)


def test_balance_sheet_lines_are_not_income_statement_events():
    s = yevmiye_oku(_yevmiye([("102", "D", "5000"), ("120", "C", "5000")]))   # a customer pays
    assert s.islemler == []


def test_a_correction_reduces_rather_than_adds():
    s = yevmiye_oku(_yevmiye(
        [("770", "D", "300"), ("100", "C", "300")],
        [("100", "D", "50"), ("770", "C", "50")],      # part of it refunded
        [("600", "D", "80"), ("120", "C", "80")],      # a sale reversed
    ))
    ozet = _ozet(s)
    assert ozet[("expense", "other_expense")] == 25_000
    assert ozet[("income", "revenue")] == -8_000


def test_sales_deductions_reduce_revenue():
    s = yevmiye_oku(_yevmiye([("610", "D", "100"), ("120", "C", "100")]))  # a return
    assert _ozet(s) == {("income", "revenue"): -10_000}


def test_a_7a_transfer_is_not_counted_twice():
    s = yevmiye_oku(_yevmiye(
        [("770", "D", "400"), ("320", "C", "400")],     # expense recorded in 7/A
        [("632", "D", "400"), ("771", "C", "400")],     # month-end transfer into 6xx
    ))
    assert _ozet(s) == {("expense", "other_expense"): 40_000}
    assert s.atlanan_kayit == 1


def test_the_closing_entry_is_skipped():
    s = yevmiye_oku(_yevmiye(
        [("600", "C", "1000"), ("120", "D", "1000")],
        [("600", "D", "1000"), ("690", "C", "1000")],   # closing revenue into 690
    ))
    assert _ozet(s) == {("income", "revenue"): 100_000}
    assert s.atlanan_kayit == 1


def test_an_unknown_income_statement_account_is_reported_not_guessed():
    s = yevmiye_oku(_yevmiye([("699", "D", "10"), ("100", "C", "10")]))
    assert s.islemler == [] and s.tanimsiz_hesaplar == ["699"]


@pytest.mark.parametrize("tur,kok", [("ledger", "defter"), ("assets", "defter"), ("", "berat")])
def test_only_a_journal_is_read(tur, kok):
    with pytest.raises(NotAJournal):
        yevmiye_oku(_yevmiye([("600", "C", "1")], tur=tur, kok=kok))


@pytest.mark.skipif(not GIB_Y.exists(), reason="GİB korpusu yerelde yok")
def test_gibs_own_journal_gives_the_expected_income_statement():
    s = yevmiye_oku(GIB_Y.read_bytes())
    assert _ozet(s) == {
        ("income", "revenue"): 4_237_300,        # 600 C 42.373,00 — mamul satışı
        ("expense", "cogs"): 3_000_000,          # 620 D 30.000,00
        ("expense", "other_expense"): 12_712,    # 770 D 127,12 — kırtasiye
    }
    assert s.kayit_sayisi == 11 and s.tanimsiz_hesaplar == []


async def test_a_cash_flow_built_from_accrual_rows_says_so():
    """Accrual rows classified as cash make a "cash flow" that is really profit."""
    from app.agents.cashflow_agent import run_cashflow

    s = yevmiye_oku(_yevmiye([("120", "D", "1000"), ("600", "C", "1000")]))
    out = await run_cashflow({"transactions": s.islemler, "job_id": "j"}, None)
    cf = out.patch["cashflow"]
    assert cf["esas"] == "tahakkuk"
    assert "gerçek nakit hareketi değildir" in cf["alerts"][0]["message"]
