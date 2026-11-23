"""A report render fetches nothing, whatever a company typed into its name.

WeasyPrint resolves `<img src>`, `<link>`, `@import` and CSS `url()` by fetching. The four report
builders put strings a person typed (company name, titles, messages) into the HTML, so
`<img src="http://169.254.169.254/...">` as a company name was a server-side request. Every render now
passes `app.services.pdf_fetch.deny_fetch`. Real-WeasyPrint tests skip where Pango is not installed (a
Windows dev box); CI has it. The server below is on localhost: no test reaches outside.
"""
from __future__ import annotations

import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services.pdf_fetch import deny_fetch


class _Hits:
    def __init__(self) -> None:
        self.paths: list[str] = []


@pytest.fixture
def local_server():
    hits = _Hits()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.paths.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):  # silence
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _weasyprint_or_skip():
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        pytest.skip(f"WeasyPrint is not usable on this machine: {exc}")
    return HTML


def test_deny_fetch_refuses_every_scheme():
    for url in ("http://169.254.169.254/latest/meta-data/", "https://example.com/a.css", "file:///etc/passwd",
                "data:image/png;base64,AAAA", "ftp://host/x"):
        with pytest.raises(ValueError):
            deny_fetch(url)


# ── Every builder passes the fetcher (runs everywhere, WeasyPrint stubbed) ────────────────────

@pytest.fixture
def fake_weasyprint(monkeypatch):
    calls: list[dict] = []

    class FakeHTML:
        def __init__(self, *a, **kw):
            calls.append(kw)

        def write_pdf(self, *a, **kw):
            return b"%PDF-fake"

    mod = types.ModuleType("weasyprint")
    mod.HTML = FakeHTML  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weasyprint", mod)
    return calls


def test_all_four_renderers_pass_the_denying_fetcher(fake_weasyprint):
    from app.services.executive_report_pdf import generate_executive_report
    from app.services.pdf import PDFEngine
    from app.services.pdf_export import board_deck_to_pdf
    from app.services.unified_report import generate_unified_pdf

    PDFEngine()._html_to_pdf("<html></html>")
    board_deck_to_pdf({"title": "T", "slides": []})
    generate_unified_pdf({}, company_name="Firma")
    generate_executive_report({}, company_name="Firma")
    assert len(fake_weasyprint) == 4
    assert all(kw.get("url_fetcher") is deny_fetch for kw in fake_weasyprint)


def test_the_executive_report_margin_cannot_break_out_of_its_css_string(fake_weasyprint):
    from app.services.executive_report_pdf import _build_html

    name = '"; } body { background: url(http://169.254.169.254/x) } </style><img src="http://169.254.169.254/y'
    page = _build_html({}, name, "2026-Q1", "01.01.2026")
    assert "<img" not in page and "</style><" not in page
    margin = next(line for line in page.splitlines() if line.strip().startswith('content: "'))
    assert margin.count('"') == 2  # one opening, one closing quote: the name added none


def test_the_template_engine_escapes_a_company_name():
    from app.services.pdf import PDFEngine, build_cfo_summary_context

    ctx = build_cfo_summary_context({}, company_name='<img src="http://169.254.169.254/">')
    out = PDFEngine()._render_html("executive_brief", ctx)
    assert "<img" not in out and "&lt;img" in out


# ── Real WeasyPrint against a localhost listener ──────────────────────────────────────────────

def _payload(base: str, tag: str) -> str:
    return f'<img src="{base}/{tag}.png"><link rel="stylesheet" href="{base}/{tag}.css">'


def test_control_the_default_fetcher_does_request_the_url(local_server):
    """Without this the tests below prove nothing: it shows the payload does reach the network."""
    HTML = _weasyprint_or_skip()
    base, hits = local_server
    HTML(string=_payload(base, "control")).write_pdf()
    assert any(p.startswith("/control") for p in hits.paths)


def test_a_payload_in_a_company_name_makes_no_request(local_server):
    _weasyprint_or_skip()
    base, hits = local_server
    from app.services.executive_report_pdf import generate_executive_report
    from app.services.pdf import PDFEngine
    from app.services.pdf_export import board_deck_to_pdf
    from app.services.unified_report import generate_unified_pdf

    name = _payload(base, "name")
    PDFEngine()._html_to_pdf(f"<html><body>{name}</body></html>")
    board_deck_to_pdf({"title": name, "period": name, "slides": [], "one_page_summary": name})
    generate_unified_pdf({}, company_name=name)
    generate_executive_report({}, company_name=name, period=name)
    assert hits.paths == []


def test_css_url_and_import_make_no_request(local_server):
    HTML = _weasyprint_or_skip()
    base, hits = local_server
    html = (f'<style>@import url("{base}/imp.css"); body {{ background: url({base}/bg.png) }}'
            f'@font-face {{ font-family: x; src: url({base}/f.woff) }}</style><p>x</p>')
    from app.services.pdf_fetch import deny_fetch as fetcher

    assert HTML(string=html, url_fetcher=fetcher).write_pdf().startswith(b"%PDF")
    assert hits.paths == []
