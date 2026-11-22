"""Tabular statements the way people export them: sign, Excel, Turkish bank columns.

Found by running a 6,000-row statement through the live API:
- a CSV without a type column booked every payment as revenue, because the
  amount's minus sign was dropped before the sign decided the type;
- an .xlsx with the same columns was never read by rules — the sheet is read
  tab-separated and only commas were tried — so it went to the model, and
  with no model it produced no transactions at all;
- a bank's own "İşlem Tarihi / Borç / Alacak" export did not match either.
"""
from __future__ import annotations

import pytest

from app.agents.data_ingestion import _parse_date, _try_parse_csv, run_data_ingestion
from app.agents.state import AgentRunConfig


def _rows(text: str):
    return [(r["type"], r["amount_cents"], r["transaction_date"][:10] if r["transaction_date"] else None)
            for r in _try_parse_csv(text) or []]


def test_a_payment_without_a_type_column_is_an_expense():
    text = ('tarih,açıklama,tutar,bakiye\n2024-01-05,Ofis Kirası,"-28.500,00","71.500,00"\n'
            '2024-01-06,Satış,"10.000,00","81.500,00"\n'
            '2024-01-07,Kira,"-1.500,00","80.000,00"\n')
    assert _rows(text) == [("expense", 2_850_000, "2024-01-05"), ("income", 1_000_000, "2024-01-06"),
                           ("expense", 150_000, "2024-01-07")]


@pytest.mark.parametrize("written", ["-1.500,00", "1.500,00-", "(1.500,00)"])
def test_every_way_of_writing_money_out(written):
    # among a statement's usual mixed signs (a file of only negatives has no direction: it is asked)
    text = (f'tarih;açıklama;tutar;bakiye\n05.01.2024;Kira;{written};8.500,00\n'
            '06.01.2024;Satış;2.000,00;10.500,00\n'
            '07.01.2024;Satış;500,00;11.000,00\n')
    assert _rows(text) == [("expense", 150_000, "2024-01-05"), ("income", 200_000, "2024-01-06"),
                           ("income", 50_000, "2024-01-07")]


def test_a_sheet_read_tab_separated_with_excel_dates_and_numbers():
    text = ("tarih\taçıklama\ttutar\tbakiye\n2024-01-05 00:00:00\tOfis Kirası\t-28500.0\t71500.0\n"
            "2024-01-06 00:00:00\tSatış\t1500\t73000.0\n"
            "2024-01-07 00:00:00\tKira\t-500\t72500.0\n")
    assert _rows(text) == [("expense", 2_850_000, "2024-01-05"), ("income", 150_000, "2024-01-06"),
                           ("expense", 50_000, "2024-01-07")]


def test_a_bank_export_with_debit_and_credit_columns():
    text = ("İşlem Tarihi;Açıklama;Borç;Alacak;Bakiye\n"
            "05.01.2024;Kira;28.500,00;;100.000,00\n"
            "06.01.2024;EFT gelen;;10.000,00;110.000,00\n"
            "07.01.2024;Kira;5.000,00;;105.000,00\n")
    assert _rows(text) == [("expense", 2_850_000, "2024-01-05"), ("income", 1_000_000, "2024-01-06"),
                           ("expense", 500_000, "2024-01-07")]


def test_a_running_balance_alone_is_not_an_amount():
    assert _try_parse_csv("tarih;bakiye\n05.01.2024;100.000,00\n") is None


@pytest.mark.parametrize("header", ["DATE,DESCRIPTION,AMOUNT,BALANCE", "TARİH,AÇIKLAMA,TUTAR,BAKİYE"])
def test_capitalised_headers(header):
    got = _try_parse_csv(f"{header}\n2024-01-05,Kira,-100,900\n2024-01-06,Satış,300,1200\n2024-01-07,Gaz,-50,1150\n")
    assert got and got[0]["type"] == "expense" and got[0]["description"] == "Kira"


def test_excel_datetime_text_parses():
    assert _parse_date("2024-01-03 00:00:00").date().isoformat() == "2024-01-03"


@pytest.mark.asyncio
async def test_an_xlsx_statement_is_read_by_rules_not_the_model(tmp_path, monkeypatch):
    from openpyxl import Workbook

    async def no_model(*_a, **_k):
        raise AssertionError("the model was asked to read a well-formed sheet")

    monkeypatch.setattr("app.agents.data_ingestion._extract_transactions_with_llm", no_model)
    wb = Workbook()
    ws = wb.active
    ws.append(["Tarih", "Açıklama", "Tutar", "Bakiye"])
    ws.append(["2024-01-05", "Ofis kirası", -28500, 71500])
    ws.append(["2024-01-06", "Müşteri tahsilatı", 10000.5, 81500.5])
    ws.append(["2024-01-07", "Kira", -1000, 80500.5])
    path = tmp_path / "ekstre.xlsx"
    wb.save(path)

    result = await run_data_ingestion({"file_path": str(path), "file_type": "xlsx", "job_id": "j"}, AgentRunConfig())
    txs = result.patch["transactions"]
    assert [(t["type"], t["amount_cents"]) for t in txs] == [("expense", 2_850_000), ("income", 1_000_050), ("expense", 100_000)]


@pytest.mark.asyncio
async def test_a_bank_name_inside_a_row_does_not_hijack_the_table(tmp_path, monkeypatch):
    """One "AKBANK EFT" line sent a whole Garanti CSV through Akbank's PDF-text
    pattern, which lost the empty cells and swapped debit for credit."""
    async def no_model(*_a, **_k):
        raise AssertionError("a well-formed table went to the model")

    monkeypatch.setattr("app.agents.data_ingestion._extract_transactions_with_llm", no_model)
    path = tmp_path / "garanti.csv"
    path.write_text(
        "Tarih;Açıklama;Borç;Alacak;Bakiye\n"
        "05.01.2024;AKBANK EFT - kira;28.500,00;;100.000,00\n"
        "06.01.2024;Müşteri tahsilatı;;10.000,00;110.000,00\n"
        "07.01.2024;Kira;5.000,00;;105.000,00\n",
        encoding="utf-8",
    )
    result = await run_data_ingestion({"file_path": str(path), "file_type": "csv", "job_id": "j"}, AgentRunConfig())
    assert [(t["type"], t["amount_cents"]) for t in result.patch["transactions"]] == [
        ("expense", 2_850_000), ("income", 1_000_000), ("expense", 500_000)]
