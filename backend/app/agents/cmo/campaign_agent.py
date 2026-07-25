"""
CMO Campaign Agent — CMO Skill 1 of 3.

Responsibility: Parse campaign performance CSV and compute ROI, ROAS, CAC.

Supported CSV formats (flexible column detection):
  - Google Ads export: Campaign, Channel, Impressions, Clicks, Cost, Conversions, Revenue
  - Meta Ads export: campaign_name, objective, amount_spent, results, revenue
  - Generic: name/campaign, channel/source, spend/cost, conversions/leads, revenue/value

All monetary inputs assumed to be in currency units (dollars) — converted to cents internally.

done_when: state['campaigns']['overall_roas'] is a float
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from app.agents.cmo.state import CMOState, CMOSkillResult

logger = logging.getLogger(__name__)


# ── CSV Parser ────────────────────────────────────────────────────────────────

def _parse_campaign_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse campaign CSV — flexible column detection."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[dict[str, Any]] = []

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            for k in (reader.fieldnames or []):
                if k.strip().lower().replace(" ", "_") == c.lower().replace(" ", "_"):
                    return k
        return None

    name_col        = _col("campaign", "campaign_name", "name", "ad_name")
    channel_col     = _col("channel", "source", "network", "platform", "objective")
    spend_col       = _col("spend", "cost", "amount_spent", "budget_spent", "total_cost")
    revenue_col     = _col("revenue", "value", "conversion_value", "total_value", "sales")
    conversions_col = _col("conversions", "leads", "results", "purchases", "acquisitions")
    clicks_col      = _col("clicks", "link_clicks", "total_clicks")
    impressions_col = _col("impressions", "reach", "total_impressions")

    for i, row in enumerate(reader):
        spend = 0.0
        revenue = 0.0
        conversions = 0
        clicks = 0
        impressions = 0

        try:
            spend = float((row.get(spend_col) or "0").replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass
        try:
            revenue = float((row.get(revenue_col) or "0").replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass
        try:
            conversions = int(float((row.get(conversions_col) or "0").replace(",", "")))
        except (ValueError, TypeError):
            pass
        try:
            clicks = int(float((row.get(clicks_col) or "0").replace(",", "")))
        except (ValueError, TypeError):
            pass
        try:
            impressions = int(float((row.get(impressions_col) or "0").replace(",", "")))
        except (ValueError, TypeError):
            pass

        name    = (row.get(name_col) or f"Campaign {i+1}").strip()
        channel = (row.get(channel_col) or "unknown").strip().lower()

        rows.append({
            "name":         name,
            "channel":      channel,
            "spend_cents":  int(spend * 100),
            "revenue_cents": int(revenue * 100),
            "conversions":  conversions,
            "clicks":       clicks,
            "impressions":  impressions,
        })

    return rows


# ── Pure Calculations ─────────────────────────────────────────────────────────

def _compute_campaign_metrics(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM, no I/O."""
    if not campaigns:
        return {
            "total_spend_cents": 0,
            "total_revenue_cents": 0,
            "overall_roas": 0.0,
            "overall_cac_cents": 0,
            "by_channel": {},
            "top_campaigns": [],
            "underperforming": [],
            "alerts": [],
            "narrative": "",
        }

    total_spend   = sum(c["spend_cents"] for c in campaigns)
    total_revenue = sum(c["revenue_cents"] for c in campaigns)
    total_conv    = sum(c["conversions"] for c in campaigns)

    overall_roas = total_revenue / total_spend if total_spend > 0 else 0.0
    overall_cac  = total_spend // total_conv if total_conv > 0 else 0

    # ── By channel aggregation ─────────────────────────────────────────────────
    channel_map: dict[str, dict[str, Any]] = {}
    for c in campaigns:
        ch = c["channel"]
        if ch not in channel_map:
            channel_map[ch] = {
                "spend_cents": 0, "revenue_cents": 0,
                "conversions": 0, "clicks": 0, "impressions": 0,
            }
        channel_map[ch]["spend_cents"]   += c["spend_cents"]
        channel_map[ch]["revenue_cents"] += c["revenue_cents"]
        channel_map[ch]["conversions"]   += c["conversions"]
        channel_map[ch]["clicks"]        += c["clicks"]
        channel_map[ch]["impressions"]   += c["impressions"]

    by_channel: dict[str, Any] = {}
    for ch, agg in channel_map.items():
        ch_spend = agg["spend_cents"]
        ch_rev   = agg["revenue_cents"]
        ch_conv  = agg["conversions"]
        by_channel[ch] = {
            "spend_cents":    ch_spend,
            "revenue_cents":  ch_rev,
            "conversions":    ch_conv,
            "clicks":         agg["clicks"],
            "impressions":    agg["impressions"],
            "roas":           round(ch_rev / ch_spend, 2) if ch_spend > 0 else 0.0,
            "cac_cents":      ch_spend // ch_conv if ch_conv > 0 else 0,
            "ctr":            round(agg["clicks"] / agg["impressions"], 4)
                              if agg["impressions"] > 0 else 0.0,
        }

    # ── Campaign status ────────────────────────────────────────────────────────
    def _campaign_status(c: dict[str, Any]) -> str:
        roas = c["revenue_cents"] / c["spend_cents"] if c["spend_cents"] > 0 else 0.0
        if roas >= 3.0:
            return "strong"
        if roas >= 1.5:
            return "good"
        if roas >= 1.0:
            return "break_even"
        return "underperforming"

    enriched = []
    for c in campaigns:
        roas = c["revenue_cents"] / c["spend_cents"] if c["spend_cents"] > 0 else 0.0
        cac  = c["spend_cents"] // c["conversions"] if c["conversions"] > 0 else 0
        enriched.append({
            "name":           c["name"],
            "channel":        c["channel"],
            "spend_cents":    c["spend_cents"],
            "revenue_cents":  c["revenue_cents"],
            "conversions":    c["conversions"],
            "roas":           round(roas, 2),
            "cac_cents":      cac,
            "status":         _campaign_status(c),
        })

    top = sorted(enriched, key=lambda x: x["roas"], reverse=True)[:5]
    underperforming = [
        {**c, "reason": "ROAS below 1.0 — spending more than earning"}
        for c in enriched if c["status"] == "underperforming"
    ]

    return {
        "total_spend_cents":   total_spend,
        "total_revenue_cents": total_revenue,
        "total_conversions":   total_conv,
        "overall_roas":        round(overall_roas, 2),
        "overall_cac_cents":   overall_cac,
        "by_channel":          by_channel,
        "top_campaigns":       top,
        "underperforming":     underperforming,
        "alerts":              [],  # filled by _build_campaign_alerts
        "narrative":           "",
    }


def _build_campaign_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts from campaign metrics."""
    alerts: list[dict[str, str]] = []

    roas = metrics.get("overall_roas", 0.0)
    cac  = metrics.get("overall_cac_cents", 0)
    under = metrics.get("underperforming", [])
    spend = metrics.get("total_spend_cents", 0)

    if roas < 1.0 and spend > 0:
        alerts.append({
            "level": "critical",
            "message": f"Overall ROAS is {roas:.2f} — losing money on every ad dollar spent.",
        })
    elif roas < 2.0 and spend > 0:
        alerts.append({
            "level": "high",
            "message": f"ROAS {roas:.2f} is below 2.0x benchmark. Review campaign targeting.",
        })

    if len(under) > 0:
        spend_wasted = sum(c["spend_cents"] for c in under)
        alerts.append({
            "level": "high",
            "message": (
                f"{len(under)} underperforming campaign(s) wasting "
                f"${spend_wasted / 100:,.0f}. Pause or reallocate budget."
            ),
        })

    # Channel concentration risk
    by_channel = metrics.get("by_channel", {})
    if by_channel and spend > 0:
        top_ch = max(by_channel.items(), key=lambda x: x[1]["spend_cents"])
        top_ch_pct = top_ch[1]["spend_cents"] / spend
        if top_ch_pct > 0.70:
            alerts.append({
                "level": "medium",
                "message": (
                    f"{int(top_ch_pct * 100)}% of spend on '{top_ch[0]}'. "
                    "High channel concentration risk — diversify."
                ),
            })

    if cac > 50000 and roas < 2.0:  # CAC > $500 with low ROAS
        alerts.append({
            "level": "medium",
            "message": (
                f"High CAC (${cac / 100:,.0f}) combined with low ROAS. "
                "Customer lifetime value must exceed CAC to be sustainable."
            ),
        })

    return alerts


# ── LLM Narrative (Türkçe + attribution + benchmark) ──────────────────────────

async def _generate_campaign_narrative(
    metrics: dict[str, Any],
    settings,
    attribution: dict[str, Any] | None = None,
    benchmark: dict[str, Any] | None = None,
) -> str:
    """Türkçe CMO narrative — attribution ve sektör benchmark bağlamıyla."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.3,
            max_tokens=700,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        )

        roas  = metrics["overall_roas"]
        spend = metrics["total_spend_cents"] / 100
        rev   = metrics["total_revenue_cents"] / 100
        cac   = metrics["overall_cac_cents"] / 100
        n_bad = len(metrics.get("underperforming", []))

        # Attribution context
        attr_context = ""
        if attribution and attribution.get("insight"):
            top_ch = max(
                attribution.get("markov", {}).get("attribution") or attribution.get("time_decay", {}),
                key=lambda k: (attribution.get("markov", {}).get("attribution") or {}).get(k, 0),
                default=""
            )
            attr_context = f"\nAttribution analizi: {attribution['insight']}"

        # Benchmark context
        bm_context = ""
        if benchmark:
            roas_bm = benchmark.get("metrics", {}).get("roas", {})
            if roas_bm.get("vs_median_pct"):
                bm_context = (
                    f"\nSektör karşılaştırması: ROAS sektör medyanının "
                    f"%{abs(roas_bm['vs_median_pct']):.0f} "
                    f"{'üstünde' if roas_bm['vs_median_pct'] > 0 else 'altında'} "
                    f"({roas_bm.get('percentile_position', '')})"
                )

        context = (
            f"ROAS: {roas:.2f}x | Harcama: {spend:,.0f} ₺ | Gelir: {rev:,.0f} ₺ | "
            f"CAC: {cac:,.0f} ₺ | Düşük performanslı kampanya: {n_bad}"
            + attr_context
            + bm_context
        )

        response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir CMO'sun. Kampanya performans verilerini analiz et ve "
                "Türkçe olarak kısa, eyleme dönüştürülebilir bir özet yaz. "
                "Yanıt şu yapıda olsun:\n"
                "1. Genel pazarlama verimliliğinin 1-2 cümlelik değerlendirmesi\n"
                "2. Attribution modelinden öne çıkan içgörü (varsa)\n"
                "3. Pazarlama ekibinin hemen yapması gereken 2-3 somut eylem\n"
                "Rakamları Türkçe birimlerle (₺, %) kullan."
            )),
            HumanMessage(content=context),
        ])
        return response.content.strip()

    except Exception:
        roas  = metrics.get("overall_roas", 0)
        spend = metrics.get("total_spend_cents", 0) / 100
        rev   = metrics.get("total_revenue_cents", 0) / 100
        return (
            f"Toplam {spend:,.0f} ₺ reklam harcaması {rev:,.0f} ₺ gelir üretiyor "
            f"(ROAS {roas:.2f}x). "
            f"{len(metrics.get('underperforming', []))} kampanya düşük performanslı."
        )


# ── LangGraph Node ─────────────────────────────────────────────────────────────

async def run_campaign_agent(state: CMOState, config: dict) -> dict[str, Any]:
    """
    CMO Campaign Skill — with multi-touch attribution and sector benchmark.
    done_when: state['campaigns']['overall_roas'] is a float.
    """
    csv_text = state.get("campaign_csv") or ""

    if not csv_text.strip():
        logger.info("CMO CampaignAgent: no campaign_csv provided — skipping")
        return {"campaigns": None}

    try:
        rows    = _parse_campaign_csv(csv_text)
        metrics = _compute_campaign_metrics(rows)
        alerts  = _build_campaign_alerts(metrics)
        metrics["alerts"] = alerts

        # ── Multi-touch attribution ────────────────────────────────────────────
        attribution: dict[str, Any] | None = None
        try:
            from app.agents.cmo.attribution import AttributionEngine
            # Use campaign data (no journey data available from CSV — Shapley fallback)
            engine = AttributionEngine(campaigns=rows, journeys=[])
            attribution = engine.compute_all_models()
            metrics["attribution"] = attribution
        except Exception as attr_exc:
            logger.warning("CMO attribution failed: %s", attr_exc)

        # ── Sector benchmark ──────────────────────────────────────────────────
        benchmark: dict[str, Any] | None = None
        try:
            from app.services.benchmark import get_benchmark_engine

            bm_engine = get_benchmark_engine()
            roas_val = metrics["overall_roas"]
            # Build a minimal "pnl-like" dict for CMO metrics
            # ROAS benchmark: map to gross_margin proxy
            benchmark = {
                "roas_vs_benchmark": bm_engine.compare_to_benchmark(
                    "gross_margin",  # Closest proxy — extend benchmark with CMO metrics later
                    roas_val / 10,   # Normalize ROAS to 0-1 range for comparison
                    sector="default",
                )
            }
            metrics["benchmark"] = benchmark
        except Exception as bm_exc:
            logger.debug("CMO benchmark skipped: %s", bm_exc)

        # ── Narrative ─────────────────────────────────────────────────────────
        try:
            from app.config import get_settings
            settings = get_settings()
            metrics["narrative"] = await _generate_campaign_narrative(
                metrics, settings, attribution=attribution, benchmark=benchmark
            )
        except Exception:
            metrics["narrative"] = ""

        logger.info(
            "CMO CampaignAgent: job=%s campaigns=%d roas=%.2f attribution=%s",
            state.get("job_id"), len(rows), metrics["overall_roas"],
            attribution.get("recommended", "none") if attribution else "skipped",
        )
        return {"campaigns": metrics}

    except Exception as exc:
        logger.exception("CMO CampaignAgent failed for job=%s", state.get("job_id"))
        return {"campaigns": None, "error": f"CampaignAgent error: {exc}"}
