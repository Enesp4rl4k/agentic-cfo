"""The parser memory defaults are MEASURED, not guessed (Linux; runs in the hardening step of the Backend CI job).

A 300-page statement-like text PDF with ruled tables, a 300-page document thin enough to go through pdfplumber,
and a 10-page full-colour scanned-style PDF OCR'd at the product's 300 dpi are each parsed by the real child
(`tests/parser_memory_probe.py`), which reports its own peak address space (VmPeak) and resident set (VmHWM); the
probe also samples every descendant (Tesseract) from /proc. The numbers are printed to the CI log and written to
the job summary, and `docs/ops/parser-sizing.md` quotes them. The defaults must keep stated headroom over them:

* `PDF_CHILD_MEMORY_MB` (RLIMIT_AS, a backstop) >= peak address space (child and Tesseract, separately: each
  process has its own limit) x ADDRESS_HEADROOM;
* `PARSE_CHILD_RSS_MB` (what the container must hold per child) >= (child + Tesseract resident) x RSS_HEADROOM.

The parse also runs under the DEFAULT limits end to end: a page that hit a limit would be a visible refusal, and
this test would fail on it.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from app.config import get_settings

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc and uses RLIMIT_AS (Linux)")

ADDRESS_HEADROOM = 1.5
RSS_HEADROOM = 1.25


@pytest.fixture(scope="module")
def probe():
    sys.path.insert(0, str(Path(__file__).parent))
    import parser_memory_probe

    return parser_memory_probe


def report(capsys, label: str, numbers: dict) -> None:
    line = f"PARSER MEMORY {label}: " + ", ".join(f"{k}={v}" for k, v in numbers.items() if k != "stderr_tail")
    with capsys.disabled():
        print("\n" + line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"- {line}\n")


def need_tesseract() -> None:
    if shutil.which("tesseract") is None:
        if os.environ.get("REQUIRE_TESSERACT") == "1":
            pytest.fail("REQUIRE_TESSERACT=1 but tesseract is not installed")
        pytest.skip("tesseract is not installed")


@pytest.mark.parametrize(("label", "rows"), [("text-300-pages-tables", 42), ("thin-300-pages-pdfplumber", 2)])
def test_a_300_page_text_statement_fits_with_headroom(probe, tmp_path, capsys, label, rows):
    numbers = probe.measure(probe.statement_pdf(tmp_path / "s.pdf", 300, rows=rows))
    report(capsys, label, numbers)
    assert numbers["exit"] == 0 and numbers["stdout_bytes"] > 0, numbers["stderr_tail"]
    s = get_settings()
    assert numbers["child_vmpeak_mb"] * ADDRESS_HEADROOM <= s.pdf_child_memory_mb, numbers
    assert numbers["child_vmhwm_mb"] * RSS_HEADROOM <= s.parse_child_rss_mb, numbers


def test_a_scanned_statement_ocr_fits_with_headroom(probe, tmp_path, capsys):
    need_tesseract()
    numbers = probe.measure(probe.scanned_pdf(tmp_path / "scan.pdf", 10), timeout_s=900)
    report(capsys, "scan-10-pages-ocr-300dpi", numbers)
    assert numbers["exit"] == 0 and numbers["stdout_bytes"] > 0, numbers["stderr_tail"]
    tesseract = next((d for name, d in numbers["descendants"].items() if "tesseract" in name.lower()), None)
    assert tesseract, f"no Tesseract process was seen: {numbers['descendants']}"
    s = get_settings()
    # each process has its own address-space limit (Tesseract inherits the child's), so the larger one decides
    assert max(numbers["child_vmpeak_mb"], tesseract["VmPeak"]) * ADDRESS_HEADROOM <= s.pdf_child_memory_mb, numbers
    assert (numbers["child_vmhwm_mb"] + tesseract["VmHWM"]) * RSS_HEADROOM <= s.parse_child_rss_mb, numbers


def test_the_real_pipeline_reads_a_300_page_statement_under_the_default_limits(probe, tmp_path):
    from app.services import pdf_isolation
    from app.services.ocr_service import extract_text_from_pdf

    pdf_isolation._cache.clear()
    result = extract_text_from_pdf(str(probe.statement_pdf(tmp_path / "s.pdf", 300)))
    assert result.strategy_used != "failed", result.warnings
    assert result.page_count == 300 and "pages_unread" not in result.metadata and "refusal" not in result.metadata


def test_the_real_pipeline_ocrs_a_scanned_statement_under_the_default_limits(probe, tmp_path):
    need_tesseract()
    from app.services import pdf_isolation
    from app.services.ocr_service import extract_text_from_pdf

    pdf_isolation._cache.clear()
    result = extract_text_from_pdf(str(probe.scanned_pdf(tmp_path / "scan.pdf", 10)))
    assert result.strategy_used == "tesseract", (result.strategy_used, result.warnings, result.metadata)
    assert result.page_count == 10 and "pages_unread" not in result.metadata and "refusal" not in result.metadata
    assert "HAVALE" in result.text.upper()
