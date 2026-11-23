"""An uploaded PDF is untrusted input to three parsers. Size cap, page cap, a child process with a
timeout, and a visible "PDF okunamadı" for every refusal, crash and timeout: never a silent "".

PDFs are generated here with PyMuPDF (nothing downloaded, nothing malicious); crashes and hangs are
simulated by pointing the worker command at a one-line interpreter script.
"""
from __future__ import annotations

import importlib.metadata
import json
import sys
from dataclasses import asdict
from types import ModuleType, SimpleNamespace

import pytest

from app.config import get_settings
from app.services import ocr_service, pdf_isolation
from app.services.ingest.readers import _read_pdf
from app.services.ocr_service import extract_text_from_pdf
from app.services.pdf_isolation import PdfOkunamadi

pymupdf = pytest.importorskip("pymupdf")

ROWS = [
    "01.03.2026 HAVALE GELEN ODEME ACIKLAMA 1.250,00 TL",
    "02.03.2026 EFT GIDEN KIRA ODEMESI ACIKLAMA 14.500,00 TL",
    "03.03.2026 POS KOMISYON KESINTISI ACIKLAMA 87,35 TL",
]


def make_pdf(path, pages: int = 1) -> str:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        y = 72
        for row in ROWS:
            page.insert_text((50, y), f"{row} sayfa {n + 1}", fontsize=10)
            y += 20
    doc.save(str(path))
    doc.close()
    return str(path)


def worker(monkeypatch, code: str) -> None:
    monkeypatch.setattr(pdf_isolation, "_WORKER_COMMAND", [sys.executable, "-c", code])


def assert_visible_failure(result) -> None:
    assert result.strategy_used == "failed" and result.text == ""
    assert result.warnings and result.warnings[0].startswith("PDF okunamadı:")


# ── The child process returns what the in-process parse returns ─────────────────────────────

def test_isolated_parse_equals_in_process_parse(tmp_path):
    path = make_pdf(tmp_path / "ekstre.pdf", pages=2)
    isolated = extract_text_from_pdf(path)
    inline = ocr_service._extract_in_process(path)
    assert isolated == inline
    assert "14.500,00" in isolated.text and "87,35" in isolated.text and isolated.page_count == 2


# ── Size and page caps, before anything is parsed ───────────────────────────────────────────

def test_a_file_over_the_size_cap_is_refused_before_parsing(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "a.pdf")
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 0)
    monkeypatch.setattr(pdf_isolation, "_run_child", lambda *a: pytest.fail("parser was reached"))
    monkeypatch.setattr(ocr_service, "_extract_in_process", lambda *a, **k: pytest.fail("parser was reached"))
    assert_visible_failure(extract_text_from_pdf(path))


def test_a_file_over_the_page_cap_is_refused(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "uzun.pdf", pages=3)
    monkeypatch.setattr(pdf_isolation, "MAX_PDF_PAGES", 2)
    # In process: a child process would read its own copy of the constant. The child path is covered below.
    monkeypatch.setattr(pdf_isolation, "ISOLATE_PARSER", False)
    result = extract_text_from_pdf(path)
    assert_visible_failure(result)
    assert "3 sayfa" in result.warnings[0]


# ── A crash, a hang, garbage output: refused and visible, the caller survives ───────────────

def test_a_hanging_parser_is_killed_at_the_timeout(tmp_path, monkeypatch):
    worker(monkeypatch, "import time; time.sleep(60)")
    monkeypatch.setattr(pdf_isolation, "PARSE_TIMEOUT_SECONDS", 1)
    result = extract_text_from_pdf(make_pdf(tmp_path / "a.pdf"))
    assert_visible_failure(result)
    assert "saniyede bitmedi" in result.warnings[0]


def test_a_crashing_parser_does_not_take_the_caller_down(tmp_path, monkeypatch):
    worker(monkeypatch, "import os; os._exit(139)")  # what a segfault in a C parser looks like
    assert_visible_failure(extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")))


def test_unreadable_worker_output_is_a_failure_not_an_empty_success(tmp_path, monkeypatch):
    worker(monkeypatch, "print('not json')")
    assert_visible_failure(extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")))


def test_the_worker_gets_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("TIPHYS_TEST_SECRET", "s3cret")
    monkeypatch.setenv("CMAP_PATH", "/tmp/evil")
    code = (
        "import json, os; print(json.dumps({'text': 'x', 'confidence': 0.9, 'strategy_used': 'native', "
        "'page_count': 1, 'page_results': [], 'file_path': 'p', "
        "'warnings': [os.environ.get('TIPHYS_TEST_SECRET', '-'), os.environ.get('CMAP_PATH', '-')]}))"
    )
    worker(monkeypatch, code)
    result = extract_text_from_pdf(make_pdf(tmp_path / "a.pdf"))
    assert result.warnings == ["-", "-"]


# ── What the ingest reader does with a refusal ──────────────────────────────────────────────

def test_the_reader_raises_with_the_reason_instead_of_returning_empty_text(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_isolation, "MAX_PDF_PAGES", 1)
    monkeypatch.setattr(pdf_isolation, "ISOLATE_PARSER", False)
    with pytest.raises(PdfOkunamadi, match="PDF okunamadı"):
        _read_pdf(make_pdf(tmp_path / "uzun.pdf", pages=2))


def test_the_reader_still_returns_text_for_a_normal_pdf(tmp_path):
    text = _read_pdf(make_pdf(tmp_path / "a.pdf"))
    assert "HAVALE GELEN ODEME" in text


# ── Pillow only decodes the PNG this process rendered, and a huge page is not rendered ──────

class _FakePage:
    def __init__(self, png: bytes, width: float = 595, height: float = 842) -> None:
        self._png = png
        self.rect = SimpleNamespace(width=width, height=height)

    def get_pixmap(self, dpi: int):
        png = self._png

        class Pix:
            def tobytes(self, fmt: str) -> bytes:
                return png

        return Pix()


@pytest.fixture
def fake_tesseract(monkeypatch):
    called: list[bool] = []
    mod = ModuleType("pytesseract")
    mod.Output = SimpleNamespace(DICT="dict")  # type: ignore[attr-defined]

    def image_to_data(*a, **k):
        called.append(True)
        return {"text": [], "conf": []}

    mod.image_to_data = image_to_data  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", mod)
    return called


def _image_bytes(fmt: str) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, fmt)
    return buf.getvalue()


def test_ocr_decodes_png_and_nothing_else(fake_tesseract):
    ocr_service._try_tesseract_ocr(_FakePage(_image_bytes("PNG")))
    assert fake_tesseract == [True]  # PNG reached tesseract
    fake_tesseract.clear()
    assert ocr_service._try_tesseract_ocr(_FakePage(_image_bytes("GIF"))) == ("", 0.0)
    assert fake_tesseract == []  # a GIF was refused by Image.open(formats=["PNG"])


def test_a_page_that_would_render_to_a_huge_bitmap_is_skipped(fake_tesseract):
    huge = _FakePage(_image_bytes("PNG"), width=14400, height=14400)
    assert ocr_service._try_tesseract_ocr(huge) == ("", 0.0)
    assert fake_tesseract == []


def test_the_decompression_bomb_ceiling_is_set_by_the_ocr_path(fake_tesseract, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    ocr_service._try_tesseract_ocr(_FakePage(_image_bytes("PNG")))
    assert Image.MAX_IMAGE_PIXELS == pdf_isolation.MAX_RENDER_PIXELS


# ── pdfminer: a fixed release, and no pickle in its CMap loader ─────────────────────────────

def test_pdfminer_is_a_release_that_fixes_the_cmap_and_crafted_pdf_advisories():
    """GHSA-wf5f-4jwr-ppcp (CVE-2025-64512, fixed 20251107) and GHSA-f83h-ghpp-7wcc (CVE-2025-70559, 20251230)."""
    try:
        version = importlib.metadata.version("pdfminer.six")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("pdfminer.six is not installed here")
    assert int(version) >= 20251230, version


def test_pdfminer_cmap_loader_reads_json_not_pickle():
    cmapdb = pytest.importorskip("pdfminer.cmapdb")
    with open(cmapdb.__file__, encoding="utf-8") as f:
        assert "pickle" not in f.read()


def test_the_worker_payload_round_trips_every_field():
    result = ocr_service.OCRResult(
        text="x", confidence=0.5, strategy_used="native", page_count=1,
        page_results=[ocr_service.PageResult(0, "x", 0.5, "native", 1, 1)], file_path="p",
        has_tables=True, warnings=["w"], metadata={"title": "t"},
    )
    assert pdf_isolation._from_payload(json.loads(json.dumps(asdict(result)))) == result
