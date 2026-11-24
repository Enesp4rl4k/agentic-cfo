"""A page that yields no text holds an upload only where DATA MAY BE MISSING (app/services/page_gap.py).

Routine text-less pages (logo cover, stamp page, blank page) get a visible note and no hold. A SCAN (an image covering
most of the page) that OCR could not read holds unless the statement's stated end is reached; a text-less page between
rows whose balances do not chain holds; a stated closing balance the rows do not reach holds. PDFs are generated here
with PyMuPDF; OCR is replaced by "reads nothing".
"""
from __future__ import annotations

import pytest

from app.agents.state import SkillResult
from app.services import ocr_service, page_gap, pdf_isolation

pymupdf = pytest.importorskip("pymupdf")

NOTE_TR = "sayfada okunabilir metin yok (görsel/boş sayfa)"
SCAN_TR = "sayfa taranmış görünüyor ve okunamadı; işlemler eksik olabilir"
FILLER = "HAVALE GELEN ODEME ACIKLAMA FATURA NO 2026 "


def rows_page(doc, *rows: tuple[str, str, str], extra: str = "") -> None:
    """A statement page: one line per (date, amount, balance)."""
    lines = [f"{d} {FILLER} {a} {b}" for d, a, b in rows]
    doc.new_page().insert_text((40, 72), "\n".join([*lines, extra] if extra else lines), fontsize=8)


def _image_page(doc, rect) -> None:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
    pix.clear_with(200)
    page = doc.new_page()
    page.insert_image(rect(page), pixmap=pix)


def logo_page(doc) -> None:
    _image_page(doc, lambda page: pymupdf.Rect(50, 50, 210, 210))     # a logo or stamp: about 5% of the page


def half_scan_page(doc) -> None:
    _image_page(doc, lambda page: pymupdf.Rect(0, 0, 595, 252))        # the last rows scanned on a third of the page: about 30%


def scan_page(doc) -> None:
    _image_page(doc, lambda page: page.rect)                           # a page-sized raster


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
CLOSING_OK = "Kapanis Bakiyesi: 10.850,00"
CLOSING_SHORT = "Kapanis Bakiyesi: 13.400,00"              # the rows end at 10.850,00


def statement(doc, *, closing: str = "", last=None) -> None:
    rows_page(doc, *FIRST)
    rows_page(doc, *CHAINS, extra=closing)
    if last:
        last(doc)


# ── The last page ───────────────────────────────────────────────────────────────────────────

def test_a_full_page_scan_at_the_end_with_nothing_stated_holds_and_says_it_is_a_scan(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, last=scan_page))
    assert meta["pages_scan"] == [3] and held is True
    assert f"3. {SCAN_TR}" in detail and "looks scanned" in detail and "görsel/boş" not in detail
    assert detail.startswith("[Okunamayan sayfalar / Pages not read:")        # first on the result, not buried


def test_the_same_scan_is_a_note_when_the_stated_closing_balance_is_reached(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, closing=CLOSING_OK, last=scan_page))
    assert meta["pages_unread"] == [3] and "pages_gap" not in meta and held is False
    assert "3. sayfa taranmış sayfa ve okunamadı; ekstrenin kapanış bakiyesi okunan son bakiyeyle aynıdır, satır eksik görünmüyor" in detail
    assert meta["pages_verified"] == {"3": "closing"} and "görsel/boş" not in detail


def test_a_logo_only_last_page_is_a_note(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, last=logo_page))
    assert "pages_scan" not in meta and held is False and f"3. {NOTE_TR}" in detail


def test_a_blank_last_page_is_a_note(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, last=lambda d: d.new_page()))
    assert meta["pages_unread"] == [3] and held is False and f"3. {NOTE_TR}" in detail


def test_a_stated_closing_balance_the_rows_do_not_reach_holds_for_a_text_less_page_anywhere(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, closing=CLOSING_SHORT, last=logo_page))
    assert held is True and "kapanış bakiyesi 13.400,00" in meta["pages_gap"]["3"][0]
    assert "closing balance is 13.400,00" in detail


def test_a_logo_first_page_is_a_note_and_a_chained_middle_scan_says_the_balances_are_continuous(tmp_path, monkeypatch):
    def first(doc):
        logo_page(doc)
        rows_page(doc, *FIRST)
        rows_page(doc, *CHAINS)
    held, detail, _meta = outcome(tmp_path, monkeypatch, first)
    assert held is False and f"1. {NOTE_TR}" in detail

    def middle(doc):
        rows_page(doc, *FIRST)
        scan_page(doc)
        rows_page(doc, *CHAINS)
    held, detail, _meta = outcome(tmp_path, monkeypatch, middle)
    assert held is False and "2. sayfa taranmış sayfa ve okunamadı; bakiyeler süreklidir, satır eksik görünmüyor" in detail


def month_end(doc, *, closing: str = "", last=scan_page) -> None:
    """A March statement whose last parsed row is 28.03, within a week of its stated end 31.03."""
    head = "Hesap Ekstresi\nDonem: 01.03.2026 - 31.03.2026\nTarih Aciklama Tutar Bakiye\n"
    first = "\n".join(f"{d} {FILLER} {a} {b}" for d, a, b in (("20.03.2026", "500,00", "10.500,00"), ("24.03.2026", "250,00", "10.750,00")))
    doc.new_page().insert_text((40, 72), head + first, fontsize=8)
    rows_page(doc, ("28.03.2026", "100,00", "10.850,00"), extra=closing)
    last(doc)


def test_a_scan_at_the_end_of_a_month_end_statement_still_holds_when_the_last_row_is_within_a_week_of_the_period_end(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, month_end)
    assert held is True and "3. sayfa taranmış görünüyor ve okunamadı" in detail          # proximity to the period end proves nothing
    assert "pages_verified" not in meta and "satır eksik görünmüyor" not in detail


def test_the_same_statement_with_its_closing_balance_exactly_reached_is_a_note_with_the_verified_wording(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: month_end(doc, closing=CLOSING_OK))
    assert held is False and meta["pages_verified"] == {"3": "closing"} and "satır eksik görünmüyor" in detail


def test_a_closing_balance_stated_but_not_reached_holds(tmp_path, monkeypatch):
    held, detail, _meta = outcome(tmp_path, monkeypatch, lambda doc: month_end(doc, closing=CLOSING_SHORT))
    assert held is True and "kapanış bakiyesi 13.400,00" in detail


def test_only_the_opening_balance_phrasing_is_not_a_stated_closing_balance(tmp_path, monkeypatch):
    # the number equals the last balance by coincidence: it must still not verify the page
    held, detail, _meta = outcome(tmp_path, monkeypatch, lambda doc: month_end(doc, closing="Onceki donem kapanis bakiyesi: 10.850,00"))
    assert held is True and "3. sayfa taranmış görünüyor ve okunamadı" in detail


def test_opening_labels_never_match_and_two_different_closing_balances_are_ambiguous():
    assert page_gap.stated_closing("Onceki donem kapanis bakiyesi 1.000,00\nDevreden bakiye 1.000,00\nAcilis bakiyesi 1.000,00") is None
    assert page_gap.stated_closing("Onceki donem kapanis bakiyesi 1.000,00\nKapanis Bakiyesi: 2.500,00") == 250_000
    assert page_gap.stated_closing("Kapanis Bakiyesi: 2.500,00\nSon Bakiye: 2.600,00") is None
    assert page_gap.stated_closing("Closing balance 2.500,00 TL") == 250_000


def test_a_half_page_scan_as_the_last_page_holds_and_a_logo_is_a_note(tmp_path, monkeypatch):
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, last=half_scan_page))
    assert meta["pages_scan"] == [3] and held is True and f"3. {SCAN_TR}" in detail
    held, detail, meta = outcome(tmp_path, monkeypatch, lambda doc: statement(doc, last=logo_page))
    assert "pages_scan" not in meta and held is False and f"3. {NOTE_TR}" in detail


def test_a_scan_that_was_not_verified_never_gets_the_reassuring_sentence():
    (entry,) = page_gap.entries({"pages_unread": [3], "pages_scan": [3]})
    assert entry["state"] == "note" and "satır eksik görünmüyor" not in entry["tr"] and "görsel/boş" not in entry["tr"]


# ── The middle ──────────────────────────────────────────────────────────────────────────────

def test_a_text_less_page_between_rows_whose_balances_do_not_chain_holds_with_the_reason(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST)
        logo_page(doc)
        rows_page(doc, *BROKEN)
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert "1. ve 3. sayfadaki bakiyeler birbirine bağlanmıyor" in meta["pages_gap"]["2"][0] and held is True
    assert "2. sayfa okunamadı" in detail and "do not connect" in detail and "may be missing" in detail


def test_the_same_page_between_rows_whose_balances_chain_is_a_note_only(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST)
        logo_page(doc)
        rows_page(doc, *CHAINS)
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert meta["pages_unread"] == [2] and "pages_gap" not in meta and held is False and f"2. {NOTE_TR}" in detail


def test_a_blank_page_between_rows_is_never_a_hold(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST)
        doc.new_page()
        rows_page(doc, *BROKEN)
    held, _detail, meta = outcome(tmp_path, monkeypatch, build)
    assert meta["pages_unread"] == [2] and "pages_gap" not in meta and held is False   # the page is blank: not where rows went


def test_rows_on_both_sides_without_balances_cannot_prove_the_link_and_hold(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, ("01.03.2026", "500,00", "x"), ("02.03.2026", "250,00", "x"))
        logo_page(doc)
        rows_page(doc, ("03.03.2026", "100,00", "x"))
    held, detail, meta = outcome(tmp_path, monkeypatch, build)
    assert held is True and "doğrulanamadı" in meta["pages_gap"]["2"][0] and "could not be checked" in detail


def test_a_page_that_says_the_statement_continues_holds_when_nothing_follows(tmp_path, monkeypatch):
    def build(doc):
        rows_page(doc, *FIRST, extra="Ekstrenin devami sonraki sayfada devam etmektedir")
        logo_page(doc)
    held, _detail, meta = outcome(tmp_path, monkeypatch, build)
    assert held is True and "devam ettiğini" in meta["pages_gap"]["2"][0]


# ── The pieces ──────────────────────────────────────────────────────────────────────────────

def test_a_stated_period_end_well_after_the_last_row_is_evidence_and_one_reached_is_not():
    head = "Hesap Ekstresi\nDönem: 01.03.2026 - 31.03.2026\nTarih Açıklama Tutar Bakiye\n"
    row = "05.03.2026 HAVALE GELEN ODEME ACIKLAMA FATURA 100,00 10.100,00\n"
    short = page_gap.stated_end([(1, head + row)])
    assert short is not None and short[0] == "short" and "31.03.2026" in short[1][0]
    reached = page_gap.stated_end([(1, head + row + "29.03.2026 HAVALE GELEN ODEME ACIKLAMA FATURA 100,00 10.200,00\n")])
    assert reached is None      # within a week of the period end: never "reached", never evidence either way
    assert page_gap.stated_end([(1, row)]) is None            # nothing stated: no evidence either way


def test_a_closing_balance_may_match_the_first_row_of_a_newest_first_statement():
    text = "Son Bakiye: 10.850,00\n03.03.2026 X 100,00 10.850,00\n02.03.2026 X 250,00 10.750,00\n"
    assert page_gap.stated_end([(1, text)])[0] == "exact"


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
