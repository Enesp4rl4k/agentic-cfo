"""An uploaded .xlsx or CSV is untrusted input: an .xlsx is a zip of XML (zip bomb, entity bomb).

It is read only in a child process (`sheet_isolation` / `sheet_child`, via `pdf_isolation.run_worker`) with caps
on size, zip members, total uncompressed size (from the directory AND while reading), rows, columns, cells and
CSV line length. Every refusal is a visible, specific message, Turkish then English, naming the limit.
Nothing here is a real bomb: inputs are a few hundred bytes, limits are lowered through the settings, and the
oversized cases are a zip whose DIRECTORY declares a huge size or a tiny cap.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import struct
import sys
import zipfile

import pytest

from app.agents.state import AgentRunConfig
from app.services import pdf_isolation, sheet_child, sheet_isolation
from app.services.ingest import readers
from app.services.ingest.table import OkunamayanDosya, satirlari_oku
from app.services.pdf_isolation import ingest_hata_metni
from app.services.sheet_isolation import SheetOkunamadi

openpyxl = pytest.importorskip("openpyxl")


def workbook(rows: list[list], extra_sheet: bool = False) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ekstre"
    for r in rows:
        ws.append(r)
    if extra_sheet:
        wb.create_sheet("Ikinci")["B2"] = "z"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


ROWS = [
    ["Banka", "Garanti"],
    [],
    ["Tarih", "Açıklama", "Borç", "Alacak"],
    [datetime.datetime(2026, 1, 5), "EFT Ödeme", 1500.5, None],
    [datetime.date(2026, 1, 6), "Maaş", None, 45000],
    [datetime.datetime(2026, 1, 7, 13, 45, 10), "Karma", True, "55.000,00"],
]


def limits(**override) -> dict[str, int]:
    base = {
        "max_bytes": 10 * 1024 * 1024, "max_uncompressed": 128 * 1024 * 1024, "max_zip_members": 500, "max_rows": 200_000,
        "max_columns": 256, "max_cells": 1_000_000, "max_csv_line_chars": 100_000,
    }
    return {**base, **override}


def use_limits(monkeypatch, **override) -> None:
    monkeypatch.setattr(sheet_isolation, "limits_from_settings", lambda: limits(**override))


def refusal(data: bytes, ext: str = "xlsx") -> SheetOkunamadi:
    with pytest.raises(SheetOkunamadi) as caught:
        satirlari_oku(data, ext)
    return caught.value


# ── No parsing regression: the child returns what openpyxl / csv return in process ─────────

def test_xlsx_rows_equal_what_openpyxl_reads_in_process():
    data = workbook(ROWS, extra_sheet=True)
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    expected = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    assert satirlari_oku(data, "xlsx") == expected


def test_cell_types_survive_the_json_hop():
    data = workbook([[datetime.time(10, 30), datetime.timedelta(hours=2, seconds=3), "Şğüİ", 2**40, 1e-7, True, None, "x"]])
    ((_, rows),) = satirlari_oku(data, "xlsx")
    assert rows == [[datetime.time(10, 30), datetime.timedelta(hours=2, seconds=3), "Şğüİ", 2**40, 1e-7, True, None, "x"]]


def test_csv_rows_and_windows_1254_equal_the_in_process_read():
    text = "Tarih;Açıklama;Tutar\n05.01.2026;Şirket ödemesi;1.250,00\n"
    for raw in (text.encode("utf-8-sig"), text.encode("cp1254")):
        assert satirlari_oku(raw, "csv") == [(None, [["Tarih", "Açıklama", "Tutar"], ["05.01.2026", "Şirket ödemesi", "1.250,00"]])]


def test_read_excel_text_matches_the_old_in_process_text(tmp_path):
    path = tmp_path / "a.xlsx"
    path.write_bytes(workbook(ROWS))
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    old = "\n".join(
        "\t".join(str(c) if c is not None else "" for c in r)
        for ws in wb.worksheets for r in ws.iter_rows(values_only=True) if any(str(c) if c is not None else "" for c in r)
    )
    assert readers._read_excel(str(path)) == old


# ── Zip bombs: the directory, then the bytes as they are read ───────────────────────────────

def lie_about_size(data: bytes, declared: int) -> bytes:
    """A zip whose central DIRECTORY claims every member is `declared` bytes (the members themselves are tiny)."""
    out = bytearray(data)
    at = out.find(b"PK\x01\x02")
    while at != -1:
        out[at + 24: at + 28] = struct.pack("<I", declared)
        at = out.find(b"PK\x01\x02", at + 4)
    return bytes(out)


def test_a_directory_declaring_a_huge_size_is_refused_before_anything_is_read():
    exc = refusal(lie_about_size(workbook(ROWS), 3_000_000_000))
    assert exc.code == "sheet_uncompressed_too_large"
    assert "SHEET_MAX_UNCOMPRESSED_MB" in exc.tr and "128" in exc.tr and "128 MB" in exc.en
    assert "\n" in str(exc) and str(exc) == exc.user_text   # Turkish, then English


def test_too_many_zip_members_is_refused(monkeypatch):
    use_limits(monkeypatch, max_zip_members=3)
    exc = refusal(workbook(ROWS))
    assert exc.code == "sheet_too_many_members" and "SHEET_MAX_ZIP_MEMBERS" in exc.tr and "3" in exc.en


def test_total_uncompressed_size_is_counted_while_members_are_read_too():
    """The directory is not trusted: with the directory check skipped (as if it lied low) the reads are counted."""
    data = workbook(ROWS)
    with pytest.raises(sheet_child.SheetLimit) as caught:
        sheet_child.read_xlsx(data, limits(max_uncompressed=500), check_directory=False)
    assert caught.value.code == "sheet_uncompressed_too_large"
    assert len(sheet_child.read_xlsx(data, limits(), check_directory=False)[0]["rows"]) == len(ROWS)


def test_the_counting_reader_counts_every_read_style():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a", b"x" * 100 + b"\n" + b"y" * 100)
    for how in ("read", "read1", "readline", "iter"):
        with sheet_child.counting_zip_reads(150), zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf, zf.open("a") as member:
            with pytest.raises(sheet_child.SheetLimit):
                if how == "iter":
                    list(member)
                elif how == "readline":
                    [member.readline() for _ in range(2)]
                else:
                    getattr(member, how)(-1)


def test_a_file_over_the_size_cap_is_refused_without_starting_a_child(monkeypatch):
    use_limits(monkeypatch, max_bytes=1024)
    monkeypatch.setattr(pdf_isolation, "run_worker", lambda *a, **k: pytest.fail("a child was started"))
    exc = refusal(b"x" * 2048, "csv")
    assert exc.code == "sheet_too_large" and "MAX_UPLOAD_SIZE_MB" in exc.tr


# ── XML entities: defusedxml is active and a declaration is refused ─────────────────────────

def with_member(data: bytes, name: str, transform) -> bytes:
    assert name in zipfile.ZipFile(io.BytesIO(data)).namelist(), f"{name} is not in the generated workbook"
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            body = zin.read(info.filename)
            zout.writestr(info.filename, transform(body) if info.filename == name else body)
    return out.getvalue()


def add_entity(body: bytes) -> bytes:
    declaration = body.find(b"?>")
    at = declaration + 2 if declaration != -1 else 0
    return body[:at] + b'<!DOCTYPE x [<!ENTITY a "b">]>' + body[at:]


@pytest.mark.parametrize("member", ["xl/worksheets/sheet1.xml", "xl/workbook.xml", "[Content_Types].xml"])
def test_an_xml_entity_declaration_in_any_part_is_refused(member):
    exc = refusal(with_member(workbook(ROWS), member, add_entity))
    assert exc.code == "sheet_unsafe_xml" and "XML" in exc.tr and "XML" in exc.en


def test_defusedxml_is_active_and_a_missing_one_refuses_instead_of_falling_back(monkeypatch):
    from openpyxl import xml as openpyxl_xml

    assert openpyxl_xml.DEFUSEDXML is True
    monkeypatch.setattr(openpyxl_xml, "DEFUSEDXML", False)
    with pytest.raises(sheet_child.SheetLimit):
        sheet_child.read_xlsx(workbook(ROWS), limits())


# ── Rows, columns, cells, CSV lines: refused with the limit named, never truncated ──────────

@pytest.mark.parametrize(("override", "code", "setting"), [
    ({"max_rows": 2}, "sheet_too_many_rows", "SHEET_MAX_ROWS"),
    ({"max_columns": 2}, "sheet_too_many_columns", "SHEET_MAX_COLUMNS"),
    ({"max_cells": 5}, "sheet_too_many_cells", "SHEET_MAX_CELLS"),
])
@pytest.mark.parametrize("ext", ["xlsx", "csv"])
def test_row_column_and_cell_caps_refuse_the_file(monkeypatch, override, code, setting, ext):
    use_limits(monkeypatch, **override)
    data = workbook(ROWS) if ext == "xlsx" else b"a,b,c\n1,2,3\n4,5,6\n7,8,9\n"
    exc = refusal(data, ext)
    assert exc.code == code and setting in exc.tr
    assert str(next(iter(override.values()))) in exc.tr and str(next(iter(override.values()))) in exc.en


def test_a_csv_line_over_the_cap_is_refused_with_the_limit_named(monkeypatch):
    use_limits(monkeypatch, max_csv_line_chars=50)
    exc = refusal(b"a,b\n" + b"x" * 60 + b",1\n", "csv")
    assert exc.code == "csv_line_too_long" and "SHEET_MAX_CSV_LINE_CHARS" in exc.tr and "50" in exc.en


def test_the_door_text_reader_caps_size_and_line_length(tmp_path, monkeypatch):
    use_limits(monkeypatch, max_bytes=1024, max_csv_line_chars=50)
    long_line = tmp_path / "long.csv"
    long_line.write_bytes(b"a,b\n" + b"x" * 60 + b"\n")
    with pytest.raises(SheetOkunamadi) as caught:
        readers._read_csv(str(long_line))
    assert caught.value.code == "csv_line_too_long"
    big = tmp_path / "big.csv"
    big.write_bytes(b"a,b\n" * 1000)
    with pytest.raises(SheetOkunamadi) as caught:
        readers._read_csv(str(big))
    assert caught.value.code == "sheet_too_large"


def test_a_damaged_or_password_protected_workbook_is_refused_not_crashed():
    exc = refusal(b"PK\x03\x04 this is not a zip")
    assert exc.code == "sheet_unreadable" and "parola" in exc.tr and "password" in exc.en


def test_the_xls_format_still_gets_its_own_instruction():
    with pytest.raises(OkunamayanDosya, match=r"\.xls"):
        satirlari_oku(b"\xd0\xcf\x11\xe0", "xls")


# ── The mechanism: timeout, flood, busy ─────────────────────────────────────────────────────

def fake_child(monkeypatch, code: str) -> None:
    monkeypatch.setattr(sheet_isolation, "_WORKER_COMMAND", [sys.executable, "-c", code])


def test_a_child_over_its_deadline_is_killed_and_the_refusal_names_the_limit(monkeypatch):
    from app.config import get_settings

    fake_child(monkeypatch, "import time; time.sleep(60)")
    monkeypatch.setattr(get_settings(), "sheet_parse_timeout_seconds", 1)
    exc = refusal(b"a,b\n1,2\n", "csv")
    assert exc.code == "sheet_timeout" and "SHEET_PARSE_TIMEOUT_SECONDS" in exc.tr and "1 second" in exc.en


def test_a_child_that_floods_stdout_is_killed_and_refused(monkeypatch):
    fake_child(monkeypatch, "import sys; sys.stdout.write('x' * 2_000_000)")
    monkeypatch.setattr(pdf_isolation, "_STDOUT_LIMIT", 100_000)
    assert refusal(b"a,b\n1,2\n", "csv").code == "sheet_output_too_large"


def test_a_child_that_crashes_or_returns_garbage_is_a_refusal_never_an_empty_table(monkeypatch):
    fake_child(monkeypatch, "import sys; sys.exit(3)")
    assert refusal(b"a,b\n", "csv").code == "sheet_unreadable"
    fake_child(monkeypatch, "print('not json')")
    assert refusal(b"a,b\n", "csv").code == "sheet_unreadable"
    fake_child(monkeypatch, "print('[1, 2]')")
    assert refusal(b"a,b\n", "csv").code == "sheet_unreadable"


def test_a_waiter_gives_up_with_a_busy_refusal_instead_of_hanging(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "pdf_parse_concurrency", 1)
    monkeypatch.setattr(settings, "parse_queue_wait_seconds", 0)
    monkeypatch.setattr(pdf_isolation, "_slots", None)
    with pdf_isolation._slot():
        exc = refusal(b"a,b\n1,2\n", "csv")
    assert exc.code == "sheet_busy" and "Sistem yoğun, tekrar deneyin" in exc.tr and "busy" in exc.en
    assert satirlari_oku(b"a,b\n1,2\n", "csv") == [(None, [["a", "b"], ["1", "2"]])]   # the slot came back


# ── A refused file reaches the run as a sentence, not "Ingestion error: ..." ────────────────

def test_a_refused_workbook_is_a_visible_halt_from_the_door_to_the_run(tmp_path, monkeypatch):
    import app.agents.data_ingestion as di

    path = tmp_path / "bomb.xlsx"
    path.write_bytes(lie_about_size(workbook(ROWS), 3_000_000_000))
    result = asyncio.run(di._belgeyi_oku(str(path), "xlsx", {}, AgentRunConfig(), None))
    assert result.ok is False and result.halt is True
    assert result.detail == ingest_hata_metni(SheetOkunamadi("sheet_uncompressed_too_large", limit_mb=128))
    assert not result.detail.startswith("Ingestion error") and "SHEET_MAX_UNCOMPRESSED_MB" in result.detail
    assert "Open it in Excel" in result.detail   # what to do, in English too
