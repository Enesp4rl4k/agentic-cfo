"""The parsers of an uploaded file's bytes run only in the isolated child processes.

PyMuPDF, pdfplumber/pdfminer, Tesseract and Pillow decode attacker-controlled bytes in C or in code that has
had crashes and decompression bombs. They may be imported or called only by the modules below, which are the
child's code (or its entry point); the API and worker processes reach them through `pdf_isolation`.
A new use anywhere else fails here: put it behind the child, or add it to the list with the reason.

Spreadsheets are the same class: an .xlsx is a zip of XML (zip bomb, entity bomb), so openpyxl / xlrd /
`pandas.read_excel` / `load_workbook` of uploaded bytes run only in `sheet_child` (reached through
`sheet_isolation`). CSV parsing (`csv.reader`, `csv.DictReader`, `pandas.read_csv`) may appear only in the
modules listed in CSV_TEXT_LEVEL, each with the reason it is acceptable there.

Every `HTML(` call (WeasyPrint) must also pass a `url_fetcher`, so a fifth renderer cannot skip the
no-fetch rule (`app.services.pdf_fetch`).
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# module (relative to app/) -> why it may touch a parser
ALLOWED = {
    "services/ocr_service.py": "child code: native text, pdfplumber tables, OCR render and Tesseract; reached via pdf_isolation",
    "services/pdf_embedded.py": "child code: the e-Belge attachment, size-capped while inflating; reached via pdf_isolation",
    "services/sheet_child.py": "child code: openpyxl, zipfile and csv of an upload, with size/zip/row/cell caps; reached via sheet_isolation",
}
# Imports of a spreadsheet library that are NOT a parse of uploaded bytes: files the server itself generates.
SERVER_GENERATED = {
    "services/exporters.py": "writes workbooks (`openpyxl.Workbook()`, never `load_workbook`): an export the server generates",
}
# CSV is parsed by the pure-Python csv module: no archive, no XML, no native code. What it can still do is eat
# memory on a huge line or file, so the TEXT it parses has already passed the door's caps (MAX_UPLOAD_SIZE_MB and
# SHEET_MAX_CSV_LINE_CHARS, `sheet_child.check_text_bytes`, via `metin_coz` / `ingest.readers._read_csv`), or it is
# text this server produced (`standart_csv`). A new module that parses uploaded CSV text goes through
# `sheet_isolation.read_sheets`, or is listed here with its reason. A key ending in "/" is a directory.
CSV_TEXT_LEVEL = {
    "agents/": "per-role agents parse the `csv_text` the orchestrator built (ingest.recognize.standart_csv) or the upload text read through the door",
    "parsers/accounting/": "ERP export parsers over text already decoded by metin_coz (size and line caps)",
    "services/connectors/": "CRM/HR exports parsed from text already decoded by metin_coz (size and line caps)",
    "services/csv_validator.py": "validates text already decoded and capped at the upload door",
    "services/data_plane/normalization_service.py": "normalises text already decoded and capped at the upload door",
    "services/ingest/rows.py": "statement rows from the text `_read_csv` returned after its caps",
}

# `Image.open` is only a PIL call when PIL is imported in the same file; a bare `.open(` of a file is not.
IMPORT = re.compile(r"^\s*(?:import|from)\s+(pymupdf|fitz|pdfplumber|pdfminer|pytesseract|PIL)\b", re.M)
SHEET_IMPORT = re.compile(r"^\s*(?:import|from)\s+(openpyxl|xlrd|pyxlsb|python_calamine)\b", re.M)
SHEET_LOAD = re.compile(r"\b(?:load_workbook|open_workbook|read_excel)\(")
CSV_PARSE = re.compile(r"\b_?csv\.(?:reader|DictReader)\(|\bread_csv\(")
PIL_OPEN = re.compile(r"\bImage\.open\(")
HTML_CALL = re.compile(r"\b(?:Weasy)?HTML\(")


def _sources() -> dict[str, str]:
    return {p.relative_to(APP).as_posix(): p.read_text(encoding="utf-8", errors="ignore") for p in APP.rglob("*.py")}


def _listed(rel: str, table: dict[str, str]) -> bool:
    return any(rel == k or (k.endswith("/") and rel.startswith(k)) for k in table)


def test_uploaded_bytes_are_parsed_only_by_the_child_modules():
    offenders = []
    for rel, text in _sources().items():
        if rel in ALLOWED:
            continue
        if IMPORT.search(text) or PIL_OPEN.search(text):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} import or call PyMuPDF/pdfplumber/pdfminer/pytesseract/PIL outside the isolated child. "
        f"Read the file through app.services.ocr_service.extract_text_from_pdf (child process), or extend ALLOWED "
        f"with the reason."
    )


def test_spreadsheets_are_parsed_only_by_the_child_module():
    sources = _sources()
    offenders = []
    for rel, text in sources.items():
        if rel in ALLOWED:
            continue
        if SHEET_LOAD.search(text) or (SHEET_IMPORT.search(text) and rel not in SERVER_GENERATED):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} open a spreadsheet (openpyxl/xlrd/read_excel/load_workbook) outside the isolated child. "
        f"Read uploaded bytes through app.services.sheet_isolation.read_sheets (child process); a file the "
        f"server itself generates goes in SERVER_GENERATED with the reason."
    )
    for rel in SERVER_GENERATED:
        assert SHEET_IMPORT.search(sources[rel]) and not SHEET_LOAD.search(sources[rel]), f"{rel}: stale, or loads a workbook"


def test_csv_parsing_is_only_where_the_caps_have_run():
    sources = _sources()
    offenders = [rel for rel, text in sources.items() if CSV_PARSE.search(text) and rel not in ALLOWED and not _listed(rel, CSV_TEXT_LEVEL)]
    assert not offenders, (
        f"{offenders} parse CSV outside the child and outside CSV_TEXT_LEVEL. Read uploaded bytes through "
        f"app.services.sheet_isolation.read_sheets, or list the module in CSV_TEXT_LEVEL with the reason its input is bounded."
    )
    stale = [k for k in CSV_TEXT_LEVEL if not any(rel == k or (k.endswith("/") and rel.startswith(k)) for rel in sources if CSV_PARSE.search(sources[rel]))]
    assert not stale, f"CSV_TEXT_LEVEL entries with no CSV parse in them: {stale}"


def test_the_allow_list_has_no_stale_entries_and_the_parent_modules_stay_free_of_parsers():
    sources = _sources()
    for rel in ALLOWED:
        assert rel in sources and (
            IMPORT.search(sources[rel]) or PIL_OPEN.search(sources[rel]) or SHEET_IMPORT.search(sources[rel])
        ), f"{rel} no longer needs its entry"
    parents = ("services/pdf_isolation.py", "services/sheet_isolation.py", "services/ingest/readers.py", "services/ingest/table.py")
    for rel in parents:
        text = sources[rel]
        assert not IMPORT.search(text) and not SHEET_IMPORT.search(text) and ".embfile_get" not in text and not SHEET_LOAD.search(text), rel
        assert not CSV_PARSE.search(text), f"{rel} parses CSV in the parent"


def test_embfile_get_is_never_called():
    """PyMuPDF inflates a whole attachment before any size check can run; pdf_embedded inflates with a cap."""
    assert [rel for rel, text in _sources().items() if ".embfile_get(" in text] == []


def test_every_weasyprint_render_passes_a_url_fetcher():
    missing = []
    for rel, text in _sources().items():
        if not re.search(r"from weasyprint import[^\n]*\bHTML\b", text):
            continue
        for match in HTML_CALL.finditer(text):
            call = text[match.start(): match.start() + 200].split(".write_pdf")[0]
            if "url_fetcher=" not in call:
                missing.append(rel)
    assert not missing, f"HTML(...) without url_fetcher in {sorted(set(missing))}: use url_fetcher=deny_fetcher()"
