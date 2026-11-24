"""Hostile text in any field of any report cannot become markup, style or a fetch.

Every report builder is fed a benign name and then hostile strings in every field it interpolates (company,
period, titles, descriptions, member names, notes, dict keys). The HTML it produces must have exactly the
tags and attributes of the benign render, a CSS string that closes where it should, and (real WeasyPrint,
CI) the render must request nothing from a localhost listener.
"""
from __future__ import annotations

import html
import re
import threading
from collections import Counter
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services.pdf_escape import css_string, escape_tree

PORT_PLACEHOLDER = "{port}"
HOSTILE = [
    "</style><img src=x onerror=alert(1)>",
    '"; content: url(http://127.0.0.1:{port}/css); }',
    "<img src=http://127.0.0.1:{port}/img.png>",
    "feed\x0cform\x0bvtab",
    "back\\A slash\\22 quote",
    "line\nbreak\r\n<script>x()</script>",
    "R&D 'ArGe' \"Ltd\" <b>bold</b> &amp;",
]


class Structure(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: Counter[str] = Counter()
        self.attrs: Counter[str] = Counter()
        self.style = ""
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        self.tags[tag] += 1
        for name, _ in attrs:
            self.attrs[f"{tag}.{name}"] += 1
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.style += data


def structure(html: str) -> Structure:
    s = Structure()
    s.feed(html)
    return s


def make_all(text: str) -> dict[str, str]:
    """Every report builder, with `text` in every user-typed field."""
    from app.api.reports_pdf import _build_compliance_cert_html
    from app.services.executive_report_pdf import _build_html as executive_html
    from app.services.pdf import PDFEngine, build_cfo_summary_context
    from app.services.pdf_export import render_board_deck_html
    from app.services.unified_report import _build_unified_html

    t = text
    dashboard = {
        "pnl": {"narrative": t, "currency_note": t, "opex": {t: 1000}, "currency": "TRY", "revenue": 10, "net_income": 5},
        "cashflow": {
            "monthly_series": [{"month": t, "net": 5}],
            "alerts": [{"level": "warning", "message": t, "description": t, "title": t}],
        },
        "forecast": {"narrative": t, "scenarios": {"base": {"label": t, "twelve_month_net": 1}}, "alerts": [{"level": "critical", "message": t}]},
        "anomalies": [{"severity": "high", "description": t, "anomaly_type": t, "category": t, "title": t}],
        "recommendations": [t],
    }
    deck = {
        "title": t, "period": t, "generated_at": "2026-01-01T00:00:00", "one_page_summary": t,
        "slides": [{"slide_number": 1, "title": t, "headline": t, "bullets": [t], "narrative": t,
                    "priorities": [{"rank": 1, "title": t, "owner": t, "timeline": t, "effort": t}],
                    "actions": [{"action": t, "owner": t, "financial_impact": t}]}],
    }
    okr = {"narrative": t, "objectives": [{"title": t, "overall_status": "on_track", "score": 0.5,
                                           "key_results": [{"kr": t, "actual": 1, "target": 2, "unit": t, "progress_pct": 50}]}]}
    unified = {
        "executive_summary": {"company_name": t, "reporting_period": t, "agents_available": [t],
                              "headline_revenue": t, "headline_net_margin": t, "cross_risk_count": 1},
        "sections": [{"section": t, "metrics": {t: t}, "top_risks": [{"severity": t, "message": t}], "quick_wins": [{"action": t}]}],
    }
    ctx = build_cfo_summary_context(dashboard, company_name=t, period=t)
    engine = PDFEngine()
    return {
        "executive": executive_html(dashboard, t, t, "01.01.2026"),
        "board_deck": render_board_deck_html(deck, okr),
        "unified": _build_unified_html(unified),
        "compliance_cert": _build_compliance_cert_html(t, t, t, t, t, t, t, t),
        "cfo_summary": engine._render_html("cfo_summary", ctx),
        "executive_brief": engine._render_html("executive_brief", ctx),
    }


BENIGN = make_all("Firma")


@pytest.mark.parametrize("payload", HOSTILE)
@pytest.mark.parametrize("report", sorted(BENIGN))
def test_hostile_text_adds_no_tag_attribute_or_style(report, payload):
    hostile = make_all(payload.replace(PORT_PLACEHOLDER, "9"))[report]
    benign, got = structure(BENIGN[report]), structure(hostile)
    assert payload.replace(PORT_PLACEHOLDER, "9") in html.unescape(hostile), f"{report}: the text never reached the page, the test proves nothing"
    assert got.tags == benign.tags, f"{report}: markup injected"
    assert got.attrs == benign.attrs, f"{report}: attribute injected"
    assert "<" not in got.style, report


@pytest.mark.parametrize("payload", HOSTILE)
def test_the_page_margin_css_string_closes_where_it_should(payload):
    page = make_all(payload.replace(PORT_PLACEHOLDER, "9"))["executive"]
    line = next(line for line in page.splitlines() if line.strip().startswith('content: "'))
    assert re.fullmatch(r'\s*content: "(?:[^"\\\n]|\\[0-9a-f]+ )*";', line), line


def test_css_string_escapes_by_the_css_rules_not_a_blacklist():
    assert css_string('a"b\\c<d>e&f\'g') == "a\\22 b\\5c c\\3c d\\3e e\\26 f\\27 g"
    assert css_string("x\x0cy\nz\r w\x00") == "x y z  w "
    assert css_string("Şirket A.Ş. · 2026-Q1") == "Şirket A.Ş. · 2026-Q1"  # ordinary Turkish text is untouched


def test_escape_tree_escapes_strings_keys_and_nested_values_only():
    out = escape_tree({"a<": ["<b>", ("&", 3)], "n": 1.5, "x": None})
    assert out == {"a&lt;": ["&lt;b&gt;", ("&amp;", 3)], "n": 1.5, "x": None}


# ── Real WeasyPrint: nothing is requested (CI; skipped where Pango is missing) ──────────────

@pytest.fixture
def listener():
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_rendering_every_report_with_hostile_text_makes_no_request(listener):
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        pytest.skip(f"WeasyPrint is not usable here: {exc}")
    from app.services.pdf_fetch import deny_fetcher

    port, paths = listener
    for payload in HOSTILE:
        for name, page in make_all(payload.replace(PORT_PLACEHOLDER, str(port))).items():
            assert HTML(string=page, url_fetcher=deny_fetcher()).write_pdf().startswith(b"%PDF"), name
    assert paths == []


# ── reportlab: `Paragraph` parses its text as mini-markup ──────────────────────────────────

def _paragraph_tags(monkeypatch, builder_module, build, text: str) -> tuple[Counter[str], list[str]]:
    """Run a reportlab builder with `text` in every field; the tags in every Paragraph it created, and its texts."""
    reportlab = pytest.importorskip("reportlab")
    assert reportlab
    seen: list[str] = []
    real = builder_module.Paragraph

    def spy(body, *args, **kwargs):
        seen.append(body)
        return real(body, *args, **kwargs)

    monkeypatch.setattr(builder_module, "Paragraph", spy)
    out = build(text)
    assert out[:4] == b"%PDF" or isinstance(out, bytes)
    tags: Counter[str] = Counter()
    for body in seen:
        tags.update(re.findall(r"</?\s*([a-zA-Z][a-zA-Z0-9]*)", body))
    return tags, seen


def _board_deck_exporter(text: str) -> bytes:
    from app.services.board_deck_pdf import BoardDeckPDFExporter

    return BoardDeckPDFExporter.generate_pdf_bytes(
        pnl={"revenue": 1000, "net_income": 100, "narrative": text, "cogs": 1}, cashflow={}, forecast={},
        company_name=text, period=text,
        anomalies=[{"severity": text, "description": text}], alerts=[{"severity": text, "message": text}],
    )


def _board_deck_builder(text: str) -> bytes:
    from app.services.board_deck_pdf import BoardDeckPDFBuilder

    deck = {
        "company_name": text, "period": text, "health_score": text, "health_label": text, "executive_summary": text,
        "top_priorities": [text], "insights": [{"severity": text, "title": text, "description": text}],
        "swot": {"strengths": [{"text": text}], "weaknesses": [text], "opportunities": [text], "threats": [text]},
        "kri_posture": {"kri_score": text, "counts": {"red": text}},
    }
    return BoardDeckPDFBuilder().build_pdf(deck)


def _smmm_packet(text: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        summary={"period": text, "primary_currency": text, "reconciliation": {"action": text}}, job_id=text, status=text,
        content_hash=text, smmm_statement=text, finalized_by_user_id=text, finalized_at=text,
        payload={"entries": [{"decision_source": "ai_auto_posted", "date": "2026-01-01", "account_code": text,
                              "description": text, "currency": text, "review": {"corrected_account": text, "note": text}}]},
    )


@pytest.mark.parametrize("payload", HOSTILE)
def test_board_deck_builder_text_cannot_become_reportlab_markup(monkeypatch, payload):
    from app.services import board_deck_pdf

    benign, _ = _paragraph_tags(monkeypatch, board_deck_pdf, _board_deck_builder, "Firma")
    hostile, texts = _paragraph_tags(monkeypatch, board_deck_pdf, _board_deck_builder, payload.replace(PORT_PLACEHOLDER, "9"))
    assert hostile == benign, "markup injected into a Paragraph"
    assert any("&lt;" in t or "&amp;" in t or "&gt;" in t for t in texts) or ("<" not in payload and "&" not in payload)


@pytest.mark.parametrize("payload", HOSTILE)
def test_board_deck_exporter_text_cannot_become_reportlab_markup(monkeypatch, payload):
    from app.services import board_deck_pdf

    benign, _ = _paragraph_tags(monkeypatch, board_deck_pdf, _board_deck_exporter, "Firma")
    hostile, _ = _paragraph_tags(monkeypatch, board_deck_pdf, _board_deck_exporter, payload.replace(PORT_PLACEHOLDER, "9"))
    assert hostile == benign, "markup injected into a Paragraph"


@pytest.mark.parametrize("payload", HOSTILE)
def test_smmm_defensibility_pdf_text_cannot_become_reportlab_markup(monkeypatch, payload):
    from app.services import smmm_defensibility_pdf as smmm

    def build(text: str) -> bytes:
        body, media = smmm.render_packet(_smmm_packet(text))
        assert media == "application/pdf"
        return body

    benign, _ = _paragraph_tags(monkeypatch, smmm, build, "Firma")
    hostile, _ = _paragraph_tags(monkeypatch, smmm, build, payload.replace(PORT_PLACEHOLDER, "9"))
    assert hostile == benign


def test_the_narrative_is_cut_before_it_is_escaped_so_no_entity_is_split():
    from app.services.executive_report_pdf import _build_html

    narrative = "R&D " * 150   # 600 characters, every fourth one an ampersand
    page = _build_html({"pnl": {"narrative": narrative}, "forecast": {"narrative": narrative}}, "Firma", "2026-Q1", "01.01.2026")
    assert html.escape(narrative[:400]) in page and html.escape(narrative[:300]) in page
    assert "R&amp;D R&amp;D R&amp;D" in page and not re.search(r"&(?:a|am|amp)?[^a-z;]", page.split("narrative-box")[1].split("</div>")[0][-12:])
