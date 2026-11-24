"""Follow-ups to the PDF isolation review: stderr cap, busy refusal, memory sizing preflight, attachments
found through the catalog (with or without /Type, Flate, other filters, oversized, encrypted) and SAID when
not read, and reportlab text escaping.

PDFs are generated here with PyMuPDF (nothing downloaded); a hostile child is a one-line interpreter script.
"""
from __future__ import annotations

import asyncio
import sys
import zlib
from types import SimpleNamespace

import pytest

from app.agents.state import SkillResult
from app.config import get_settings
from app.core import preflight
from app.services import pdf_embedded, pdf_isolation
from app.services.ocr_service import extract_text_from_pdf

pymupdf = pytest.importorskip("pymupdf")

UBL = b"<Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'><ID>A1</ID></Invoice>"
NOTE = "PDF'in eki okunamadı; metinden okundu"


@pytest.fixture(autouse=True)
def fresh_cache():
    pdf_isolation._cache.clear()
    yield
    pdf_isolation._cache.clear()


def make_pdf(path, attachments: dict[str, bytes], *, drop_type: bool = False, flate: bool = False,
             filter_name: str | None = None, encrypt: bool = False) -> str:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "01.03.2026 HAVALE GELEN ODEME ACIKLAMA 1.250,00 TL", fontsize=10)
    for name, data in attachments.items():
        doc.embfile_add(name, data)
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type") == ("name", "/EmbeddedFile"):
            if flate:
                doc.update_stream(xref, doc.xref_stream_raw(xref), compress=True)   # deflates the bytes ...
                doc.xref_set_key(xref, "Filter", "/FlateDecode")                      # ... and the object must say so
            if filter_name:
                doc.update_stream(xref, b"3c496e766f6963652f3e>", compress=False)
                doc.xref_set_key(xref, "Filter", filter_name)
            if drop_type:
                doc.xref_set_key(xref, "Type", "null")
    options: dict = {}
    if encrypt:
        options.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    doc.save(str(path), **options)
    doc.close()
    return str(path)


# ── Attachments: found through the name tree, not by an optional marker ─────────────────────

def test_an_attachment_with_type_embeddedfile_is_read(tmp_path):
    scan = pdf_embedded.scan_attachments(make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}))
    assert scan.found == [UBL.decode()] and scan.unread == []


def test_an_attachment_without_type_is_still_read(tmp_path):
    path = make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}, drop_type=True)
    doc = pymupdf.open(path)
    assert not any(doc.xref_get_key(x, "Type") == ("name", "/EmbeddedFile") for x in range(1, doc.xref_length())), "the marker is still there"
    doc.close()
    # the old reader (marker only) found nothing here: that was silent loss
    scan = pdf_embedded.scan_attachments(path)
    assert scan.found == [UBL.decode()] and scan.unread == []


def test_a_flate_attachment_is_inflated_and_read(tmp_path):
    path = make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}, flate=True, drop_type=True)
    doc = pymupdf.open(path)
    streams = pdf_embedded.declared_streams(doc)
    assert streams and doc.xref_get_key(streams[0], "Filter")[1].replace(" ", "") in ("/FlateDecode", "[/FlateDecode]")
    doc.close()
    assert pdf_embedded.scan_attachments(path).found == [UBL.decode()]


def test_two_attachments_keep_pdf_order_and_a_non_ebelge_one_is_not_a_loss(tmp_path):
    path = make_pdf(tmp_path / "a.pdf", {"a.xml": UBL, "notlar.txt": b"hello", "b.xml": UBL.replace(b"A1", b"B2")}, drop_type=True)
    scan = pdf_embedded.scan_attachments(path)
    assert [("A1" in t, "B2" in t) for t in scan.found] == [(True, False), (False, True)] and scan.unread == []


def test_an_unsupported_filter_is_reported_not_skipped_silently(tmp_path):
    path = make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}, filter_name="/ASCIIHexDecode", drop_type=True)
    scan = pdf_embedded.scan_attachments(path)
    assert scan.found == [] and scan.unread == [{"name": "fatura.xml", "reason": "unsupported_filter", "candidate": True}]


def test_an_attachment_over_the_cap_is_reported_for_flate_and_plain_streams(tmp_path):
    big = UBL.replace(b"</Invoice>", b"<N>" + b"x" * 20_000 + b"</N></Invoice>")
    for flate in (False, True):
        scan = pdf_embedded.scan_attachments(make_pdf(tmp_path / f"a{flate}.pdf", {"b.xml": big}, flate=flate), limit=5_000)
        assert scan.found == [] and scan.unread == [{"name": "b.xml", "reason": "too_large", "candidate": True}], flate


def test_an_encrypted_pdf_declares_attachments_it_cannot_read_and_says_so(tmp_path):
    scan = pdf_embedded.scan_attachments(make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}, encrypt=True))
    assert scan.found == [] and scan.unread == [{"name": "", "reason": "encrypted", "candidate": False}]


def test_an_attachment_declaring_a_dtd_is_reported(tmp_path):
    hostile = b"<!DOCTYPE a [<!ENTITY b 'c'>]><Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'/>"
    scan = pdf_embedded.scan_attachments(make_pdf(tmp_path / "a.pdf", {"a.xml": hostile}))
    assert scan.found == [] and [u["reason"] for u in scan.unread] == ["unsafe_xml"]


def test_a_picture_attachment_with_an_unsupported_filter_is_not_reported_as_a_lost_invoice(tmp_path):
    path = make_pdf(tmp_path / "a.pdf", {"logo.png": b"x"}, filter_name="/DCTDecode", drop_type=True)
    assert pdf_embedded.scan_attachments(path).unread == []


def test_a_bomb_stream_is_still_capped_while_inflating():
    assert pdf_embedded.bounded_inflate(zlib.compress(b"0" * 5_000_000), limit=100_000) is None


# ── ... and the ingestion result carries the note ───────────────────────────────────────────

def test_the_note_reaches_the_ingestion_result_through_the_child_parse(tmp_path):
    import app.agents.data_ingestion as di

    path = make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}, filter_name="/ASCIIHexDecode", drop_type=True)
    result = extract_text_from_pdf(path)   # the parse the ingest door already made (child, cached)
    assert result.metadata["attachments_unread"][0]["reason"] == "unsupported_filter" and result.embedded_xml == []

    async def fake_read(*a, **k):
        return SkillResult(ok=True, patch={"transactions": []}, confidence=0.95, needs_review=False, detail="3 işlem")

    di._belgeyi_oku, original = fake_read, di._belgeyi_oku
    try:
        sonuc = asyncio.run(di._belgeyi_al(path, "pdf", {}, SimpleNamespace()))
    finally:
        di._belgeyi_oku = original
    assert NOTE in sonuc.detail and "The PDF's attachment could not be read" in sonuc.detail
    assert sonuc.needs_review is True and sonuc.detail.startswith("3 işlem")


def test_no_note_when_every_attachment_was_read_or_there_is_none(tmp_path):
    for name, attachments in (("none", {}), ("read", {"fatura.xml": UBL})):
        path = make_pdf(tmp_path / f"{name}.pdf", attachments)
        extract_text_from_pdf(path)
        assert pdf_isolation.attachment_note(path) is None


def test_a_note_never_starts_a_child(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL})
    monkeypatch.setattr(pdf_isolation, "_run_child", lambda *a: pytest.fail("a child was started"))
    assert pdf_isolation.attachment_note(path) is None   # nothing cached: no answer, no spawn


# ── stderr is read in fixed-size chunks and capped ──────────────────────────────────────────

def test_a_stderr_line_without_a_newline_cannot_grow_the_buffer():
    pending, kept = b"", 0
    for _ in range(200):                       # 12.8 MB of one endless line, 64 KB at a time
        lines, pending = pdf_isolation.split_stderr(pending, b"x" * 65536)
        assert len(pending) <= pdf_isolation._STDERR_LINE_CAP
        kept += sum(len(line) for line in lines)
        assert all(len(line) <= pdf_isolation._STDERR_LINE_CAP for line in lines)
    lines, pending = pdf_isolation.split_stderr(b"", b"@@OCR@@\nrest")
    assert lines == [b"@@OCR@@"] and pending == b"rest"


def test_a_child_flooding_stderr_is_killed_and_the_pdf_refused(tmp_path, monkeypatch):
    code = "import sys\nfor _ in range(200): sys.stderr.write('x' * 100000); sys.stderr.flush()"
    monkeypatch.setattr(pdf_isolation, "_WORKER_COMMAND", [sys.executable, "-c", code])
    monkeypatch.setattr(pdf_isolation, "_STDERR_TOTAL_LIMIT", 500_000)
    result = extract_text_from_pdf(make_pdf(tmp_path / "a.pdf", {}))
    assert result.metadata["refusal"]["code"] == "pdf_output_too_large"


# ── Concurrency: waiters time out with a visible refusal ────────────────────────────────────

def test_a_waiter_for_a_parser_slot_is_refused_as_busy_not_left_hanging(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "pdf_parse_concurrency", 1)
    monkeypatch.setattr(settings, "parse_queue_wait_seconds", 0)
    monkeypatch.setattr(pdf_isolation, "_slots", None)
    path = make_pdf(tmp_path / "a.pdf", {})
    with pdf_isolation._slot():
        result = pdf_isolation._run_child(path, False)
    assert result.metadata["refusal"]["code"] == "pdf_busy"
    assert "Sistem yoğun, tekrar deneyin" in result.warnings[0] and "busy" in pdf_isolation.PdfOkunamadi("pdf_busy", seconds=0).en
    assert "PDF okunamadı" in pdf_isolation.PdfOkunamadi("pdf_busy", seconds=60).user_text


def test_the_busy_refusal_is_not_cached_so_a_retry_reads_the_file(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "pdf_parse_concurrency", 1)
    monkeypatch.setattr(settings, "parse_queue_wait_seconds", 0)
    monkeypatch.setattr(pdf_isolation, "_slots", None)
    path = make_pdf(tmp_path / "a.pdf", {})
    with pdf_isolation._slot():
        assert pdf_isolation.guarded_extract(path).metadata["refusal"]["code"] == "pdf_busy"
    assert "HAVALE" in pdf_isolation.guarded_extract(path).text


# ── Memory: the children must fit the container (and only where children run) ──────────────

def settings_for(rss=800, slots=1, procs=2):
    return SimpleNamespace(parse_child_rss_mb=rss, pdf_parse_concurrency=slots, parse_process_count=procs)


def limit_files(monkeypatch, tmp_path, v2: str | None = None, v1: str | None = None):
    paths = []
    for name, text in (("memory.max", v2), ("memory.limit_in_bytes", v1)):
        p = tmp_path / name
        if text is not None:
            p.write_text(text)
        paths.append(p)
    monkeypatch.setattr(preflight, "_CGROUP_LIMIT_FILES", tuple(paths))


MB = 1024 * 1024


def test_the_cgroup_limit_is_read_from_v2_then_v1_and_unlimited_or_absent_is_none(tmp_path, monkeypatch):
    limit_files(monkeypatch, tmp_path, v2=str(1280 * MB))
    assert preflight.cgroup_memory_limit_mb() == 1280
    v1_dir = tmp_path / "v1"
    v1_dir.mkdir()
    limit_files(monkeypatch, v1_dir, v1=str(768 * MB))
    assert preflight.cgroup_memory_limit_mb() == 768
    limit_files(monkeypatch, tmp_path, v2="max")
    assert preflight.cgroup_memory_limit_mb() is None
    limit_files(monkeypatch, v1_dir, v1="9223372036854771712")
    assert preflight.cgroup_memory_limit_mb() is None
    monkeypatch.setattr(preflight, "_CGROUP_LIMIT_FILES", (tmp_path / "absent",))
    assert preflight.cgroup_memory_limit_mb() is None


def test_children_that_fit_say_nothing_and_a_host_without_cgroup_files_is_quiet(tmp_path, monkeypatch):
    limit_files(monkeypatch, tmp_path, v2=str(2560 * MB))
    assert preflight._parser_memory_findings(settings_for(), "api") == []   # (800 x 1 + 350) x 2 = 2300 <= 2560
    monkeypatch.setattr(preflight, "_CGROUP_LIMIT_FILES", (tmp_path / "absent",))
    assert preflight._parser_memory_findings(settings_for(rss=99999), "api") == []


def test_children_that_can_exceed_the_container_warn(tmp_path, monkeypatch):
    limit_files(monkeypatch, tmp_path, v2=str(1280 * MB))
    (finding,) = preflight._parser_memory_findings(settings_for(rss=800, slots=1, procs=2), "api")   # 2300 > 1280
    assert finding.code == "parser_memory_exceeds_container" and finding.severity == preflight.WARN
    assert "2300" in finding.message and "1280" in finding.message and "parser-sizing.md" in finding.message


def test_one_child_as_big_as_the_container_is_fatal_but_only_where_children_run(tmp_path, monkeypatch):
    limit_files(monkeypatch, tmp_path, v2=str(512 * MB))
    (finding,) = preflight._parser_memory_findings(settings_for(rss=800), "api")
    assert finding.code == "parser_memory_impossible" and finding.severity == preflight.FATAL
    for process in (None, "worker-maintenance", "migrate", "anything-else"):   # migrate, --db, maintenance: no children
        assert preflight._parser_memory_findings(settings_for(rss=800), process) == [], process


def test_an_arq_worker_counts_as_one_process_whatever_the_api_process_count_is(tmp_path, monkeypatch):   # (800 + 350) = 1150 fits 1200
    limit_files(monkeypatch, tmp_path, v2=str(1200 * MB))
    assert preflight._parser_memory_findings(settings_for(rss=800, procs=4), "worker") == []
    assert [f.code for f in preflight._parser_memory_findings(settings_for(rss=800, procs=4), "api")] == ["parser_memory_exceeds_container"]


def test_the_shipped_defaults_fit_the_production_container_and_the_backstop_is_above_the_budget():
    s = get_settings()
    assert s.pdf_child_memory_mb > s.parse_child_rss_mb, "RLIMIT_AS counts address space: it must sit above the resident budget"


# ── reportlab text ──────────────────────────────────────────────────────────────────────────

def test_rl_text_escapes_reportlab_markup_and_slices_before_escaping():
    from app.services.pdf_escape import rl_text

    assert rl_text("R&D <b>x</b> > y") == "R&amp;D &lt;b&gt;x&lt;/b&gt; &gt; y"
    assert rl_text(None) == "None" and rl_text(5) == "5"
    narrative = "&" * 399 + "x"
    assert rl_text(narrative[:400]).count("&amp;") == 399   # cut first: no half entity


# ── Resource limits: a MemoryError is a visible failure, never an empty page ───────────────

def page_pdf(path, pages: int) -> str:
    doc = pymupdf.open()
    for n in range(pages):
        doc.new_page().insert_text((50, 72), f"sayfa {n + 1}", fontsize=10)
    doc.save(str(path))
    doc.close()
    return str(path)


def force_strategies(monkeypatch, plumber):
    from app.services import ocr_service

    monkeypatch.setattr(ocr_service, "_try_native_extraction", lambda page: ("", 0.0))   # thin pages: pdfplumber is asked
    monkeypatch.setattr(ocr_service, "_try_pdfplumber_extraction", plumber)
    monkeypatch.setattr(ocr_service, "_try_tesseract_ocr", lambda page, dpi=300: ("", 0.0))


def test_a_memory_error_on_page_n_refuses_the_document_and_names_the_pages(tmp_path, monkeypatch):
    def plumber(file_path, page_num):
        if page_num == 2:
            raise MemoryError
        return "x " * 80, 0.9, False

    force_strategies(monkeypatch, plumber)
    result = pdf_isolation.parse_here(page_pdf(tmp_path / "a.pdf", 5))
    assert result.strategy_used == "failed" and result.text == ""            # not a success, not a partial text
    refusal = result.metadata["refusal"]
    assert refusal["code"] == "pdf_memory"
    error = pdf_isolation.PdfOkunamadi("pdf_memory", **refusal["params"])
    assert "dosya bellek sınırını aştı" in error.tr and "sayfa 3-5 okunamadı" in error.tr and "bölüp yükleyin" in error.tr
    assert "memory limit" in error.en and "page 3-5" in error.en and "split" in error.en
    assert "bozuk" not in error.tr   # not "damaged, download it again"


def test_a_memory_error_in_tesseract_is_not_swallowed_into_an_empty_page(tmp_path, monkeypatch):
    import types

    from app.services import ocr_service

    fake = types.ModuleType("pytesseract")
    fake.Output = SimpleNamespace(DICT="dict")

    def image_to_data(*a, **k):
        raise MemoryError

    fake.image_to_data = image_to_data
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    page = pymupdf.open(page_pdf(tmp_path / "a.pdf", 1))[0]
    with pytest.raises(MemoryError):
        ocr_service._try_tesseract_ocr(page, dpi=72)


def test_tesseract_ended_by_a_failed_allocation_counts_as_memory_but_other_failures_do_not():
    from app.services import ocr_service

    killed = RuntimeError("tesseract failed")
    killed.status = -6   # type: ignore[attr-defined]
    assert ocr_service._tesseract_ran_out_of_memory(killed)
    assert ocr_service._tesseract_ran_out_of_memory(RuntimeError("terminate called after throwing an instance of 'std::bad_alloc'"))
    assert not ocr_service._tesseract_ran_out_of_memory(RuntimeError("Error opening data file tur.traineddata"))


def test_a_child_that_reports_a_memory_error_or_is_killed_is_the_memory_refusal(tmp_path, monkeypatch):
    path = page_pdf(tmp_path / "a.pdf", 1)
    monkeypatch.setattr(pdf_isolation, "_WORKER_COMMAND", [sys.executable, "-c", "import sys; sys.stderr.write('@@MEM@@' + chr(10)); sys.exit(3)"])
    refusal = extract_text_from_pdf(path).metadata["refusal"]
    assert refusal["code"] == "pdf_memory"
    if sys.platform != "win32":   # the OOM killer's SIGKILL
        pdf_isolation._cache.clear()
        monkeypatch.setattr(pdf_isolation, "_WORKER_COMMAND", [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
        assert extract_text_from_pdf(path).metadata["refusal"]["code"] == "pdf_memory"


def test_an_unreadable_page_with_content_is_listed_as_a_note_and_holds_only_with_evidence(tmp_path, monkeypatch):
    import app.agents.data_ingestion as di
    from app.services import ocr_service

    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "01.03.2026 HAVALE GELEN ODEME ACIKLAMA 1.250,00 TL " * 3, fontsize=8)   # readable (native)
    doc.new_page().insert_text((50, 72), "ok", fontsize=10)   # a page with a little text no strategy can use
    doc.new_page()                                              # a genuinely blank page: a note, never a hold
    path = str(tmp_path / "a.pdf")
    doc.save(path)
    doc.close()
    # hermetic: whatever pdfplumber and Tesseract would make of "ok" on this machine, here they read nothing
    monkeypatch.setattr(ocr_service, "_try_pdfplumber_extraction", lambda file_path, page_num: ("", 0.0, False))
    monkeypatch.setattr(ocr_service, "_try_tesseract_ocr", lambda page, dpi=300: ("", 0.0))
    result = pdf_isolation.parse_here(path)
    assert result.metadata.get("pages_unread") == [2, 3]        # page 2 had content and gave nothing; page 3 is blank (a note either way)
    monkeypatch.setattr(pdf_isolation, "cached_result", lambda file_path: result)
    sonuc = SkillResult(ok=True, patch={}, confidence=0.95, needs_review=False, detail="3 işlem")
    pdf_isolation.apply_pdf_notes(sonuc, path)
    # nothing on the pages around it says rows are missing (no transaction rows at all): a visible note, no hold
    assert sonuc.needs_review is False and "2, 3. sayfada okunabilir metin yok (görsel/boş sayfa)" in sonuc.detail and "No readable text" in sonuc.detail
    assert di.apply_pdf_notes is pdf_isolation.apply_pdf_notes


# ── The hold is for e-Belge candidates only ─────────────────────────────────────────────────

def held_by(tmp_path, attachments, **options) -> tuple[bool, str]:
    path = make_pdf(tmp_path / "h.pdf", attachments, drop_type=True, **options)
    extract_text_from_pdf(path)
    sonuc = SkillResult(ok=True, patch={}, confidence=0.95, needs_review=False, detail="x")
    pdf_isolation.apply_pdf_notes(sonuc, path)
    return sonuc.needs_review, sonuc.detail


def test_an_unread_xml_attachment_holds_the_result_and_says_so(tmp_path):
    held, detail = held_by(tmp_path, {"fatura.xml": UBL}, filter_name="/ASCIIHexDecode")
    assert held is True and NOTE in detail


def test_an_unread_attachment_of_unknown_kind_gets_the_note_without_a_hold(tmp_path):
    held, detail = held_by(tmp_path, {"ek1": b"binary-ish"}, filter_name="/ASCIIHexDecode")   # no name extension, no XML bytes
    assert held is False and NOTE in detail


def test_an_encrypted_pdf_attachment_is_not_a_hold_candidate(tmp_path):
    path = make_pdf(tmp_path / "e.pdf", {"fatura.xml": UBL}, encrypt=True)
    assert pdf_embedded.scan_attachments(path).unread == [{"name": "", "reason": "encrypted", "candidate": False}]


def test_an_attachment_with_xml_content_but_no_name_is_a_candidate_by_its_first_bytes(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    doc.embfile_add("ek", b"x")
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type") == ("name", "/EmbeddedFile"):
            doc.update_stream(xref, b"<Invoice/>", compress=False)
            doc.xref_set_key(xref, "Filter", "/LZWDecode")
    path = str(tmp_path / "m.pdf")
    doc.save(path)
    doc.close()
    assert pdf_embedded.scan_attachments(path).unread == [{"name": "ek", "reason": "unsupported_filter", "candidate": True}]
