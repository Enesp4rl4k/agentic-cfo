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
    assert scan.found == [] and scan.unread == [{"name": "fatura.xml", "reason": "unsupported_filter"}]


def test_an_attachment_over_the_cap_is_reported_for_flate_and_plain_streams(tmp_path):
    big = UBL.replace(b"</Invoice>", b"<N>" + b"x" * 20_000 + b"</N></Invoice>")
    for flate in (False, True):
        scan = pdf_embedded.scan_attachments(make_pdf(tmp_path / f"a{flate}.pdf", {"b.xml": big}, flate=flate), limit=5_000)
        assert scan.found == [] and scan.unread == [{"name": "b.xml", "reason": "too_large"}], flate


def test_an_encrypted_pdf_declares_attachments_it_cannot_read_and_says_so(tmp_path):
    scan = pdf_embedded.scan_attachments(make_pdf(tmp_path / "a.pdf", {"fatura.xml": UBL}, encrypt=True))
    assert scan.found == [] and scan.unread == [{"name": "", "reason": "encrypted"}]


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


# ── Memory: the children must fit the container ─────────────────────────────────────────────

def settings_for(child=512, sheet=512, slots=1, procs=2):
    return SimpleNamespace(pdf_child_memory_mb=child, sheet_child_memory_mb=sheet, pdf_parse_concurrency=slots, parse_process_count=procs)


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
    limit_files(monkeypatch, tmp_path, v2=str(1280 * MB))
    assert preflight._parser_memory_findings(settings_for(), {}) == []   # 512 x 1 x 2 = 1024 <= 1280
    monkeypatch.setattr(preflight, "_CGROUP_LIMIT_FILES", (tmp_path / "absent",))
    assert preflight._parser_memory_findings(settings_for(child=99999), {}) == []


def test_children_that_can_exceed_the_container_warn(tmp_path, monkeypatch):
    limit_files(monkeypatch, tmp_path, v2=str(1280 * MB))
    (finding,) = preflight._parser_memory_findings(settings_for(child=512, slots=2, procs=2), {})   # 2048 > 1280
    assert finding.code == "parser_memory_exceeds_container" and finding.severity == preflight.WARN
    assert "2048" in finding.message and "1280" in finding.message and "parser-sizing.md" in finding.message


def test_one_child_as_big_as_the_container_is_fatal(tmp_path, monkeypatch):
    limit_files(monkeypatch, tmp_path, v2=str(1280 * MB))
    (finding,) = preflight._parser_memory_findings(settings_for(child=3072), {})   # the old default
    assert finding.code == "parser_memory_impossible" and finding.severity == preflight.FATAL


def test_the_shipped_defaults_fit_the_production_container():
    s = get_settings()
    compose = (pdf_isolation.Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "mem_limit: 1280m" in compose
    assert max(s.pdf_child_memory_mb, s.sheet_child_memory_mb) * s.pdf_parse_concurrency * s.parse_process_count <= 1280


# ── reportlab text ──────────────────────────────────────────────────────────────────────────

def test_rl_text_escapes_reportlab_markup_and_slices_before_escaping():
    from app.services.pdf_escape import rl_text

    assert rl_text("R&D <b>x</b> > y") == "R&amp;D &lt;b&gt;x&lt;/b&gt; &gt; y"
    assert rl_text(None) == "None" and rl_text(5) == "5"
    narrative = "&" * 399 + "x"
    assert rl_text(narrative[:400]).count("&amp;") == 399   # cut first: no half entity
