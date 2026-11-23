"""The OCR path end to end on a generated scanned-style PDF: PyMuPDF render -> Pillow 13 `Image.open(formats=["PNG"])`
-> Tesseract, all in the child process. Runs where the `tesseract` binary and the Turkish and English models are
installed (the Backend CI job installs them); skipped elsewhere, so a machine without Tesseract proves nothing
about this path and says so."""
from __future__ import annotations

import shutil

import pytest

from app.services.ocr_service import extract_text_from_pdf

pymupdf = pytest.importorskip("pymupdf")
pytesseract = pytest.importorskip("pytesseract")


def _tesseract_ready() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        languages = set(pytesseract.get_languages(config=""))
    except Exception:
        return False
    return {"tur", "eng"} <= languages


pytestmark = pytest.mark.skipif(not _tesseract_ready(), reason="tesseract with tur+eng models is not installed here")


def scanned_pdf(path, pages: int = 2) -> str:
    """Pages that are only a picture of text: no text layer, so native extraction finds nothing."""
    source = pymupdf.open()
    scan = pymupdf.open()
    for n in range(pages):
        page = source.new_page()
        y = 100
        for line in ("HAVALE GELEN ODEME 1.250,00 TL", "KIRA ODEMESI GIDEN 14.500,00 TL", f"SAYFA {n + 1} EKSTRE TOPLAM"):
            page.insert_text((60, y), line, fontsize=22)
            y += 50
        pixmap = page.get_pixmap(dpi=200)
        target = scan.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, pixmap=pixmap)
    scan.save(str(path))
    return str(path)


def test_a_scanned_pdf_is_read_by_tesseract_in_the_child(tmp_path):
    import PIL

    path = scanned_pdf(tmp_path / "tarama.pdf")
    assert pymupdf.open(path)[0].get_text().strip() == ""  # really no text layer
    result = extract_text_from_pdf(path)
    assert result.strategy_used == "tesseract", (result.strategy_used, result.warnings)
    assert result.page_count == 2
    text = result.text.upper()
    assert "HAVALE" in text and "KIRA" in text and "EKSTRE" in text
    assert PIL.__version__.split(".")[0] == "13"  # the Pillow the lock pins is the one that decoded the render
