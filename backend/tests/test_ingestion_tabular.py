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
    text = 'tarih,açıklama,tutar\n2024-01-05,Ofis Kirası,"-28.500,00"\n2024-01-06,Satış,"10.000,00"\n'
    assert _rows(text) == [("expense", 2_850_000, "2024-01-05"), ("income", 1_000_000, "2024-01-06")]


@pytest.mark.parametrize("written", ["-1.500,00", "1.500,00-", "(1.500,00)"])
def test_every_way_of_writing_money_out(written):
    text = f'tarih;açıklama;tutar\n05.01.2024;Kira;{written}\n'
    assert _rows(text) == [("expense", 150_000, "2024-01-05")]


def test_a_sheet_read_tab_separated_with_excel_dates_and_numbers():
    text = "tarih\taçıklama\ttutar\n2024-01-05 00:00:00\tOfis Kirası\t-28500.0\n2024-01-06 00:00:00\tSatış\t1500\n"
    assert _rows(text) == [("expense", 2_850_000, "2024-01-05"), ("income", 150_000, "2024-01-06")]


def test_a_bank_export_with_debit_and_credit_columns():
    text = ("İşlem Tarihi;Açıklama;Borç;Alacak;Bakiye\n"
            "05.01.2024;Kira;28.500,00;;100.000,00\n"
            "06.01.2024;EFT gelen;;10.000,00;110.000,00\n")
    assert _rows(text) == [("expense", 2_850_000, "2024-01-05"), ("income", 1_000_000, "2024-01-06")]


def test_a_running_balance_alone_is_not_an_amount():
    assert _try_parse_csv("tarih;bakiye\n05.01.2024;100.000,00\n") is None


@pytest.mark.parametrize("header", ["DATE,DESCRIPTION,AMOUNT", "TARİH,AÇIKLAMA,TUTAR"])
def test_capitalised_headers(header):
    got = _try_parse_csv(f"{header}\n2024-01-05,Kira,-100\n")
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
    ws.append(["Tarih", "Açıklama", "Tutar"])
    ws.append(["2024-01-05", "Ofis kirası", -28500])
    ws.append(["2024-01-06", "Müşteri tahsilatı", 10000.5])
    path = tmp_path / "ekstre.xlsx"
    wb.save(path)

    result = await run_data_ingestion({"file_path": str(path), "file_type": "xlsx", "job_id": "j"}, AgentRunConfig())
    txs = result.patch["transactions"]
    assert [(t["type"], t["amount_cents"]) for t in txs] == [("expense", 2_850_000), ("income", 1_000_050)]
