"""The parsers of an uploaded file's bytes run only in the PDF child process.

PyMuPDF, pdfplumber/pdfminer, Tesseract and Pillow decode attacker-controlled bytes in C or in code that has
had crashes and decompression bombs. They may be imported or called only by the modules below, which are the
child's code (or its entry point); the API and worker processes reach them through `pdf_isolation`.
A new use anywhere else fails here: put it behind the child, or add it to the list with the reason.

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
}
# `Image.open` is only a PIL call when PIL is imported in the same file; a bare `.open(` of a file is not.
IMPORT = re.compile(r"^\s*(?:import|from)\s+(pymupdf|fitz|pdfplumber|pdfminer|pytesseract|PIL)\b", re.M)
PIL_OPEN = re.compile(r"\bImage\.open\(")
HTML_CALL = re.compile(r"\b(?:Weasy)?HTML\(")


def _sources() -> dict[str, str]:
    return {p.relative_to(APP).as_posix(): p.read_text(encoding="utf-8", errors="ignore") for p in APP.rglob("*.py")}


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


def test_the_allow_list_has_no_stale_entries_and_the_parent_modules_stay_free_of_parsers():
    sources = _sources()
    for rel in ALLOWED:
        assert rel in sources and (IMPORT.search(sources[rel]) or PIL_OPEN.search(sources[rel])), f"{rel} no longer needs its entry"
    for rel in ("services/pdf_isolation.py", "services/ingest/readers.py"):
        assert not IMPORT.search(sources[rel]) and ".embfile_get" not in sources[rel], rel


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
