"""Generates the four small bank-statement workbooks next to this file (benign, hand-sized data).

    python backend/tests/fixtures/xlsx_statements/make_fixtures.py

The workbooks are committed because the repo had no .xlsx fixtures: `test_xlsx_statement_fixtures.py` reads
them to the parsed-ledger level (date, amount, description per row), and proves that the spreadsheet child,
which drops trailing empty cells, gives the same ledger as the old in-process reader that kept them.
The expected ledgers are in `expected.json` (regenerate with `--expected` after reading the diff).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
D = dt.datetime


def ragged_header() -> openpyxl.Workbook:
    """Title rows above a header that is NARROWER than the data rows: the balance sits in an unheaded column."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hesap Hareketleri"
    ws.append(["GARANTİ BBVA - Hesap Ekstresi"])
    ws.append(["Hesap sahibi: Örnek Ticaret A.Ş.", None, None, None, None])
    ws.append(["IBAN: TR33 0006 1005 1978 6457 8413 26"])
    ws.append([])
    ws.append(["Tarih", "Açıklama", "Borç", "Alacak"])
    ws.append([D(2026, 1, 5), "EFT Kira Ödemesi", 14500.00, None, 85500.00])
    ws.append([D(2026, 1, 7), "Havale Gelen Müşteri", None, 22000.00, 107500.00])
    ws.append([D(2026, 1, 9), "POS Komisyon", 87.35, None, 107412.65])
    return wb


def empty_last_aciklama() -> openpyxl.Workbook:
    """The description is the LAST column and is empty on some rows: those rows end early (trailing empties)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ekstre"
    ws.append(["Tarih", "Tutar", "Bakiye", "Açıklama"])
    ws.append(["05.01.2026", "-14.500,00", "85.500,00", "Kira ödemesi"])
    ws.append(["07.01.2026", "22.000,00", "107.500,00", None])
    ws.append(["09.01.2026", "-87,35", "107.412,65", "POS komisyon"])
    ws.append(["12.01.2026", "-1.250,00", "106.162,65", None])
    ws.append(["15.01.2026", "5.000,00", "111.162,65", ""])
    return wb


def merged_header() -> openpyxl.Workbook:
    """A merged title across the sheet and merged group headers over the real column header row."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ekstre"
    ws.append(["AKBANK - Cari Hesap Ekstresi", None, None, None, None])
    ws.merge_cells("A1:E1")
    ws.append(["Dönem: Ocak 2026", None, None, None, None])
    ws.append(["", "İşlem Bilgisi", None, "Tutar Bilgisi", None])
    ws.merge_cells("B3:C3")
    ws.merge_cells("D3:E3")
    ws.append(["Tarih", "Açıklama", "Referans", "Borç", "Alacak"])
    ws.append([D(2026, 1, 3), "Maaş Ödemesi Personel", "REF001", 48000.00, None])
    ws.append([D(2026, 1, 4), "Tahsilat ABC Ltd", "REF002", None, 36500.50])
    ws.append([D(2026, 1, 11), "Elektrik Faturası", "REF003", 2310.20, None])
    return wb


def two_sheets() -> openpyxl.Workbook:
    """A summary sheet first, the statement on the second sheet."""
    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Özet"
    summary.append(["Rapor", "Ocak 2026"])
    summary.append(["Toplam işlem sayısı", 3])
    ws = wb.create_sheet("Hareketler")
    ws.append(["İşlem Tarihi", "Açıklama", "Tutar", "Bakiye"])
    ws.append([D(2026, 1, 2), "Müşteri Tahsilatı", 15000.00, 115000.00])
    ws.append([D(2026, 1, 6), "Tedarikçi Ödemesi", -4200.75, 110799.25])
    ws.append([D(2026, 1, 8), "Vergi Ödemesi", -980.00, 109819.25])
    return wb


BUILDERS = {
    "ragged_header.xlsx": ragged_header, "empty_last_aciklama.xlsx": empty_last_aciklama,
    "merged_header.xlsx": merged_header, "two_sheets.xlsx": two_sheets,
}


def write_workbooks() -> None:
    for name, build in BUILDERS.items():
        build().save(HERE / name)


def ledger_of(path: Path) -> list[dict]:
    from app.services.ingest.rows import _tablo_ekstresi

    rows = _tablo_ekstresi(str(path)) or []
    return [{"date": r.get("transaction_date"), "amount_cents": r.get("amount_cents"), "description": r.get("description"),
             "type": r.get("type")} for r in rows]


if __name__ == "__main__":
    import json

    sys.path.insert(0, str(HERE.parents[2]))
    write_workbooks()
    if "--expected" in sys.argv:
        expected = {name: ledger_of(HERE / name) for name in BUILDERS}
        (HERE / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
