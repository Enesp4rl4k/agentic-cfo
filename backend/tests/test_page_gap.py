"""A page that yields no text holds an upload only where DATA MAY BE MISSING (app/services/page_gap.py).

Routine text-less pages (logo cover, stamp page, blank scanned back) get a visible note and no hold. A text-less page
between pages with transaction rows whose balances do not chain (or cannot be checked), or after a page that says the
statement continues, holds with the reason. PDFs are generated here with PyMuPDF; OCR is replaced by "reads nothing".
"""
from __future__ import annotations

import pytest

from app.agents.state import SkillResult
from app.services import ocr_service, page_gap, pdf_isolation

pymupdf = pytest.importorskip("pymupdf")

NOTE_TR = "sayfada okunabilir metin yok (görsel/boş sayfa)"
FILLER = "HAVALE GELEN ODEME ACIKLAMA FATURA NO 2026 "


def rows_page(doc, *rows: tuple[str, str, str], extra: str = "") -> None:
    """A statement page: one line per (date, amount, balance)."""
    lines = [f"{d} {FILLER} {a} {b}" for d, a, b in rows]
    doc.new_page().insert_text((40, 72), "\n".join([*lines, extra] if extra else lines), fontsize=8)


def image_page(doc) -> None:
    """A page with a small image and no text: a logo, a stamp, a scanned blank."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
    pix.clear_with(200)
    doc.new_page().insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=pix)


def outcome(tmp_path, monkeypatch, build) -> tuple[bool, str, dict]:
    doc = pymupdf.open()
    build(doc)
    path = str(tmp_path / "s.pdf")
    doc.save(path)
    doc.close()
    monkeypatch.setattr(ocr_service, "_try_pdfplumber_extraction", lambda file_path, page_num: ("", 0.0, False))
    monkeypatch.setattr(ocr_service, "_try_tesseract_ocr", lambda page, dpi=300: ("", 0.0))
    result = pdf_isolation.parse_here(path)
    monkeypatch.setattr(pdf_isolation, "cached_result", lambda file_path: result)
    sonuc = SkillResult(ok=True, patch={}, confidence=0.95, needs_review=False, detail="6 işlem")
    pdf_isolation.apply_pdf_notes(sonuc, path)
    return bool(sonuc.needs_review), sonuc.detail, result.metadata


FIRST = ("01.03.2026", "500,00", "10.500,00"), ("02.03.2026", "250,00", "10.750,00")
CHAINS = (("03.03.2026", "100,00", "10.850,00"),)          # 10.850 - 10.750 = this row's own 100,00
BROKEN = (("03.03.2026", "100,00", "12.850,00"),)          # 2.100 apart: rows are missing between


def test_a_logo_only_first_page_is_a_note_and_no_hold(tmp_path, monkeypatch):
    def build(doc):
        image_page(doc)
        rows_page(doc, *FIRST)
        rows_page(doc, *CHAINS)
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert meta["pages_unread"] == [1] and "pages_gap" not in meta
    assert held is False and f"1. {NOTE_TR}" in detail and "No readable text on page(s) 1" in detail


def test_a_blank_scanned_last_page_is_a_note_and_no_hold(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST)
        rows_page(doc, *CHAINS)
        image_page(doc)
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert meta["pages_unread"] == [3] and "pages_gap" not in meta
    assert held is False and f"3. {NOTE_TR}" in detail


def test_a_text_less_page_between_rows_whose_balances_do_not_chain_holds_with_the_reason(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST)
        image_page(doc)
        rows_page(doc, *BROKEN)
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert meta["pages_gap"]["2"][0].startswith("1. ve 3. sayfadaki bakiyeler birbirine bağlanmıyor")
    assert held is True
    assert "Sayfa 2 okunamadı" in detail and "bağlanmıyor" in detail and "do not connect" in detail and "may be missing" in detail


def test_the_same_page_between_rows_whose_balances_chain_is_a_note_only(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST)
        image_page(doc)
        rows_page(doc, *CHAINS)
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert meta["pages_unread"] == [2] and "pages_gap" not in meta
    assert held is False and f"2. {NOTE_TR}" in detail


def test_rows_on_both_sides_without_balances_cannot_prove_the_link_and_hold(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, ("01.03.2026", "500,00", "x"), ("02.03.2026", "250,00", "x"))
        image_page(doc)
        rows_page(doc, ("03.03.2026", "100,00", "x"))
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert held is True and "doğrulanamadı" in meta["pages_gap"]["2"][0] and "could not be checked" in detail


def test_a_page_that_says_the_statement_continues_holds_when_nothing_follows(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST, extra="Ekstrenin devami sonraki sayfada devam etmektedir")
        image_page(doc)
    held, _detail, meta = outcome(tmp_path, monkeypatch, build)
    assert held is True and "devam ettiğini" in meta["pages_gap"]["2"][0]


def test_balances_chain_in_either_row_order():
    assert page_gap.chains([500, 10_500], [100, 10_600]) is True      # oldest first: the next row's own amount
    assert page_gap.chains([100, 10_600], [500, 10_100]) is True      # newest first: the earlier row's amount
    assert page_gap.chains([500, 10_500], [100, 12_600]) is False
    assert page_gap.chains([500], [100, 10_600]) is None              # no balance on one side


def test_rows_are_lines_with_a_date_and_an_amount():
    text = "Hesap özeti\n01.03.2026 HAVALE 1.250,00 11.250,00\nSayfa 1 / 3\n02/03/2026 EFT -75,50 11.174,50\n"
    assert page_gap.row_lines(text) == [[125_000, 1_125_000], [-7_550, 1_117_450]]


def test_nothing_unread_is_no_note():
    assert page_gap.note({}) is None and page_gap.note({"pages_unread": []}) is None
