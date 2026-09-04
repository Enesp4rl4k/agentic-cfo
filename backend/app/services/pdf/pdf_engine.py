"""
PDFEngine — WeasyPrint tabanlı HTML → PDF dönüştürücü (Sprint M2)

Architecture
------------
- Jinja2 HTML şablonları → WeasyPrint → PDF bytes
- Türkçe karakter desteği (UTF-8 + embedded font)
- Report types: cfo_summary, board_deck, executive_brief, compliance_cert

Graceful degradation
--------------------
- WeasyPrint not installed → ReportLab fallback (plain text PDF)
- Jinja2 not installed → string format fallback

Usage
-----
    engine = PDFEngine()
    pdf_bytes = await engine.render("cfo_summary", context_dict)
    # Returns bytes ready to stream as response
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC
from typing import Any

from app.core.branding import get_brand

logger = logging.getLogger(__name__)

# ── HTML Templates ─────────────────────────────────────────────────────────────

_CFO_SUMMARY_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: Arial, sans-serif; font-size: 12px; color: #1a1a2e; margin: 40px; }
  .cover { text-align: center; padding: 80px 0; border-bottom: 3px solid #2563eb; }
  .cover h1 { font-size: 28px; color: #2563eb; margin-bottom: 8px; }
  .cover .subtitle { font-size: 16px; color: #666; }
  .cover .meta { margin-top: 40px; font-size: 11px; color: #999; }
  .section { page-break-inside: avoid; margin-top: 30px; }
  .section h2 { font-size: 16px; color: #2563eb; border-bottom: 1px solid #e4e4e7; padding-bottom: 6px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 12px; }
  .kpi-card { background: #f4f4f5; border-radius: 8px; padding: 12px; }
  .kpi-card .label { font-size: 10px; color: #71717a; }
  .kpi-card .value { font-size: 18px; font-weight: bold; color: #1a1a2e; }
  .alert-list { margin-top: 8px; }
  .alert-item { padding: 6px 10px; margin: 4px 0; border-radius: 4px; font-size: 11px; }
  .alert-critical { background: #fee2e2; color: #991b1b; }
  .alert-warning  { background: #fef3c7; color: #92400e; }
  .alert-info     { background: #dbeafe; color: #1e40af; }
  .narrative { font-style: italic; color: #555; font-size: 11px; line-height: 1.6; margin-top: 8px; }
  .recommendation { padding: 6px 12px; margin: 4px 0; background: #f0fdf4; border-left: 3px solid #22c55e; font-size: 11px; }
  .footer { text-align: center; font-size: 9px; color: #aaa; margin-top: 40px; border-top: 1px solid #e4e4e7; padding-top: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }
  th { background: #2563eb; color: white; padding: 6px 8px; text-align: left; }
  td { padding: 5px 8px; border-bottom: 1px solid #e4e4e7; }
  tr:nth-child(even) td { background: #f9fafb; }
  @page { size: A4; margin: 2cm; }
</style>
</head>
<body>

<!-- Cover -->
<div class="cover">
  <div style="font-size:48px; color:#2563eb;">📊</div>
  <h1>CFO Yönetici Raporu</h1>
  <div class="subtitle">{{ company_name or "Şirket" }}</div>
  <div class="meta">
    Dönem: {{ period or "Güncel" }} &nbsp;|&nbsp;
    Hazırlayan: {{ brand_name }} &nbsp;|&nbsp;
    {{ generated_at }}
  </div>
</div>

<!-- Executive Summary -->
<div class="section">
  <h2>Yönetici Özeti</h2>
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="label">Toplam Gelir</div>
      <div class="value">{{ revenue }}</div>
    </div>
    <div class="kpi-card">
      <div class="label">Net Marj</div>
      <div class="value">{{ net_margin }}</div>
    </div>
    <div class="kpi-card">
      <div class="label">Nakit Pisti</div>
      <div class="value">{{ runway }}</div>
    </div>
    <div class="kpi-card">
      <div class="label">FAVÖK</div>
      <div class="value">{{ ebitda }}</div>
    </div>
    <div class="kpi-card">
      <div class="label">Nakit Akışı</div>
      <div class="value">{{ cash_flow }}</div>
    </div>
    <div class="kpi-card">
      <div class="label">Risk Seviyesi</div>
      <div class="value">{{ risk_level }}</div>
    </div>
  </div>
</div>

{% if alerts %}
<!-- Alerts -->
<div class="section">
  <h2>Kritik Uyarılar</h2>
  <div class="alert-list">
    {% for alert in alerts[:5] %}
    <div class="alert-{{ alert.level or 'warning' }}">⚠ {{ alert.message }}</div>
    {% endfor %}
  </div>
</div>
{% endif %}

{% if pnl %}
<!-- P&L Summary -->
<div class="section">
  <h2>Kar & Zarar Özeti</h2>
  {% if pnl.narrative %}
  <div class="narrative">{{ pnl.narrative }}</div>
  {% endif %}
  <table>
    <tr><th>Metrik</th><th>Değer</th><th>Değerlendirme</th></tr>
    <tr><td>Gelir</td><td>{{ pnl.revenue or "—" }}</td><td>{{ pnl.revenue_verdict or "—" }}</td></tr>
    <tr><td>Brüt Kar</td><td>{{ pnl.gross_profit or "—" }}</td><td>{{ pnl.gross_margin_str or "—" }}</td></tr>
    <tr><td>Giderler</td><td>{{ pnl.opex or "—" }}</td><td>—</td></tr>
    <tr><td>Net Kar</td><td>{{ pnl.net_income or "—" }}</td><td>{{ pnl.net_margin_str or "—" }}</td></tr>
  </table>
</div>
{% endif %}

{% if forecast %}
<!-- Forecast -->
<div class="section">
  <h2>Nakit Akışı Tahmini</h2>
  {% if forecast.narrative %}
  <div class="narrative">{{ forecast.narrative }}</div>
  {% endif %}
</div>
{% endif %}

{% if anomalies %}
<!-- Anomalies -->
<div class="section">
  <h2>Anomali Tespiti</h2>
  <table>
    <tr><th>Tür</th><th>Seviye</th><th>Açıklama</th></tr>
    {% for a in anomalies[:10] %}
    <tr>
      <td>{{ a.anomaly_type or "—" }}</td>
      <td>{{ a.severity or "—" }}</td>
      <td>{{ a.description or "—" }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endif %}

{% if recommendations %}
<!-- Recommendations -->
<div class="section">
  <h2>Öneriler</h2>
  {% for rec in recommendations[:5] %}
  <div class="recommendation">{{ loop.index }}. {{ rec }}</div>
  {% endfor %}
</div>
{% endif %}

<div class="footer">
  Bu rapor {{ brand_name }} tarafından otomatik olarak üretilmiştir. &nbsp;|&nbsp; {{ generated_at }} &nbsp;|&nbsp;
  Gizlilik seviyesi: Ticari Sır
</div>

</body>
</html>
"""

_EXECUTIVE_BRIEF_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: Arial, sans-serif; font-size: 13px; color: #1a1a2e; margin: 30px; }
  h1 { font-size: 22px; color: #2563eb; }
  .kpi-row { display: flex; gap: 20px; margin: 16px 0; }
  .kpi { flex: 1; background: #f4f4f5; padding: 10px; border-radius: 6px; }
  .kpi .val { font-size: 20px; font-weight: bold; }
  .alert { background: #fee2e2; padding: 8px; border-radius: 4px; margin: 4px 0; font-size: 11px; }
  .rec { padding: 6px; border-left: 3px solid #2563eb; margin: 4px 0; font-size: 11px; }
  @page { size: A4; margin: 2cm; }
</style>
</head>
<body>
<h1>Yönetici Özeti — {{ company_name or "Şirket" }}</h1>
<p style="color:#666;">{{ period or "Güncel Dönem" }} &nbsp;|&nbsp; {{ generated_at }}</p>

<div class="kpi-row">
  <div class="kpi"><div class="label">Gelir</div><div class="val">{{ revenue }}</div></div>
  <div class="kpi"><div class="label">Net Marj</div><div class="val">{{ net_margin }}</div></div>
  <div class="kpi"><div class="label">Nakit Pisti</div><div class="val">{{ runway }}</div></div>
</div>

{% for alert in alerts[:3] %}<div class="alert">⚠ {{ alert.message }}</div>{% endfor %}
{% for rec in recommendations[:3] %}<div class="rec">→ {{ rec }}</div>{% endfor %}

<p style="font-size:9px;color:#aaa;margin-top:30px;">{{ brand_name }} &nbsp;|&nbsp; {{ generated_at }}</p>
</body>
</html>
"""


# ── PDF Engine ────────────────────────────────────────────────────────────────

class PDFEngine:
    """
    HTML → PDF engine using WeasyPrint.
    Falls back to simple text rendering if WeasyPrint unavailable.
    """

    async def render(
        self,
        template_name: str,
        context: dict[str, Any],
    ) -> bytes:
        """
        Render a PDF from a named template + context dict.

        Args:
            template_name: "cfo_summary" | "executive_brief"
            context:       Template variables

        Returns:
            PDF bytes
        """
        html = self._render_html(template_name, context)
        return await asyncio.get_event_loop().run_in_executor(
            None, self._html_to_pdf, html
        )

    def _render_html(self, template_name: str, context: dict[str, Any]) -> str:
        """Render HTML from template + context using Jinja2."""
        template_map = {
            "cfo_summary":    _CFO_SUMMARY_TEMPLATE,
            "executive_brief": _EXECUTIVE_BRIEF_TEMPLATE,
        }

        template_str = template_map.get(template_name, _EXECUTIVE_BRIEF_TEMPLATE)

        # Templates never name the product directly — one env change renames
        # every report footer.
        context = {"brand_name": get_brand().name, **context}

        try:
            from jinja2 import Template
            tmpl = Template(template_str)
            return tmpl.render(**context)
        except ImportError:
            # Jinja2 not available — use str.format fallback
            logger.warning("Jinja2 not installed — using basic template")
            return template_str.replace("{{ company_name or \"Şirket\" }}", str(context.get("company_name", "Şirket")))
        except Exception as exc:
            logger.warning("Template render failed: %s", exc)
            return f"<html><body><h1>{context.get('company_name', 'CFO Report')}</h1></body></html>"

    def _html_to_pdf(self, html: str) -> bytes:
        """Convert HTML to PDF bytes using WeasyPrint (sync, run in executor)."""
        try:
            from weasyprint import HTML
            pdf = HTML(string=html).write_pdf()
            return pdf  # type: ignore[return-value]
        except ImportError:
            logger.warning("WeasyPrint not installed — generating minimal PDF")
            return self._minimal_pdf(html)
        except Exception as exc:
            logger.error("WeasyPrint render failed: %s", exc)
            return self._minimal_pdf(html)

    def _minimal_pdf(self, html: str) -> bytes:
        """
        Ultra-minimal PDF as fallback when WeasyPrint unavailable.
        Uses ReportLab if available, otherwise returns a raw PDF stub.
        """
        try:
            import io

            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            buf = io.BytesIO()
            c   = canvas.Canvas(buf, pagesize=A4)
            c.setFont("Helvetica", 12)
            c.drawString(50, 800, "CFO Raporu")
            c.drawString(50, 780, "(WeasyPrint yüklü değil — tam rapor için pip install weasyprint)")
            c.save()
            return buf.getvalue()
        except ImportError:
            pass

        # Raw minimal PDF bytes as last resort
        return (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]"
            b"/Parent 2 0 R>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f\n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref 9\n%%EOF\n"
        )


# ── Context builders from CFO result ─────────────────────────────────────────

def build_cfo_summary_context(
    dashboard_json: dict[str, Any],
    company_name:   str = "",
    period:         str = "",
) -> dict[str, Any]:
    """Build template context from CFO pipeline result dashboard JSON."""
    from datetime import datetime

    pnl      = dashboard_json.get("pnl") or {}
    cashflow = dashboard_json.get("cashflow") or {}
    forecast = dashboard_json.get("forecast") or {}
    alerts   = dashboard_json.get("alerts") or []
    anomalies = dashboard_json.get("anomalies") or []

    def fmt_money(val: Any) -> str:
        if val is None: return "—"
        try:
            v = float(val)
            if abs(v) >= 1_000_000: return f"₺{v/1_000_000:.1f}M"
            if abs(v) >= 1_000:     return f"₺{v/1_000:.0f}K"
            return f"₺{v:.0f}"
        except Exception:
            return str(val)

    def fmt_pct(val: Any) -> str:
        if val is None: return "—"
        try:
            return f"{float(val)*100:.1f}%"
        except Exception:
            return str(val)

    runway_months = None
    scenarios = forecast.get("scenarios") or {}
    base_scenario = scenarios.get("base") or {}
    runway_months = base_scenario.get("runway_months")

    recommendations = forecast.get("recommendations") or pnl.get("recommendations") or []

    return {
        "company_name":   company_name,
        "period":         period,
        "generated_at":   datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC"),
        "revenue":        fmt_money(pnl.get("revenue")),
        "net_margin":     fmt_pct(pnl.get("net_margin")),
        "net_margin_str": fmt_pct(pnl.get("net_margin")),
        "gross_margin_str": fmt_pct(pnl.get("gross_margin")),
        "ebitda":         fmt_money(pnl.get("ebitda")),
        "cash_flow":      fmt_money(cashflow.get("operating_cash_flow")),
        "runway":         f"{runway_months:.1f} ay" if runway_months is not None else "—",
        "risk_level":     "Kritik" if any(a.get("level") == "critical" for a in alerts) else "Normal",
        "alerts":         alerts,
        "anomalies":      anomalies,
        "pnl":            {
            "narrative":  pnl.get("narrative"),
            "revenue":    fmt_money(pnl.get("revenue")),
            "gross_profit": fmt_money(pnl.get("gross_profit")),
            "opex":       fmt_money(pnl.get("opex")),
            "net_income": fmt_money(pnl.get("net_income")),
        },
        "forecast":       {"narrative": forecast.get("narrative")},
        "recommendations": recommendations if isinstance(recommendations, list) else [],
    }
