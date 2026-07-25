"""
Executive Report PDF — Board-ready single-page financial summary.

Generates a professional A4 PDF suitable for management board presentations.
Content: P&L summary + Cash Flow + 12-month forecast + anomaly count.

Uses WeasyPrint (already in requirements.txt) with embedded CSS.
No external font or image dependencies.

Usage:
    from app.services.executive_report_pdf import generate_executive_report
    pdf_bytes = generate_executive_report(dashboard_data, company_name="Acme A.Ş.")
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _fmt(cents: int | float) -> str:
    """Format cents to Turkish TL string."""
    val = cents / 100
    if abs(val) >= 1_000_000:
        return f"₺{val/1_000_000:.1f}M"
    elif abs(val) >= 1_000:
        return f"₺{val/1_000:.0f}K"
    return f"₺{val:,.0f}"


def _pct(v: float) -> str:
    return f"%{v*100:.1f}"


def _sign_class(value: int | float) -> str:
    return "positive" if value >= 0 else "negative"


def _build_html(
    dashboard: dict[str, Any],
    company_name: str,
    period: str,
    generated_at: str,
) -> str:
    pnl      = dashboard.get("pnl") or {}
    cashflow = dashboard.get("cashflow") or {}
    forecast = dashboard.get("forecast") or {}
    anomalies = dashboard.get("anomalies") or []

    base_scenario = (forecast.get("scenarios") or {}).get("base") or {}
    runway = base_scenario.get("runway_months")
    forecast_12m = base_scenario.get("twelve_month_net", 0)

    cf_alerts = cashflow.get("alerts") or []
    fc_alerts = forecast.get("alerts") or []
    critical_count = sum(1 for a in cf_alerts + fc_alerts if a.get("level") == "critical")
    warning_count  = sum(1 for a in cf_alerts + fc_alerts if a.get("level") == "warning")

    # Anomaly severity breakdown
    anom_critical = sum(1 for a in anomalies if a.get("severity") == "critical")
    anom_high     = sum(1 for a in anomalies if a.get("severity") == "high")

    # Monthly series for sparkline-like table
    monthly = cashflow.get("monthly_series") or []
    monthly_rows = ""
    for entry in sorted(monthly, key=lambda x: x.get("month", ""))[-6:]:
        net = entry.get("net", 0)
        monthly_rows += f"""
        <tr>
          <td class="month-cell">{entry.get('month', '')}</td>
          <td class="amount-cell income">{_fmt(entry.get('in', 0))}</td>
          <td class="amount-cell expense">{_fmt(entry.get('out', 0))}</td>
          <td class="amount-cell {_sign_class(net)}">{_fmt(net)}</td>
        </tr>"""

    # OpEx top 3
    opex = pnl.get("opex") or {}
    top_opex = sorted(
        [(k, v) for k, v in opex.items() if v and v > 0],
        key=lambda x: -x[1]
    )[:3]
    opex_rows = "".join(
        f'<tr><td class="opex-name">{k.replace("_"," ").title()}</td>'
        f'<td class="opex-amt">{_fmt(v)}</td></tr>'
        for k, v in top_opex
    )

    # Forecast scenarios
    scenarios = forecast.get("scenarios") or {}
    scenario_rows = ""
    for key in ["pessimistic", "base", "optimistic"]:
        sc = scenarios.get(key) or {}
        net12 = sc.get("twelve_month_net", 0)
        rw    = sc.get("runway_months")
        label = sc.get("label", key)
        row_class = "base-row" if key == "base" else ""
        scenario_rows += f"""
        <tr class="{row_class}">
          <td>{label}</td>
          <td class="{_sign_class(net12)}">{_fmt(net12)}</td>
          <td>{f"{rw} ay" if rw else "Stabil"}</td>
        </tr>"""

    # Narrative
    narrative = pnl.get("narrative") or ""
    forecast_narrative = forecast.get("narrative") or ""

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<style>
@page {{
  size: A4;
  margin: 1.2cm 1.5cm;
  @bottom-center {{
    content: "{company_name} · {period} · {generated_at}";
    font-size: 7pt;
    color: #94a3b8;
  }}
  @bottom-right {{
    content: counter(page) " / " counter(pages);
    font-size: 7pt;
    color: #94a3b8;
  }}
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 9pt;
  color: #1e293b;
  background: #fff;
  line-height: 1.4;
}}

/* ── Header bar ── */
.header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 3px solid #2563eb;
  padding-bottom: 0.3cm;
  margin-bottom: 0.4cm;
}}
.header-left h1 {{
  font-size: 16pt;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}}
.header-left .subtitle {{
  font-size: 9pt;
  color: #64748b;
  margin-top: 0.05cm;
}}
.header-right {{
  text-align: right;
  font-size: 8pt;
  color: #64748b;
}}
.header-right .period {{
  font-size: 11pt;
  font-weight: 700;
  color: #2563eb;
}}

/* ── KPI strip ── */
.kpi-strip {{
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0.25cm;
  margin-bottom: 0.4cm;
}}
.kpi-card {{
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 5px;
  padding: 0.25cm 0.3cm;
}}
.kpi-label {{
  font-size: 7pt;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #64748b;
  margin-bottom: 0.05cm;
}}
.kpi-value {{
  font-size: 12pt;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.01em;
}}
.kpi-sub {{
  font-size: 7pt;
  color: #64748b;
  margin-top: 0.02cm;
}}
.positive {{ color: #16a34a !important; }}
.negative {{ color: #dc2626 !important; }}
.warning-color {{ color: #d97706 !important; }}

/* ── Section layout ── */
.section-grid {{
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 0.3cm;
  margin-bottom: 0.35cm;
}}
.section-grid-3 {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.3cm;
  margin-bottom: 0.35cm;
}}
.section {{
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 5px;
}}
.section-header {{
  background: #1e3a5f;
  color: #fff;
  padding: 0.15cm 0.3cm;
  font-size: 8pt;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-radius: 4px 4px 0 0;
}}
.section-body {{
  padding: 0.25cm 0.3cm;
}}

/* ── Tables ── */
table {{ width: 100%; border-collapse: collapse; }}
th {{
  font-size: 7pt;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  padding: 0.1cm 0.15cm;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}}
td {{
  font-size: 8.5pt;
  padding: 0.12cm 0.15cm;
  border-bottom: 1px solid #f1f5f9;
}}
tr:last-child td {{ border-bottom: none; }}
tr.base-row td {{ font-weight: 700; background: #eff6ff; }}
.amount-cell {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
.month-cell {{ color: #64748b; font-size: 8pt; }}
.income  {{ color: #16a34a; }}
.expense {{ color: #dc2626; }}
.opex-name {{ color: #334155; }}
.opex-amt  {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}

/* ── Narrative ── */
.narrative-box {{
  background: #f0f9ff;
  border-left: 3px solid #2563eb;
  border-radius: 0 4px 4px 0;
  padding: 0.2cm 0.3cm;
  font-size: 8pt;
  color: #334155;
  line-height: 1.5;
  margin-bottom: 0.3cm;
  font-style: italic;
}}

/* ── Alert strip ── */
.alert-strip {{
  display: flex;
  gap: 0.2cm;
  margin-bottom: 0.3cm;
}}
.alert-badge {{
  display: flex;
  align-items: center;
  gap: 0.1cm;
  padding: 0.1cm 0.2cm;
  border-radius: 4px;
  font-size: 8pt;
  font-weight: 700;
}}
.alert-critical {{ background: #fee2e2; color: #dc2626; }}
.alert-warning  {{ background: #fff7ed; color: #d97706; }}
.alert-anomaly  {{ background: #faf5ff; color: #7c3aed; }}
.alert-ok       {{ background: #f0fdf4; color: #16a34a; }}

/* ── Footer note ── */
.footer-note {{
  border-top: 1px solid #e2e8f0;
  padding-top: 0.2cm;
  font-size: 7pt;
  color: #94a3b8;
  text-align: center;
}}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <h1>{company_name}</h1>
    <div class="subtitle">Yönetim Kurulu Finansal Özeti — AI CFO Analizi</div>
  </div>
  <div class="header-right">
    <div class="period">{period}</div>
    <div>Oluşturulma: {generated_at}</div>
  </div>
</div>

<!-- Alert strip -->
<div class="alert-strip">
  {'<div class="alert-badge alert-critical">⚠ ' + str(critical_count) + ' Kritik Uyarı</div>' if critical_count > 0 else '<div class="alert-badge alert-ok">✓ Kritik Uyarı Yok</div>'}
  {'<div class="alert-badge alert-warning">▲ ' + str(warning_count) + ' Uyarı</div>' if warning_count > 0 else ''}
  {'<div class="alert-badge alert-anomaly">◆ ' + str(anom_critical + anom_high) + ' Yüksek Anomali</div>' if (anom_critical + anom_high) > 0 else ''}
  {'<div class="alert-badge alert-warning">⏳ Nakit Ömrü: ' + str(runway) + ' Ay</div>' if runway and runway < 12 else ''}
</div>

<!-- KPI Strip -->
<div class="kpi-strip">
  <div class="kpi-card">
    <div class="kpi-label">Ciro</div>
    <div class="kpi-value">{_fmt(pnl.get('revenue', 0))}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Brüt Kâr</div>
    <div class="kpi-value">{_fmt(pnl.get('gross_profit', 0))}</div>
    <div class="kpi-sub">{_pct(pnl.get('gross_margin', 0))} marj</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">FAVÖK</div>
    <div class="kpi-value {_sign_class(pnl.get('ebitda', 0))}">{_fmt(pnl.get('ebitda', 0))}</div>
    <div class="kpi-sub">{_pct(pnl.get('ebitda_margin', 0))} marj</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Net Kâr</div>
    <div class="kpi-value {_sign_class(pnl.get('net_income', 0))}">{_fmt(pnl.get('net_income', 0))}</div>
    <div class="kpi-sub">{_pct(pnl.get('net_margin', 0))} marj</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Net Nakit</div>
    <div class="kpi-value {_sign_class(cashflow.get('net_change', 0))}">{_fmt(cashflow.get('net_change', 0))}</div>
    <div class="kpi-sub">Nakit ömrü: {str(runway) + " ay" if runway else "Stabil"}</div>
  </div>
</div>

<!-- CFO Narrative -->
{f'<div class="narrative-box">{narrative[:400]}</div>' if narrative else ""}

<!-- Main grid: Cash Flow + OpEx -->
<div class="section-grid">
  <!-- Monthly Cash Flow -->
  <div class="section">
    <div class="section-header">Aylık Nakit Akışı (Son 6 Ay)</div>
    <div class="section-body">
      <table>
        <thead><tr><th>Ay</th><th style="text-align:right">Giriş</th><th style="text-align:right">Çıkış</th><th style="text-align:right">Net</th></tr></thead>
        <tbody>{monthly_rows or "<tr><td colspan='4' style='color:#94a3b8;text-align:center'>Aylık veri yok</td></tr>"}</tbody>
      </table>
    </div>
  </div>

  <!-- OpEx Breakdown -->
  <div class="section">
    <div class="section-header">Faaliyet Giderleri (Top 3)</div>
    <div class="section-body">
      <table>
        <thead><tr><th>Kategori</th><th style="text-align:right">Tutar</th></tr></thead>
        <tbody>
          {opex_rows or "<tr><td colspan='2' style='color:#94a3b8'>Gider verisi yok</td></tr>"}
          <tr style="font-weight:700;border-top:2px solid #e2e8f0">
            <td>Toplam Faaliyet Gideri</td>
            <td class="opex-amt">{_fmt(pnl.get('total_opex', 0))}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- Forecast scenarios -->
<div class="section" style="margin-bottom:0.35cm">
  <div class="section-header">12 Aylık Tahmin — 3 Senaryo</div>
  <div class="section-body">
    <table>
      <thead><tr><th>Senaryo</th><th style="text-align:right">12 Aylık Net</th><th>Nakit Ömrü</th></tr></thead>
      <tbody>{scenario_rows or "<tr><td colspan='3' style='color:#94a3b8'>Tahmin verisi yok</td></tr>"}</tbody>
    </table>
    {f'<div style="margin-top:0.2cm;font-size:7.5pt;color:#475569;font-style:italic">{forecast_narrative[:300]}</div>' if forecast_narrative else ""}
  </div>
</div>

<!-- Footer -->
<div class="footer-note">
  Bu rapor AI CFO sistemi tarafından otomatik üretilmiştir. Yatırım tavsiyesi değildir.
  Lütfen kararlarınız için yetkili mali müşavirinize danışın.
</div>

</body>
</html>"""


def generate_executive_report(
    dashboard: dict[str, Any],
    company_name: str = "Şirket",
    period: str | None = None,
) -> bytes:
    """
    Generate a board-ready executive report PDF.

    Args:
        dashboard:    Dashboard JSON data (from report_agent output)
        company_name: Company name for header
        period:       Period label e.g. "2024-Q1" (auto-detected if None)

    Returns:
        PDF bytes
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError as exc:
        raise RuntimeError(f"weasyprint not installed: {exc}") from exc

    if not period:
        # Try to detect period from transactions
        cf = dashboard.get("cashflow") or {}
        series = cf.get("monthly_series") or []
        if series:
            months = sorted(m["month"] for m in series)
            period = f"{months[0]} – {months[-1]}"
        else:
            period = datetime.now(timezone.utc).strftime("%Y-%m")

    generated_at = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    html_content = _build_html(
        dashboard=dashboard,
        company_name=company_name,
        period=period,
        generated_at=generated_at,
    )

    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
        logger.info("Executive report PDF generated: %d bytes", len(pdf_bytes))
        return pdf_bytes
    except Exception as exc:
        logger.exception("WeasyPrint failed to generate executive report")
        raise RuntimeError(f"PDF generation failed: {exc}") from exc
