"""
PDF Export Service — renders CEO board deck to a printable PDF using WeasyPrint.

Design:
  - Pure function: board_deck dict → bytes (PDF)
  - HTML template is generated in-memory (no file I/O)
  - CSS is embedded for self-contained output
  - No external font dependencies (uses system fonts / sans-serif fallback)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── HTML/CSS template ─────────────────────────────────────────────────────────

_BASE_CSS = """
@page {
  size: A4 landscape;
  margin: 1.5cm 2cm;
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-size: 9pt;
    color: #666;
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 11pt;
  color: #1a1a2e;
  background: #ffffff;
}

.cover {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  height: 100vh;
  padding: 3cm;
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
  color: white;
  page-break-after: always;
}

.cover h1 { font-size: 28pt; font-weight: 700; margin-bottom: 0.5cm; }
.cover .subtitle { font-size: 14pt; opacity: 0.8; margin-bottom: 1cm; }
.cover .meta { font-size: 10pt; opacity: 0.6; }

.slide {
  page-break-after: always;
  padding: 1cm 0;
}

.slide:last-child { page-break-after: avoid; }

.slide-header {
  border-bottom: 3px solid #2563eb;
  padding-bottom: 0.3cm;
  margin-bottom: 0.6cm;
  display: flex;
  align-items: baseline;
  gap: 0.5cm;
}

.slide-number {
  font-size: 9pt;
  color: #2563eb;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.slide-title {
  font-size: 18pt;
  font-weight: 700;
  color: #0f172a;
}

.narrative {
  font-size: 10pt;
  color: #475569;
  line-height: 1.5;
  margin-bottom: 0.5cm;
  font-style: italic;
}

/* Metrics grid */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(4cm, 1fr));
  gap: 0.4cm;
  margin-bottom: 0.5cm;
}

.metric-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0.4cm;
}

.metric-label {
  font-size: 8pt;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  margin-bottom: 0.1cm;
}

.metric-value {
  font-size: 14pt;
  font-weight: 700;
  color: #0f172a;
}

.metric-value.positive { color: #16a34a; }
.metric-value.negative { color: #dc2626; }

/* Risk table */
.risk-table { width: 100%; border-collapse: collapse; font-size: 9pt; }
.risk-table th {
  background: #1e3a5f;
  color: white;
  padding: 0.2cm 0.3cm;
  text-align: left;
  font-size: 8pt;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.risk-table td { padding: 0.2cm 0.3cm; border-bottom: 1px solid #e2e8f0; }
.risk-table tr:nth-child(even) td { background: #f8fafc; }

.badge {
  display: inline-block;
  padding: 0.05cm 0.2cm;
  border-radius: 3px;
  font-size: 8pt;
  font-weight: 600;
}
.badge-critical { background: #fee2e2; color: #dc2626; }
.badge-high     { background: #ffedd5; color: #ea580c; }
.badge-medium   { background: #fef9c3; color: #ca8a04; }
.badge-low      { background: #dbeafe; color: #2563eb; }

/* Priority list */
.priority-list { list-style: none; }
.priority-item {
  display: flex;
  align-items: flex-start;
  gap: 0.4cm;
  padding: 0.3cm 0;
  border-bottom: 1px solid #f1f5f9;
}
.priority-rank {
  flex-shrink: 0;
  width: 0.8cm;
  height: 0.8cm;
  background: #2563eb;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9pt;
  font-weight: 700;
}
.priority-body { flex: 1; }
.priority-title { font-size: 11pt; font-weight: 600; color: #0f172a; }
.priority-meta  { font-size: 9pt; color: #64748b; margin-top: 0.1cm; }

/* One-pager */
.one-pager {
  page-break-before: always;
  padding: 0.5cm 0;
}
.one-pager pre {
  font-family: "Courier New", Courier, monospace;
  font-size: 9pt;
  line-height: 1.6;
  white-space: pre-wrap;
  color: #334155;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0.5cm;
}

/* OKR section */
.okr-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(7cm, 1fr));
  gap: 0.4cm;
}
.okr-card {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0.4cm;
}
.okr-title { font-size: 10pt; font-weight: 600; margin-bottom: 0.2cm; }
.okr-status-badge {
  display: inline-block;
  padding: 0.05cm 0.2cm;
  border-radius: 3px;
  font-size: 8pt;
  font-weight: 600;
  margin-bottom: 0.2cm;
}
.badge-achieved  { background: #dcfce7; color: #16a34a; }
.badge-on_track  { background: #dbeafe; color: #2563eb; }
.badge-at_risk   { background: #fef9c3; color: #ca8a04; }
.badge-off_track { background: #fee2e2; color: #dc2626; }

.progress-bar-bg {
  background: #e2e8f0;
  border-radius: 3px;
  height: 6px;
  width: 100%;
  margin: 0.15cm 0;
}
.progress-bar-fill {
  height: 6px;
  border-radius: 3px;
  background: #2563eb;
}

.kr-item { font-size: 8.5pt; color: #475569; margin-top: 0.15cm; }
"""


def _severity_badge(severity: str) -> str:
    cls = f"badge badge-{severity.lower()}"
    return f'<span class="{cls}">{severity.upper()}</span>'


def _okr_status_badge(status: str) -> str:
    cls = f"okr-status-badge badge-{status}"
    labels = {"achieved": "Achieved", "on_track": "On Track", "at_risk": "At Risk", "off_track": "Off Track"}
    return f'<span class="{cls}">{labels.get(status, status)}</span>'


def _render_slide(slide: dict[str, Any], index: int) -> str:
    chart_type = slide.get("chart_type", "")
    num = slide.get("slide_number", index + 1)
    title = slide.get("title", f"Slide {num}")
    narrative = slide.get("narrative", "")

    parts = [
        f'<div class="slide">',
        f'  <div class="slide-header">',
        f'    <span class="slide-number">Slide {num}</span>',
        f'    <span class="slide-title">{title}</span>',
        f'  </div>',
    ]

    if narrative:
        parts.append(f'  <p class="narrative">{narrative}</p>')

    # Metrics grid
    metrics = slide.get("key_metrics") or []
    if metrics:
        parts.append('  <div class="metrics-grid">')
        for m in metrics:
            trend_cls = ""
            if m.get("trend") == "positive":
                trend_cls = " positive"
            elif m.get("trend") == "negative":
                trend_cls = " negative"
            parts.append(
                f'    <div class="metric-card">'
                f'<div class="metric-label">{m["label"]}</div>'
                f'<div class="metric-value{trend_cls}">{m["value"]}</div>'
                f'</div>'
            )
        parts.append('  </div>')

    # Risk table
    risks = slide.get("risks") or []
    if risks:
        parts.append(
            '  <table class="risk-table">'
            '<tr><th>Risk</th><th>Severity</th><th>Domains</th><th>Action</th><th>Impact</th></tr>'
        )
        for r in risks:
            domains = ", ".join(r.get("domains") or [])
            parts.append(
                f'    <tr>'
                f'<td><strong>{r.get("title","")}</strong></td>'
                f'<td>{_severity_badge(r.get("severity","low"))}</td>'
                f'<td>{domains}</td>'
                f'<td>{r.get("action","")}</td>'
                f'<td>{r.get("financial_impact","Indirect")}</td>'
                f'</tr>'
            )
        parts.append('  </table>')

    # Priorities
    priorities = slide.get("priorities") or []
    if priorities:
        parts.append('  <ul class="priority-list">')
        for p in priorities:
            parts.append(
                f'  <li class="priority-item">'
                f'<span class="priority-rank">{p["rank"]}</span>'
                f'<div class="priority-body">'
                f'<div class="priority-title">{p.get("title","")}</div>'
                f'<div class="priority-meta">Owner: {p.get("owner","CEO")} · Timeline: {p.get("timeline","TBD")} · Effort: {p.get("effort","medium")}</div>'
                f'</div></li>'
            )
        parts.append('  </ul>')

    parts.append('</div>')
    return "\n".join(parts)


def _render_okr_section(okr_status: dict[str, Any]) -> str:
    """Render OKR tracking as an extra PDF slide."""
    objectives = okr_status.get("objectives") or []
    narrative = okr_status.get("narrative", "")
    period = okr_status.get("period", "")

    parts = [
        '<div class="slide">',
        '  <div class="slide-header">',
        '    <span class="slide-number">Appendix</span>',
        '    <span class="slide-title">OKR Tracking</span>',
        '  </div>',
    ]

    if narrative:
        parts.append(f'  <p class="narrative">{narrative}</p>')

    parts.append('  <div class="okr-grid">')
    for obj in objectives:
        status = obj.get("overall_status", "off_track")
        score_pct = round(obj.get("score", 0) * 100)
        bar_color = {
            "achieved": "#16a34a", "on_track": "#2563eb",
            "at_risk": "#ca8a04", "off_track": "#dc2626",
        }.get(status, "#2563eb")

        krs_html = ""
        for kr in obj.get("key_results") or []:
            krs_html += (
                f'<div class="kr-item">• {kr["kr"]}: '
                f'{kr["actual"] if kr["actual"] is not None else "—"}/{kr["target"]} {kr["unit"]} '
                f'({kr["progress_pct"]}%)</div>'
            )

        parts.append(
            f'  <div class="okr-card">'
            f'<div class="okr-title">{obj.get("title","")}</div>'
            f'{_okr_status_badge(status)}'
            f'<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:{score_pct}%;background:{bar_color}"></div></div>'
            f'{krs_html}'
            f'</div>'
        )

    parts.append('  </div>')
    parts.append('</div>')
    return "\n".join(parts)


def render_board_deck_html(
    board_deck: dict[str, Any],
    okr_status: dict[str, Any] | None = None,
) -> str:
    """
    Build a complete HTML document from board_deck (and optional OKR status).
    Suitable for WeasyPrint rendering.
    """
    title = board_deck.get("title", "Board Deck")
    period = board_deck.get("period", "")
    generated_at = board_deck.get("generated_at", "")
    slides = board_deck.get("slides") or []
    one_pager = board_deck.get("one_page_summary", "")

    # Cover page
    cover_html = f"""
    <div class="cover">
      <h1>{title}</h1>
      <div class="subtitle">Board of Directors Presentation</div>
      <div class="meta">Period: {period} · Generated: {generated_at[:10] if generated_at else ""}</div>
    </div>
    """

    # Slide pages
    slides_html = "\n".join(_render_slide(s, i) for i, s in enumerate(slides))

    # OKR appendix
    okr_html = _render_okr_section(okr_status) if okr_status else ""

    # One-pager appendix
    one_pager_html = ""
    if one_pager:
        one_pager_html = f"""
        <div class="one-pager">
          <div class="slide-header">
            <span class="slide-number">Appendix</span>
            <span class="slide-title">Executive Summary</span>
          </div>
          <pre>{one_pager}</pre>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{_BASE_CSS}</style>
</head>
<body>
{cover_html}
{slides_html}
{okr_html}
{one_pager_html}
</body>
</html>"""


def board_deck_to_pdf(
    board_deck: dict[str, Any],
    okr_status: dict[str, Any] | None = None,
) -> bytes:
    """
    Render board_deck dict to PDF bytes using WeasyPrint.

    Raises ImportError if weasyprint is not installed.
    Raises RuntimeError on render failure.
    """
    try:
        from weasyprint import HTML, CSS  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "weasyprint is required for PDF export. "
            "Install it: pip install weasyprint==62.3"
        ) from exc

    html_content = render_board_deck_html(board_deck, okr_status)

    try:
        pdf_bytes: bytes = HTML(string=html_content).write_pdf()
        logger.info(
            "PDF generated: %d bytes, slides=%d",
            len(pdf_bytes),
            len(board_deck.get("slides") or []),
        )
        return pdf_bytes
    except Exception as exc:
        logger.exception("WeasyPrint render failed")
        raise RuntimeError(f"PDF render failed: {exc}") from exc
