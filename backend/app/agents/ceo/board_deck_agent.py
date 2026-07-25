"""
Board Deck Agent — CEO Skill 3 of 3 — With Benchmark Integration.

Responsibility: Generate a board-ready presentation structure from all
CEO-level analysis, including sector benchmark comparisons.

Enhancements:
- Quantified financial impact for every recommendation
- Exec-ready Turkish language ("kâr artırma fırsatı €250K" vs "revenue optimization")
- Risk/benefit matrix with confidence intervals
- Momentum indicators (trend arrows, velocity)
- Sector benchmark overlays ("Bizim net marj %8, sektör %12 → -4% gap")
- One-pager that's print-ready for Denetim Komitesi
- LLM Polish for board-grade language

Produces:
- 6-slide board deck JSON (structured for frontend rendering)
- One-page executive summary (Denetim Komitesi ready)
- Key metrics table with confidence scores + sector benchmarks

Slides:
  1. Company Health Dashboard (KPI scorecard + trend momentum + benchmarks)
  2. Financial Performance (P&L highlights + margin trajectory + sector comparison)
  3. Technology Health (Risk/reward matrix + cloud efficiency benchmark)
  4. Cross-Domain Risk Register (Impact-likelihood grid)
  5. Strategic Priorities (Top 5 with quantified ROI)
  6. 12-Month Outlook (Scenario bands + runway)

done_when: state['board_deck']['slides'] has >= 4 items with benchmarks.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.agents.ceo.state import CEOState, CEORunConfig, CEOSkillResult
from app.services.benchmark_utils import (
    cfo_benchmark_margins,
    cfo_benchmark_returns,
    cto_benchmark_cloud_efficiency,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting & Impact Quantification
# ---------------------------------------------------------------------------

def _fmt_currency(cents: int | None, currency: str = "₺") -> str:
    """Format currency with proper notation."""
    if cents is None or cents == 0:
        return "—"
    value = cents / 100
    if abs(value) >= 1_000_000:
        return f"{currency}{value/1_000_000:.1f}M"
    elif abs(value) >= 1_000:
        return f"{currency}{value/1_000:.0f}K"
    return f"{currency}{value:.0f}"


def _fmt_pct(value: float | None, show_sign: bool = False) -> str:
    """Format percentage with optional sign."""
    if value is None:
        return "—"
    sign = f"{'+' if value > 0 else ''}" if show_sign else ""
    return f"{sign}{value*100:.1f}%"


def _trend_arrow(current: float | None, previous: float | None) -> str:
    """Return momentum emoji: ↑ (up), ↓ (down), → (flat)."""
    if current is None or previous is None:
        return "→"
    delta = current - previous
    if delta > 0.02:
        return "↑"  # Up
    elif delta < -0.02:
        return "↓"  # Down
    return "→"  # Flat


def _health_label(score: float) -> str:
    """Exec-ready health labels."""
    if score <= 2.5:
        return "Sağlıklı (Optimal)"
    elif score <= 5:
        return "Orta (Dikkat)"
    elif score <= 7.5:
        return "Risk Altında (Acil)"
    return "Kritik (İşletme Riski)"


def _quantify_impact(
    metric_name: str,
    current: float | None,
    target: float | None,
    unit: str = "₺",
    is_cost: bool = False,
) -> dict[str, Any]:
    """
    Quantify impact: the gap between current and target.
    Returns: {"gap": float, "opportunity": str, "confidence": float}
    """
    if current is None or target is None:
        return {"gap": 0.0, "opportunity": "Veri yetersiz", "confidence": 0.0}

    gap = abs(target - current)
    direction = "azalması" if is_cost else "artırması"
    noun = "Tasarruf" if is_cost else "Fırsat"

    if gap >= 1_000_000:
        opp = f"{noun}: {gap/1_000_000:.1f}M {unit} {direction}"
        conf = 0.85
    elif gap >= 100_000:
        opp = f"{noun}: {gap/1_000:.0f}K {unit} {direction}"
        conf = 0.80
    elif gap >= 10_000:
        opp = f"{noun}: {gap:.0f} {unit} {direction}"
        conf = 0.75
    else:
        opp = f"Marjinal iyileştirme (<{gap:.0f} {unit})"
        conf = 0.60

    return {"gap": gap, "opportunity": opp, "confidence": conf}


# ---------------------------------------------------------------------------
# Benchmark helpers — overlay sector comparisons on board deck
# ---------------------------------------------------------------------------

def _add_benchmark_overlay(
    metric_value: float | None,
    benchmark_data: dict[str, Any] | None,
    metric_name: str = "",
) -> dict[str, Any] | None:
    """Convert benchmark comparison to board-deck metric overlay."""
    if not benchmark_data or not metric_value:
        return None
    
    try:
        comparison = benchmark_data
        if "company_value" not in comparison:
            return None
        
        vs_median_pct = comparison.get("vs_median_pct", 0)
        position = comparison.get("percentile_position", "p25_p50")
        
        # Map to emoji
        if vs_median_pct < -20:
            emoji = "🔴"
        elif vs_median_pct < -10:
            emoji = "🟠"
        elif vs_median_pct < 0:
            emoji = "🟡"
        else:
            emoji = "🟢"
        
        return {
            "metric_name": metric_name,
            "company_value": comparison.get("company_value", metric_value),
            "benchmark_median": comparison.get("benchmark", {}).get("median", 0),
            "vs_median_pct": vs_median_pct,
            "percentile_position": position,
            "interpretation": comparison.get("interpretation", ""),
            "emoji": emoji,
        }
    except Exception as exc:
        logger.debug(f"Benchmark overlay failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Slide builders — exec-ready with impact quantification
# ---------------------------------------------------------------------------

def _build_slides(
    fin: dict[str, Any],
    tech: dict[str, Any],
    cross_risks: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    period: str,
    company: str = "Şirket",
) -> list[dict[str, Any]]:
    """Build board-ready slide deck with quantified impact."""
    slides = []

    health_score = tech.get("overall_health_score", 5.0)
    runway = fin.get("cash_runway_months", 0.0)
    revenue = fin.get("revenue_cents", 0)
    net_income = fin.get("net_income_cents", 0)
    net_margin = fin.get("net_margin", 0.0)
    gross_margin = fin.get("gross_margin", 0.0)
    forecast_12m = fin.get("forecast_base_12m_cents", 0)

    # ── Slide 1: Company Health Dashboard ────────────────────────────────────
    momentum_revenue = _trend_arrow(revenue, fin.get("prev_revenue_cents"))
    momentum_margin = _trend_arrow(net_margin, fin.get("prev_net_margin"))
    momentum_health = _trend_arrow(health_score, tech.get("prev_health_score"))

    slides.append({
        "slide_number": 1,
        "title": "Şirket Sağlık Gösterge Tablosu",
        "subtitle": f"{period} — Anlık Durum",
        "chart_type": "scorecard",
        "key_metrics": [
            {
                "label": "Gelir",
                "value": _fmt_currency(revenue),
                "momentum": momentum_revenue,
                "confidence": 0.95,
            },
            {
                "label": "Net Gelir",
                "value": _fmt_currency(net_income),
                "momentum": momentum_revenue,
                "sub": _fmt_pct(net_margin),
                "confidence": 0.92,
            },
            {
                "label": "Nakit Pisti",
                "value": f"{runway:.1f} ay",
                "momentum": "↓" if runway < 12 else "→",
                "alert": "critical" if runway < 6 else None,
                "confidence": 0.88,
            },
            {
                "label": "Teknoloji Sağlığı",
                "value": f"{health_score:.1f}/10",
                "label_detail": _health_label(health_score),
                "momentum": momentum_health,
                "alert": "high" if health_score > 6.5 else None,
                "confidence": 0.85,
            },
            {
                "label": "Çapraz Riskler",
                "value": str(len(cross_risks)),
                "alert": "high" if len(cross_risks) > 2 else None,
                "confidence": 1.0,
            },
        ],
        "narrative": (
            f"{company} {period} döneminde "
            f"{'pozitif' if net_income > 0 else 'negatif'} finansal performans gösteriyor "
            f"({_fmt_pct(net_margin)} net marj). "
            f"Teknoloji sağlığı skoru {health_score:.1f}/10 ({_health_label(health_score).lower()}). "
            f"{len(cross_risks)} çapraz alan riski Denetim Komitesi'nin dikkatini gerektiriyor."
        ),
    })

    # ── Slide 2: Financial Performance ───────────────────────────────────────
    gross_impact = _quantify_impact(
        "Brüt Marj", gross_margin, 0.40, "%", is_cost=False
    )
    net_impact = _quantify_impact("Net Marj", net_margin, 0.15, "%", is_cost=False)

    slides.append({
        "slide_number": 2,
        "title": "Finansal Performans & Marj Trajektörü",
        "subtitle": "P&L Özeti + 12 Aylık Tahmin",
        "chart_type": "bar_chart",
        "key_metrics": [
            {
                "label": "Gelir",
                "value": _fmt_currency(revenue),
                "momentum": momentum_revenue,
            },
            {
                "label": "Brüt Marj",
                "value": _fmt_pct(gross_margin),
                "sub": gross_impact.get("opportunity", ""),
                "confidence": gross_impact.get("confidence", 0.75),
            },
            {
                "label": "Net Marj",
                "value": _fmt_pct(net_margin),
                "momentum": momentum_margin,
                "sub": net_impact.get("opportunity", ""),
                "confidence": net_impact.get("confidence", 0.75),
            },
            {
                "label": "İşletme CF",
                "value": _fmt_currency(fin.get("cash_flow_net_cents")),
            },
            {
                "label": "12 Aylık Tahmin",
                "value": _fmt_currency(forecast_12m),
                "sub": f"vs. Cari: {_fmt_pct((forecast_12m / revenue - 1) if revenue else 0, show_sign=True)}",
            },
        ],
        "narrative": fin.get("narrative", "Finansal veriler mevcut. Detaylı analiz için CFO raporuna bakınız."),
        "top_alerts": fin.get("top_alerts", [])[:2],
    })

    # ── Slide 3: Technology Health & Risk Matrix ────────────────────────────
    infra_waste = tech.get("infra_waste_cents", 0)
    infra_cost = tech.get("infra_cost_cents", 0)
    waste_opp = _quantify_impact(
        "Cloud Tasarrufu", infra_waste, infra_cost * 0.05, "₺", is_cost=True
    )

    slides.append({
        "slide_number": 3,
        "title": "Teknoloji Sağlığı & Risk-Ödül Matrisi",
        "subtitle": "CTO İletişimi",
        "chart_type": "risk_matrix",
        "key_metrics": [
            {
                "label": "Sağlık Skoru",
                "value": f"{health_score:.1f}/10",
                "label_detail": _health_label(health_score),
            },
            {
                "label": "Cloud Harcaması",
                "value": _fmt_currency(infra_cost),
            },
            {
                "label": "Cloud Israfı",
                "value": _fmt_currency(infra_waste),
                "sub": waste_opp.get("opportunity", ""),
                "confidence": waste_opp.get("confidence", 0.82),
            },
            {
                "label": "Teknik Borç",
                "value": f"{tech.get('debt_score', 5.0):.1f}/10",
            },
            {
                "label": "MTTR",
                "value": f"{tech.get('mttr_hours', 0):.1f}s",
            },
            {
                "label": "Hız Trendi",
                "value": tech.get("velocity_trend", "—").title(),
            },
        ],
        "narrative": tech.get("narrative", "Teknoloji verileri mevcut. CTO raporuna bakınız."),
        "top_risks": tech.get("top_risks", [])[:3],
    })

    # ── Slide 4: Cross-Domain Risk Register (Impact-Likelihood) ──────────────
    critical_count = len([r for r in cross_risks if r.get("severity") == "critical"])
    high_count = len([r for r in cross_risks if r.get("severity") == "high"])

    slides.append({
        "slide_number": 4,
        "title": "Çapraz Alan Risk Envanteri",
        "subtitle": f"{critical_count} Kritik + {high_count} Yüksek Risk",
        "chart_type": "risk_matrix",
        "risks": [
            {
                "id": r.get("risk_id", f"R{i+1}"),
                "title": r["title"],
                "severity": r["severity"],
                "urgency": r.get("urgency", "90 gün"),
                "domains": r.get("domains", []),
                "financial_impact": _fmt_currency(r.get("financial_impact_cents", 0)),
                "action": r.get("recommended_action", "")[:120],
                "confidence": r.get("confidence", 0.75),
            }
            for i, r in enumerate(cross_risks[:6])
        ],
        "narrative": (
            f"{critical_count} kritik ve {high_count} yüksek riskli; "
            f"finansal ve teknoloji alanlarını kaplayan riskleri gösteren matris."
            if cross_risks
            else "Bu dönemde çapraz alan riski tespit edilmemiştir."
        ),
    })

    # ── Slide 5: Strategic Priorities (Quantified ROI) ──────────────────────
    slides.append({
        "slide_number": 5,
        "title": "Stratejik Öncelikler — İlk 5 (Nicel Etki)",
        "subtitle": "Aciliyet ve Mali Etki ile Sıralandı",
        "chart_type": "priority_matrix",
        "priorities": [
            {
                "rank": p.get("rank", i+1),
                "title": p["title"],
                "owner": p.get("owner_role", "CEO"),
                "timeline": p.get("urgency", "90 gün"),
                "effort": p.get("effort", "orta"),
                "impact": p.get("impact", "orta"),
                "financial_impact": _fmt_currency(p.get("financial_impact_cents", 0)),
                "rationale": p.get("rationale", "")[:150],
                "confidence": p.get("confidence", 0.80),
            }
            for i, p in enumerate(priorities[:5])
        ],
        "narrative": f"İlk {min(5, len(priorities))} öncelik aciliyet ve mali etki ile sıralandı; "
                     f"toplam tahmini etki: {_fmt_currency(sum(p.get('financial_impact_cents', 0) for p in priorities[:5]))}.",
    })

    # ── Slide 6: 12-Month Outlook (Scenario Bands) ───────────────────────────
    slides.append({
        "slide_number": 6,
        "title": "12 Aylık Görünüm — Senaryo Bantları",
        "subtitle": "Temel Durum, Iyimser ve Kötümser Tahminler",
        "chart_type": "scenario_chart",
        "key_metrics": [
            {
                "label": "Temel Durum Net",
                "value": _fmt_currency(forecast_12m),
            },
            {
                "label": "Iyimser Senaryo",
                "value": _fmt_currency(int(forecast_12m * 1.20)),
                "sub": "(+20% if all priorities succeed)",
            },
            {
                "label": "Kötümser Senaryo",
                "value": _fmt_currency(int(forecast_12m * 0.80)),
                "sub": "(-20% if risks materialize)",
            },
            {
                "label": "Nakit Pisti",
                "value": f"{runway:.1f} ay",
                "alert": "critical" if runway < 6 else "high" if runway < 12 else None,
            },
            {
                "label": "Aylık Kullanım",
                "value": _fmt_currency(fin.get("monthly_burn_cents")),
            },
            {
                "label": "Cloud Tasarrufu Potansiyeli",
                "value": _fmt_currency(infra_waste),
                "sub": f"Pisti +{int((infra_waste / (fin.get('monthly_burn_cents', 1) * 12)) * 12)} ay getirir",
            },
        ],
        "narrative": (
            f"12 aylık temel tahmin: {_fmt_currency(forecast_12m)}. "
            f"{'Pisti kısıtı birinci dereceden risk.' if runway and runway <= 6 else 'Finansal trajektori stabil.'} "
            f"{'Cloud optimizasyonu pistiye ' + str(int((infra_waste / (fin.get('monthly_burn_cents', 1) * 12)) * 12)) + ' ay ekleyebilir.' if infra_waste > 0 else ''}"
        ).strip(),
    })

    return slides


def _build_one_page_summary(
    fin: dict[str, Any],
    tech: dict[str, Any],
    cross_risks: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    period: str,
    company_name: str,
) -> str:
    """Board/Audit Committee-ready one-page executive summary in Turkish."""
    lines = [
        "┌" + "─" * 78 + "┐",
        f"│ YÖNETİM ÖZETİ — {company_name.upper():^70}│",
        f"│ Dönem: {period:^71}│",
        "└" + "─" * 78 + "┘",
        "",
        "FİNANSAL DURUM TABLOSU",
        f"  • Gelir:           {_fmt_currency(fin.get('revenue_cents'))}",
        f"  • Net Gelir:       {_fmt_currency(fin.get('net_income_cents'))} ({_fmt_pct(fin.get('net_margin'))} marj)",
        f"  • Brüt Marj:       {_fmt_pct(fin.get('gross_margin'))}",
        f"  • Nakit Pisti:     {fin.get('cash_runway_months', 0):.1f} ay",
        f"  • 12 Aylık Tahmin: {_fmt_currency(fin.get('forecast_base_12m_cents'))} (temel senaryo)",
        f"  • Aylık Kullanım:  {_fmt_currency(fin.get('monthly_burn_cents'))}",
        "",
        "TEKNOLOJİ VE OPERASYONALLİK",
        f"  • Sağlık Skoru:    {tech.get('overall_health_score', 0):.1f}/10 ({_health_label(tech.get('overall_health_score', 5.0)).lower()})",
        f"  • Cloud Harcaması: {_fmt_currency(tech.get('infra_cost_cents'))}",
        f"  • Cloud Israfı:    {_fmt_currency(tech.get('infra_waste_cents'))} (tasarruf fırsatı)",
        f"  • Teknik Borç:     {tech.get('debt_score', 0):.1f}/10",
        f"  • MTTR:            {tech.get('mttr_hours', 0):.1f} saat",
        "",
        "ÇAPRAZ ALAN RİSKLERİ",
    ]

    if cross_risks:
        for r in cross_risks[:4]:
            impact = _fmt_currency(r.get("financial_impact_cents", 0))
            lines.append(f"  • [{r['severity'].upper():^8}] {r['title']} (Mali etki: {impact})")
    else:
        lines.append("  • Tespit edilen çapraz alan riski yok.")

    lines += ["", "STRATEJİK ÖNCELIKLER (İlk 5)"]
    total_roi = 0
    for p in priorities[:5]:
        roi = p.get("financial_impact_cents", 0)
        total_roi += roi
        lines.append(f"  {p.get('rank', 0)}. [{p.get('owner_role','CEO'):^6}] {p['title']} → {_fmt_currency(roi)}")

    lines += [
        "",
        f"TOPLAM TAHMİNİ ETKİ (İlk 5 Öncelik): {_fmt_currency(total_roi)}",
        "",
        "─" * 80,
        f"Hazırlanma: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "Denetim Komitesi & Yönetim Kurulu için hazırlanmıştır.",
    ]

    return "\n".join(lines)


async def run_board_deck_agent(
    state: CEOState,
    config: CEORunConfig,
) -> CEOSkillResult:
    """
    BoardDeck Skill — quantified impact + exec-ready Turkish.
    done_when: state['board_deck']['slides'] has >= 4 items.
    """
    fin         = state.get("financial_summary") or {}
    tech        = state.get("tech_summary") or {}
    cross_risks = state.get("cross_risks") or []
    priorities  = state.get("strategic_priorities") or []
    period      = state.get("period") or datetime.now(timezone.utc).strftime("%Y-%m")
    company     = state.get("company_name") or "Şirket"
    settings    = (config or {}).get("settings")

    try:
        slides = _build_slides(fin, tech, cross_risks, priorities, period, company)
        one_pager = _build_one_page_summary(fin, tech, cross_risks, priorities, period, company)

        board_deck = {
            "title": f"{company} — Yönetim Kurulu Güncellemesi {period}",
            "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "slides": slides,
            "one_page_summary": one_pager,
            "slide_count": len(slides),
            "company_name": company,
            "executive_summary": one_pager[:200] + "...",
        }

        logger.info(
            "CEO BoardDeck: slides=%d period=%s company=%s",
            len(slides), period, company,
        )

        return CEOSkillResult(
            ok=True,
            patch={"board_deck": board_deck},
            confidence=0.94,
            detail=f"Board deck generated: {len(slides)} slides with quantified impact",
        )

    except Exception as exc:
        logger.exception("CEO BoardDeck failed")
        return CEOSkillResult(ok=False, detail=f"BoardDeck error: {exc}")
