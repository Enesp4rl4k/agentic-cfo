"""Bank-statement workbooks, read to the parsed-ledger level (date, amount, description, type per row).

The repo had no .xlsx fixtures, so the spreadsheet child's one deliberate change (trailing empty cells are
dropped, rows padded back to the widest real row) was proved on raw rows only. Here four statement layouts
(header narrower than the data rows, an empty last "Açıklama" column, merged header cells, a statement on the
second sheet) are read through `_tablo_ekstresi` twice: with the isolated child, and with the OLD in-process
reader (openpyxl straight, every padded cell kept). The ledgers must be identical and equal the committed ones.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.services.ingest import recognize, rows
from app.services.ingest.table import satirlari_oku

FIXTURES = Path(__file__).parent / "fixtures" / "xlsx_statements"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
NAMES = sorted(EXPECTED)


def old_in_process_reader(veri: bytes, uzanti: str):
    """The reader as it was before the child: openpyxl in this process, trailing padding kept."""
    wb = openpyxl.load_workbook(io.BytesIO(veri), read_only=True, data_only=True)
    try:
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    finally:
        wb.close()


def ledger(path: Path) -> list[dict]:
    return [
        {"date": r.get("transaction_date"), "amount_cents": r.get("amount_cents"), "description": r.get("description"), "type": r.get("type")}
        for r in rows._tablo_ekstresi(str(path)) or []
    ]


def test_the_fixtures_exist_and_cover_the_four_layouts():
    assert NAMES == ["empty_last_aciklama.xlsx", "merged_header.xlsx", "ragged_header.xlsx", "two_sheets.xlsx"]
    assert [len(EXPECTED[n]) for n in NAMES] == [5, 3, 3, 3]


@pytest.mark.parametrize("name", NAMES)
def test_the_ledger_read_through_the_child_equals_the_committed_one(name):
    assert ledger(FIXTURES / name) == EXPECTED[name]


@pytest.mark.parametrize("name", NAMES)
def test_the_old_in_process_reader_gives_the_same_raw_rows_and_the_same_ledger(name, monkeypatch):
    data = (FIXTURES / name).read_bytes()
    assert satirlari_oku(data, "xlsx") == old_in_process_reader(data, "xlsx")
    monkeypatch.setattr(recognize, "satirlari_oku", old_in_process_reader)
    assert ledger(FIXTURES / name) == EXPECTED[name]


def test_amounts_dates_and_descriptions_are_the_ones_in_the_workbook():
    """Spot checks written by hand, not derived from the reader."""
    by = {n: EXPECTED[n] for n in NAMES}
    assert [(r["amount_cents"], r["description"]) for r in by["ragged_header.xlsx"]] == [
        (1450000, "EFT Kira Ödemesi"), (2200000, "Havale Gelen Müşteri"), (8735, "POS Komisyon")]
    assert [r["description"] for r in by["empty_last_aciklama.xlsx"]] == ["Kira ödemesi", "", "POS komisyon", "", ""]   # the empty ones stay rows
    assert [r["type"] for r in by["empty_last_aciklama.xlsx"]] == ["expense", "income", "expense", "expense", "income"]
    assert by["merged_header.xlsx"][1]["amount_cents"] == 3650050
    assert by["two_sheets.xlsx"][1]["amount_cents"] == 420075 and by["two_sheets.xlsx"][1]["type"] == "expense"
