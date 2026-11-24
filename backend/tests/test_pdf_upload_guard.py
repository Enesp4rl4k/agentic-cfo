"""An uploaded PDF is untrusted input to three parsers. Size cap, page cap, a child process with a
timeout, resource limits, a bounded pipe, no orphans, and a visible, readable refusal for every limit:
never a silent "" and never an empty success.

PDFs are generated here with PyMuPDF (nothing downloaded, nothing malicious); crashes, hangs and floods
are simulated by pointing the worker command at a one-line interpreter script.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import threading
import time
import zlib
from dataclasses import asdict
from types import ModuleType, SimpleNamespace

import pytest

from app.config import get_settings
from app.services import ocr_service, pdf_embedded, pdf_isolation
from app.services.ingest.readers import _pdf_embedded_xml, _read_pdf
from app.services.ocr_service import extract_text_from_pdf
from app.services.pdf_isolation import PdfOkunamadi

pymupdf = pytest.importorskip("pymupdf")

ROWS = [
    "01.03.2026 HAVALE GELEN ODEME ACIKLAMA 1.250,00 TL",
    "02.03.2026 EFT GIDEN KIRA ODEMESI ACIKLAMA 14.500,00 TL",
    "03.03.2026 POS KOMISYON KESINTISI ACIKLAMA 87,35 TL",
]
UBL = "<Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'><ID>A1</ID></Invoice>"


@pytest.fixture(autouse=True)
def fresh_cache():
    pdf_isolation._cache.clear()
    yield
    pdf_isolation._cache.clear()


def make_pdf(path, pages: int = 1, attachments: dict[str, bytes] | None = None) -> str:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        y = 72
        for row in ROWS:
            page.insert_text((50, y), f"{row} sayfa {n + 1}", fontsize=10)
            y += 20
    for name, data in (attachments or {}).items():
        doc.embfile_add(name, data)
    doc.save(str(path))
    doc.close()
    return str(path)


def worker(monkeypatch, code: str) -> None:
    monkeypatch.setattr(pdf_isolation, "_WORKER_COMMAND", [sys.executable, "-c", code])


def setting(monkeypatch, name: str, value) -> None:
    monkeypatch.setattr(get_settings(), name, value)


def assert_refused(result, code: str) -> None:
    assert result.strategy_used == "failed" and result.text == ""
    assert result.metadata["refusal"]["code"] == code
    assert result.warnings and result.warnings[0].startswith("PDF okunamadı:")


# ── The child returns what an in-process parse returns, attachments included ────────────────

def test_isolated_parse_equals_in_process_parse(tmp_path):
    path = make_pdf(tmp_path / "ekstre.pdf", pages=2, attachments={"fatura.xml": UBL.encode()})
    isolated = extract_text_from_pdf(path)
    inline = pdf_isolation.parse_here(path)
    assert isolated == inline
    assert "14.500,00" in isolated.text and "87,35" in isolated.text and isolated.page_count == 2
    assert isolated.embedded_xml == [UBL]


def test_the_attachment_is_read_by_the_child_never_by_the_parent(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "e.pdf", attachments={"a.xml": UBL.encode(), "n.txt": b"notes"})
    monkeypatch.setattr(pdf_isolation, "parse_here", lambda *a, **k: pytest.fail("parent parsed the PDF"))
    monkeypatch.setattr(pdf_embedded, "read_ebelge_attachments", lambda *a, **k: pytest.fail("parent read attachments"))
    assert _pdf_embedded_xml(path) == [UBL]


def test_text_and_attachment_share_one_child(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "e.pdf", attachments={"a.xml": UBL.encode()})
    runs: list[str] = []
    real = pdf_isolation._run_child
    monkeypatch.setattr(pdf_isolation, "_run_child", lambda *a: runs.append("child") or real(*a))
    _read_pdf(path)
    _pdf_embedded_xml(path)
    assert runs == ["child"]


# ── Attachments: capped while inflating, not after ──────────────────────────────────────────

def test_a_deflate_bomb_attachment_is_not_inflated_past_the_cap():
    bomb = zlib.compress(b"0" * 50_000_000)  # about 50 KB that would inflate to 50 MB
    assert len(bomb) < 100_000
    assert pdf_embedded.bounded_inflate(bomb, limit=1_000_000) is None
    assert pdf_embedded.bounded_inflate(zlib.compress(b"<a/>"), limit=1_000_000) == b"<a/>"
    assert pdf_embedded.bounded_inflate(b"not deflate", limit=100) is None


def test_an_oversized_attachment_inside_a_pdf_is_skipped(tmp_path):
    big = UBL.encode().replace(b"</Invoice>", b"<N>" + b"x" * 20_000 + b"</N></Invoice>")
    path = make_pdf(tmp_path / "e.pdf", attachments={"a.xml": big})
    assert pdf_embedded.read_ebelge_attachments(path, limit=5_000) == []
    assert pdf_embedded.read_ebelge_attachments(path, limit=1_000_000) == [big.decode()]


def test_an_attachment_declaring_a_dtd_is_not_passed_on(tmp_path):
    hostile = b"<!DOCTYPE a [<!ENTITY b 'c'>]><Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'/>"
    assert pdf_embedded.read_ebelge_attachments(make_pdf(tmp_path / "e.pdf", attachments={"a.xml": hostile})) == []


# ── Caps, before anything is parsed ─────────────────────────────────────────────────────────

def test_a_file_over_the_size_cap_is_refused_before_a_child_starts(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "a.pdf")
    setting(monkeypatch, "max_upload_size_mb", 0)
    monkeypatch.setattr(pdf_isolation, "_run_child", lambda *a: pytest.fail("a child was started"))
    result = extract_text_from_pdf(path)
    assert_refused(result, "pdf_too_large")


def test_a_file_over_the_page_cap_is_refused_by_the_child_and_says_which_limit(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "uzun.pdf", pages=3)
    setting(monkeypatch, "pdf_max_pages", 2)
    result = extract_text_from_pdf(path)
    assert_refused(result, "pdf_too_many_pages")
    with pytest.raises(PdfOkunamadi) as caught:
        _read_pdf(path)
    text = caught.value.user_text
    assert "3 sayfa" in text and "PDF_MAX_PAGES" in text and "daha kısa dönemlere" in text
    assert "3 pages" in text and "shorter periods" in text  # English twin
    assert str(tmp_path) not in text and "Ingestion error" not in text


# ── The child: crash, hang, garbage, flood, budget ──────────────────────────────────────────

def test_a_hanging_parser_is_killed_at_the_timeout(tmp_path, monkeypatch):
    worker(monkeypatch, "import time; time.sleep(60)")
    setting(monkeypatch, "pdf_parse_timeout_seconds", 1)
    result = extract_text_from_pdf(make_pdf(tmp_path / "a.pdf"))
    assert_refused(result, "pdf_timeout")
    assert "PDF_PARSE_TIMEOUT_SECONDS" in result.warnings[0]


def test_a_crashing_parser_does_not_take_the_caller_down(tmp_path, monkeypatch):
    worker(monkeypatch, "import os; os._exit(139)")  # what a segfault in a C parser looks like
    assert_refused(extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")), "pdf_unreadable")


@pytest.mark.parametrize("output", ["print('not json')", "print('[1, 2]')", "print('{\"text\": 1}')", "print('{}')"])
def test_unreadable_worker_output_is_a_failure_never_a_fallback_or_an_empty_success(tmp_path, monkeypatch, output):
    worker(monkeypatch, output)
    monkeypatch.setattr(pdf_isolation, "parse_here", lambda *a, **k: pytest.fail("fell back to an in-process parse"))
    assert_refused(extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")), "pdf_unreadable")


def test_the_parent_stops_reading_a_flooding_child(tmp_path, monkeypatch):
    worker(monkeypatch, "import sys\nwhile True:\n    sys.stdout.write('x' * 65536); sys.stdout.flush()")
    monkeypatch.setattr(pdf_isolation, "_STDOUT_LIMIT", 200_000)
    started = time.monotonic()
    assert_refused(extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")), "pdf_output_too_large")
    assert time.monotonic() - started < 30


def test_the_worker_gets_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("TIPHYS_TEST_SECRET", "s3cret")
    monkeypatch.setenv("CMAP_PATH", "/tmp/evil")
    code = (
        "import json, os; print(json.dumps({'text': 'x', 'confidence': 0.9, 'strategy_used': 'native', "
        "'page_count': 1, 'page_results': [], 'file_path': 'p', "
        "'warnings': [os.environ.get('TIPHYS_TEST_SECRET', '-'), os.environ.get('CMAP_PATH', '-')]}))"
    )
    worker(monkeypatch, code)
    assert extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")).warnings == ["-", "-"]


def test_the_child_is_told_its_limits(monkeypatch):
    setting(monkeypatch, "pdf_child_memory_mb", 1234)
    setting(monkeypatch, "pdf_parse_timeout_seconds", 50)
    setting(monkeypatch, "pdf_ocr_seconds_per_page", 7)
    setting(monkeypatch, "pdf_max_pages", 9)
    assert pdf_isolation._command("f.pdf", False)[-6:] == ["f.pdf", "0", "1234", "100", "7", "9"]


def test_ocr_pages_extend_the_deadline_by_one_page_budget_each(tmp_path, monkeypatch):
    """A scan is not refused for being long: while pages are being OCRed the deadline moves."""
    code = (
        "import sys, time, json\n"
        "sys.stderr.write('@@OCR@@\\n'); sys.stderr.flush()\n"
        "time.sleep(2.5)\n"
        "print(json.dumps({'text': 'ok', 'confidence': 0.9, 'strategy_used': 'tesseract', 'page_count': 1, "
        "'page_results': [], 'file_path': 'p'}))"
    )
    worker(monkeypatch, code)
    setting(monkeypatch, "pdf_parse_timeout_seconds", 1)
    setting(monkeypatch, "pdf_ocr_seconds_per_page", 5)
    assert extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")).text == "ok"
    # without the OCR mark the same child is over its 1 s budget
    worker(monkeypatch, code.replace("sys.stderr.write('@@OCR@@\\n'); sys.stderr.flush()\n", ""))
    pdf_isolation._cache.clear()
    assert_refused(extract_text_from_pdf(make_pdf(tmp_path / "b.pdf")), "pdf_timeout")


def test_parser_children_run_at_most_pdf_parse_concurrency_at_a_time(tmp_path, monkeypatch):
    setting(monkeypatch, "pdf_parse_concurrency", 1)
    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def fake_supervise(*a, **k):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.2)
        with lock:
            active["now"] -= 1
        return pdf_isolation.ChildOutcome("failed")

    monkeypatch.setattr(pdf_isolation, "_supervise", fake_supervise)
    pdf_isolation._slots = None
    threads = [threading.Thread(target=pdf_isolation._run_child, args=(str(tmp_path / "a.pdf"), False)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["max"] == 1


@pytest.mark.skipif(os.name != "posix", reason="process groups and /proc-style liveness are POSIX")
def test_no_descendant_survives_a_timeout(tmp_path, monkeypatch):
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(120)\n"
    )
    worker(monkeypatch, code)
    setting(monkeypatch, "pdf_parse_timeout_seconds", 2)
    assert_refused(extract_text_from_pdf(make_pdf(tmp_path / "a.pdf")), "pdf_timeout")
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail(f"grandchild {pid} survived the timeout")


@pytest.mark.skipif(os.name != "posix", reason="RLIMIT_AS is Linux")
def test_the_child_applies_its_memory_limit(tmp_path):
    import subprocess

    code = (
        "import sys, json; sys.path.insert(0, '.')\n"
        "from app.services import pdf_isolation\n"
        "pdf_isolation._apply_limits(512, 100)\n"
        "try:\n    bytearray(2 * 1024**3); print('allocated')\n"
        "except MemoryError:\n    print('refused')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ocr_service.Path(__file__).resolve().parents[1]))
    assert out.stdout.strip().splitlines()[-1] == "refused", out.stderr


# ── What reaches the user ───────────────────────────────────────────────────────────────────

def test_every_refusal_reads_as_a_sentence_in_both_languages_without_a_prefix_or_a_path():
    for code in pdf_isolation._TEXTS:
        params = {"size_mb": "12.0", "limit_mb": 10, "pages": 612, "limit": 500, "seconds": 180}
        error = PdfOkunamadi(code, **params)
        assert error.tr.startswith("PDF okunamadı:") and error.en.startswith("The PDF could not be read:")
        assert "{" not in error.user_text and "Ingestion error" not in error.user_text
        assert pdf_isolation.ingest_hata_metni(error) == error.user_text
    assert pdf_isolation.ingest_hata_metni(ValueError("boom")) == "Ingestion error: boom"


@pytest.mark.asyncio
async def test_a_refused_pdf_is_a_visible_actionable_halt_from_the_door_to_the_run_log(tmp_path, monkeypatch):
    """_belgeyi_al (the reading door) -> the ingestion step's result -> the orchestrator node's patch and log
    entry, which is what the job's `logs` and `error` carry to the API and the UI."""
    from app.agents import data_ingestion, orchestrator
    from app.agents.state import AgentRunConfig

    path = make_pdf(tmp_path / "uzun.pdf", pages=3)
    setting(monkeypatch, "pdf_max_pages", 2)
    state = {"org_id": "org-1", "job_id": "j", "file_path": path, "file_type": "pdf", "logs": []}

    res = await data_ingestion._belgeyi_al(path, "pdf", state, AgentRunConfig())
    assert res.ok is False and res.halt is True and not (res.patch or {}).get("transactions")
    assert res.detail.startswith("PDF okunamadı:") and "PDF_MAX_PAGES" in res.detail and "The PDF could not be read" in res.detail
    assert "Ingestion error" not in res.detail and str(tmp_path) not in res.detail

    patch = await orchestrator.node_data_ingestion(state, {})
    assert patch["halted"] is True and patch["awaiting_review"] is True  # the upload stays visible, held for a person
    assert patch["error"].startswith("PDF okunamadı:")  # the text the job records as its error
    entry = patch["logs"][-1]
    assert (entry.step if hasattr(entry, "step") else entry["step"]) == "data_ingestion"
    assert (entry.detail if hasattr(entry, "detail") else entry["detail"]) == patch["error"]


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
    called: list[dict] = []
    mod = ModuleType("pytesseract")
    mod.Output = SimpleNamespace(DICT="dict")  # type: ignore[attr-defined]

    def image_to_data(*a, **k):
        called.append(k)
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


def test_ocr_decodes_png_and_nothing_else_and_gives_tesseract_a_timeout(fake_tesseract, monkeypatch):
    setting(monkeypatch, "pdf_ocr_seconds_per_page", 11)
    ocr_service._try_tesseract_ocr(_FakePage(_image_bytes("PNG")))
    assert len(fake_tesseract) == 1 and fake_tesseract[0]["timeout"] == 11
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
        has_tables=True, warnings=["w"], metadata={"title": "t"}, embedded_xml=["<a/>"],
    )
    assert pdf_isolation._from_payload(json.loads(json.dumps(asdict(result)))) == result
