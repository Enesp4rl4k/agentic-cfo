"""
Unified Executive Report Service

Builds a single comprehensive report combining all available C-Suite agent results
from the CompanyContext. Used by:
  - POST /reports/unified/{org_id}     → JSON summary
  - POST /reports/unified/{org_id}/pdf → PDF download

Data sources (all optional, taken from CompanyContext):
  - CFO: P&L, Cash Flow, Forecast, Anomalies, Alerts
  - CTO: Infrastructure, Tech Debt, Incidents, Velocity
  - CMO: Campaigns, Funnel, Cohort
  - COO: Processes, SLA, Operations Score
  - CHRO: Headcount, Attrition, Compensation
  - Risk: Risk Register, KRIs
  - CEO: Cross-risks, Strategic Priorities, Board Deck

Output: Structured dict + WeasyPrint HTML/PDF
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Formatter helpers ─────────────────────────────────────────────────────────

def _fmt_tl(cents: int | float) -> str:
    val = (cents or 0) / 100
    if abs(val) >= 1_000_000:
        return f"₺{val/1_000_000:.1f}M"
    elif abs(val) >= 1_000:
        return f"₺{val/1_000:.0f}K"
    return f"₺{val:,.0f}"


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"%{v * 100:.1f}"


def _score(v: float | None, scale: float = 10.0) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}/{scale:.0f}"


# ── Section builders ──────────────────────────────────────────────────────────

def _build_cfo_section(cfo: dict[str, Any]) -> dict[str, Any]:
    pnl      = cfo.get("pnl")      or {}
    cfo.get("cashflow") or {}
    forecast = cfo.get("forecast") or {}
    anomalies = cfo.get("anomalies") or []
    alerts    = cfo.get("alerts")   or []

    base = (forecast.get("scenarios") or {}).get("base") or {}

    return {
        "section": "CFO — Finansal Durum",
        "metrics": {
            "revenue":         _fmt_tl(pnl.get("revenue", 0)),
            "gross_profit":    _fmt_tl(pnl.get("gross_profit", 0)),
            "gross_margin":    _pct(pnl.get("gross_margin")),
            "ebitda":          _fmt_tl(pnl.get("ebitda", 0)),
            "ebitda_margin":   _pct(pnl.get("ebitda_margin")),
            "net_income":      _fmt_tl(pnl.get("net_income", 0)),
            "net_margin":      _pct(pnl.get("net_margin")),
            "cash_runway":     f"{base.get('runway_months', '?')} ay" if base.get("runway_months") else "—",
            "forecast_12m":    _fmt_tl(base.get("twelve_month_net", 0)),
        },
        "critical_alerts": [a for a in alerts if a.get("level") == "critical"],
        "anomaly_count":   len(anomalies),
        "anomaly_critical": sum(1 for a in anomalies if a.get("severity") == "critical"),
    }


def _build_cto_section(cto: dict[str, Any]) -> dict[str, Any]:
    summary  = (cto.get("cto_summary") or {})
    infra    = cto.get("infra")      or {}
    debt     = cto.get("tech_debt")  or {}
    velocity = cto.get("velocity")   or {}
    incidents = cto.get("incidents") or {}

    return {
        "section": "CTO — Teknoloji Sağlığı",
        "metrics": {
            "health_score":    _score(summary.get("overall_health_score")),
            "infra_cost":      _fmt_tl(infra.get("total_cost_cents", 0)),
            "infra_waste":     _fmt_tl(infra.get("waste_estimate_cents", 0)),
            "debt_score":      _score(debt.get("debt_score")),
            "velocity_trend":  velocity.get("trend", "—"),
            "incidents_total": incidents.get("total_incidents", 0),
            "mttr_hours":      incidents.get("mttr_hours", "—"),
        },
        "quick_wins": summary.get("quick_wins") or [],
        "top_risks":  summary.get("top_risks")  or [],
    }


def _build_cmo_section(cmo: dict[str, Any]) -> dict[str, Any]:
    summary   = cmo.get("cmo_summary") or {}
    campaigns = cmo.get("campaigns")   or {}
    funnel    = cmo.get("funnel")      or {}
    cohort    = cmo.get("cohort")      or {}

    return {
        "section": "CMO — Pazarlama Etkinliği",
        "metrics": {
            "marketing_score":   _score(summary.get("overall_marketing_score")),
            "growth_score":      _score(summary.get("growth_efficiency_score")),
            "overall_roas":      f"{campaigns.get('overall_roas', 0):.2f}x",
            "blended_cac":       _fmt_tl(campaigns.get("blended_cac_cents", 0)),
            "total_spend":       _fmt_tl(campaigns.get("total_spend_cents", 0)),
            "conversion_rate":   _pct(funnel.get("overall_conversion_rate")),
            "ltv_cac_ratio":     f"{cohort.get('ltv_cac_ratio', 0):.2f}x",
            "retention_30d":     _pct(cohort.get("avg_retention_30d")),
        },
        "top_risks":  summary.get("top_risks")  or [],
        "quick_wins": summary.get("quick_wins") or [],
    }


def _build_coo_section(coo: dict[str, Any]) -> dict[str, Any]:
    summary = coo.get("coo_summary") or {}
    sla     = coo.get("sla")         or {}

    return {
        "section": "COO — Operasyonel Verimlilik",
        "metrics": {
            "ops_score":   _score(summary.get("overall_ops_score")),
            "sla_breach":  _pct(sla.get("breach_rate")),
        },
        "top_risks":  summary.get("top_risks")  or [],
        "quick_wins": summary.get("quick_wins") or [],
    }


def _build_chro_section(chro: dict[str, Any]) -> dict[str, Any]:
    summary    = chro.get("chro_summary") or {}
    headcount  = chro.get("headcount")    or {}
    attrition  = chro.get("attrition")    or {}
    comp       = chro.get("compensation") or {}

    return {
        "section": "CHRO — İnsan Kaynakları",
        "metrics": {
            "hr_score":         _score(summary.get("overall_hr_score")),
            "total_headcount":  headcount.get("total_headcount", "—"),
            "attrition_rate":   _pct(attrition.get("annualized_attrition_rate")),
            "cost_of_attrition": _fmt_tl(attrition.get("cost_of_attrition", 0)),
            "avg_salary":       _fmt_tl(comp.get("avg_salary", 0)),
            "below_market_pct": _pct(comp.get("below_market_pct")),
        },
        "top_risks":  summary.get("top_risks")  or [],
        "quick_wins": summary.get("quick_wins") or [],
    }


def _build_risk_section(risk: dict[str, Any]) -> dict[str, Any]:
    summary = risk.get("risk_summary") or {}

    return {
        "section": "Risk — Kurumsal Risk Yönetimi",
        "metrics": {
            "risk_score":  summary.get("overall_risk_score", "—"),
            "risk_level":  summary.get("overall_risk_level", "—"),
        },
        "top_risks": (summary.get("top_risks") or [])[:5],
    }


def _build_ceo_section(ceo: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": "CEO — Stratejik Sentez",
        "cross_risks":          ceo.get("cross_risks")          or [],
        "strategic_priorities": ceo.get("strategic_priorities") or [],
        "board_deck_summary":   (ceo.get("board_deck") or {}).get("one_page_summary", ""),
        "agents_used":          ceo.get("agents_used") or [],
    }


# ── Main builder ──────────────────────────────────────────────────────────────

def build_unified_report(
    ctx_data: dict[str, Any],
    company_name: str | None = None,
    reporting_period: str | None = None,
) -> dict[str, Any]:
    """
    Build a structured unified executive report from CompanyContext data.

    Args:
        ctx_data: CompanyContext.to_dict() output
        company_name: Optional company name override
        reporting_period: Optional period string

    Returns:
        Structured report dict with per-agent sections + executive summary
    """
    cfo  = ctx_data.get("last_cfo_result")        or {}
    cto  = ctx_data.get("last_cto_result")        or {}
    cmo  = ctx_data.get("last_cmo_result")        or {}
    coo  = ctx_data.get("last_coo_result")        or {}
    chro = ctx_data.get("last_chro_result")       or {}
    risk = ctx_data.get("last_risk_result")       or {}
    ceo  = ctx_data.get("last_ceo_result")        or {}

    sections = []
    agents_available = []

    if cfo:
        sections.append(_build_cfo_section(cfo))
        agents_available.append("CFO")
    if cto:
        sections.append(_build_cto_section(cto))
        agents_available.append("CTO")
    if cmo:
        sections.append(_build_cmo_section(cmo))
        agents_available.append("CMO")
    if coo:
        sections.append(_build_coo_section(coo))
        agents_available.append("COO")
    if chro:
        sections.append(_build_chro_section(chro))
        agents_available.append("CHRO")
    if risk:
        sections.append(_build_risk_section(risk))
        agents_available.append("Risk")
    if ceo:
        sections.append(_build_ceo_section(ceo))
        agents_available.append("CEO Sentezi")

    # Executive summary — top-level KPIs
    exec_summary: dict[str, Any] = {
        "company_name":    company_name or ctx_data.get("company_name") or "Şirket",
        "reporting_period": reporting_period or ctx_data.get("reporting_period") or "",
        "agents_available": agents_available,
        "generated_at":    datetime.now(UTC).isoformat(),
    }

    # CFO headline
    if cfo:
        pnl = cfo.get("pnl") or {}
        exec_summary["headline_revenue"]    = _fmt_tl(pnl.get("revenue", 0))
        exec_summary["headline_net_margin"] = _pct(pnl.get("net_margin"))

    # Cross-risks from CEO
    if ceo:
        exec_summary["cross_risk_count"] = len(ceo.get("cross_risks") or [])
        exec_summary["strategic_priority_count"] = len(ceo.get("strategic_priorities") or [])

    return {
        "executive_summary": exec_summary,
        "sections":          sections,
        "raw": {
            "cfo":  cfo  or None,
            "cto":  cto  or None,
            "cmo":  cmo  or None,
            "coo":  coo  or None,
            "chro": chro or None,
            "risk": risk or None,
            "ceo":  ceo  or None,
        },
    }


# ── PDF generation ────────────────────────────────────────────────────────────

def _build_unified_html(report: dict[str, Any]) -> str:
    """Convert unified report to HTML for WeasyPrint."""
    summary  = report["executive_summary"]
    sections = report["sections"]

    company    = summary["company_name"]
    period     = summary.get("reporting_period", "")
    agents     = ", ".join(summary["agents_available"])
    gen_at     = datetime.now(UTC).strftime("%d %B %Y, %H:%M UTC")
    revenue    = summary.get("headline_revenue", "—")
    net_margin = summary.get("headline_net_margin", "—")
    risk_count = summary.get("cross_risk_count", 0)

    # Build sections HTML
    sections_html = ""
    for sec in sections:
        metrics = sec.get("metrics") or {}
        risks   = (sec.get("top_risks") or sec.get("cross_risks") or [])[:3]
        wins    = (sec.get("quick_wins") or [])[:2]

        metrics_html = "".join(
            f'<tr><td class="k">{k.replace("_", " ").title()}</td>'
            f'<td class="v">{v}</td></tr>'
            for k, v in metrics.items()
        )

        risks_html = "".join(
            f'<li class="risk-item sev-{r.get("severity", "medium")}">'
            f'{r.get("message", r.get("title", str(r)))[:120]}</li>'
            for r in risks
            if isinstance(r, dict)
        )

        wins_html = "".join(
            f'<li>{w.get("action", str(w))[:100]}</li>'
            for w in wins
            if isinstance(w, dict)
        )

        sections_html += f"""
        <div class="section">
          <h2>{sec["section"]}</h2>
          {f'<table class="metrics">{metrics_html}</table>' if metrics_html else ""}
          {f'<div class="sub-head">Riskler</div><ul class="risk-list">{risks_html}</ul>' if risks_html else ""}
          {f'<div class="sub-head">Hızlı Kazanımlar</div><ul class="wins-list">{wins_html}</ul>' if wins_html else ""}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>Yönetim Raporu — {company}</title>
<style>
  @page {{ size: A4; margin: 20mm 15mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Arial', sans-serif; font-size: 11px; color: #1a1a2e; line-height: 1.4; }}
  .header {{ border-bottom: 3px solid #6D28D9; padding-bottom: 10px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 20px; color: #6D28D9; margin: 0 0 4px; }}
  .header-meta {{ display: flex; gap: 24px; font-size: 10px; color: #6b7280; }}
  .kpi-bar {{ display: flex; gap: 16px; background: #f5f3ff; border-radius: 6px; padding: 10px 14px; margin-bottom: 16px; }}
  .kpi-item {{ text-align: center; }}
  .kpi-label {{ font-size: 9px; color: #6b7280; text-transform: uppercase; }}
  .kpi-value {{ font-size: 16px; font-weight: bold; color: #4C1D95; }}
  .section {{ margin-bottom: 16px; page-break-inside: avoid; }}
  .section h2 {{ font-size: 12px; font-weight: bold; color: #4C1D95; border-left: 3px solid #6D28D9; padding-left: 8px; margin: 0 0 8px; }}
  .metrics {{ width: 100%; border-collapse: collapse; font-size: 10px; }}
  .metrics td {{ padding: 3px 6px; }}
  .metrics tr:nth-child(even) {{ background: #f9fafb; }}
  .metrics .k {{ color: #6b7280; width: 45%; }}
  .metrics .v {{ font-weight: 600; }}
  .sub-head {{ font-size: 9px; font-weight: bold; color: #6b7280; text-transform: uppercase; margin: 8px 0 4px; }}
  .risk-list, .wins-list {{ margin: 0; padding-left: 14px; font-size: 10px; }}
  .risk-list li {{ margin-bottom: 2px; }}
  .risk-item.sev-critical {{ color: #DC2626; }}
  .risk-item.sev-high {{ color: #D97706; }}
  .footer {{ border-top: 1px solid #e5e7eb; padding-top: 6px; font-size: 9px; color: #9ca3af; text-align: center; }}
</style>
</head>
<body>
<div class="header">
  <h1>Yönetim Kurulu Raporu — {company}</h1>
  <div class="header-meta">
    <span>📅 {period or gen_at}</span>
    <span>🤖 Agentlar: {agents}</span>
    <span>⏱ Oluşturuldu: {gen_at}</span>
  </div>
</div>

<div class="kpi-bar">
  <div class="kpi-item">
    <div class="kpi-label">Gelir</div>
    <div class="kpi-value">{revenue}</div>
  </div>
  <div class="kpi-item">
    <div class="kpi-label">Net Marj</div>
    <div class="kpi-value">{net_margin}</div>
  </div>
  <div class="kpi-item">
    <div class="kpi-label">Aktif Agent</div>
    <div class="kpi-value">{len(summary["agents_available"])}</div>
  </div>
  <div class="kpi-item">
    <div class="kpi-label">Cross Risk</div>
    <div class="kpi-value">{risk_count}</div>
  </div>
</div>

{sections_html}

<div class="footer">
  Gizlilik: Bu rapor C-Level AI tarafından {gen_at} tarihinde üretilmiştir. Yalnızca yönetim kurulu kullanımı içindir.
</div>
</body>
</html>"""


def generate_unified_pdf(
    ctx_data: dict[str, Any],
    company_name: str | None = None,
    reporting_period: str | None = None,
) -> bytes:
    """
    Generate a multi-section board PDF from CompanyContext data.
    Returns raw PDF bytes.
    """
    report = build_unified_report(ctx_data, company_name, reporting_period)
    html   = _build_unified_html(report)

    try:
        from weasyprint import HTML as WeasyHTML
        pdf_bytes: bytes = WeasyHTML(string=html).write_pdf()
        return pdf_bytes
    except ImportError:
        logger.error("WeasyPrint not installed — cannot generate PDF")
        raise RuntimeError("WeasyPrint is required for PDF generation. Run: pip install weasyprint")
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc)
        raise
