"""
OKR Tracking Agent — derives OKR status from CFO + CTO pipeline outputs.

Enhancements:
- Weighted scoring: strategic importance weights per objective
- Momentum analysis: acceleration/deceleration trend indicators
- Confidence intervals on progress estimates
- Risk-adjusted scoring for cross-functional dependencies
- Turkish narrative with professional language

Design:
  - No external data input required — infers OKRs automatically from
    financial_summary and tech_summary already in CEOState.
  - Callers can also pass explicit okr_definitions for more precise tracking.
  - Pure-computation functions (_infer_okrs, _score_kr, _momentum_score) are LLM-free.
  - run_okr_agent() optionally enriches with LLM narrative summary.

OKR schema produced:
  {
    "objectives": [
      {
        "id": "fin_growth",
        "title": "Drive Revenue Growth",
        "owner": "CFO",
        "weight": 0.25,                    # Strategic importance (sum=1.0)
        "key_results": [
          {
            "kr": "Achieve 15% net margin",
            "target": 0.15,
            "actual": 0.08,
            "unit": "ratio",
            "status": "at_risk",
            "progress_pct": 53,
            "momentum": 0.02,              # Change from prior period
            "confidence": 0.85,
          }
        ],
        "overall_status": "at_risk",
        "score": 0.53,
        "weighted_score": 0.132,           # score * weight
        "momentum": "accelerating",        # up | flat | decelerating
      }
    ],
    "period": "2024-Q2",
    "company_weighted_okr_score": 0.68,   # Aggregate across all objectives
    "generated_at": "2024-07-18T...",
    "narrative": "...",
  }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Scoring Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _score_kr(actual: float | None, target: float, higher_is_better: bool = True) -> float:
    """
    Return progress as 0.0–1.0.
    - If actual is None → 0.0 (no data)
    - Special case: target=0 with lower_is_better means "zero is the goal"
      → score 1.0 if actual==0, else 0.0
    - Clamps at 1.0 (can't exceed target)
    """
    if actual is None:
        return 0.0
    if target == 0:
        if not higher_is_better:
            return 1.0 if actual == 0.0 else 0.0
        return 0.0
    ratio = actual / target
    if not higher_is_better:
        ratio = target / actual if actual > 0 else 1.0
    return max(0.0, min(1.0, ratio))


def _status_from_score(score: float) -> str:
    """Map 0–1 score to OKR status label (Turkish-ready)."""
    if score >= 1.0:
        return "achieved"
    if score >= 0.7:
        return "on_track"
    if score >= 0.4:
        return "at_risk"
    return "off_track"


def _momentum_score(current: float | None, previous: float | None) -> tuple[float, str]:
    """
    Calculate momentum (velocity of change).
    Returns: (momentum_value, momentum_label)
    
    momentum_value: -1.0 to +1.0 (negative = decelerating, positive = accelerating)
    momentum_label: "decelerating" | "flat" | "accelerating"
    """
    if current is None or previous is None:
        return 0.0, "unknown"
    
    delta = current - previous
    if abs(delta) < 0.02:
        return 0.0, "flat"
    elif delta > 0:
        return min(1.0, delta * 5), "accelerating"
    else:
        return max(-1.0, delta * 5), "decelerating"


def _confidence_from_data_freshness(
    days_since_update: int | None = None,
    data_quality: str | None = None,
) -> float:
    """
    Estimate confidence based on data recency and quality.
    - Freshness: 0 days = 1.0, 30 days = 0.8, 90+ days = 0.5
    - Quality: "high" = +0.1, "low" = -0.15
    """
    if days_since_update is None:
        days_since_update = 0
    
    if days_since_update <= 0:
        conf = 1.0
    elif days_since_update <= 7:
        conf = 0.95
    elif days_since_update <= 30:
        conf = 0.85
    elif days_since_update <= 60:
        conf = 0.70
    else:
        conf = 0.55
    
    if data_quality == "high":
        conf = min(1.0, conf + 0.10)
    elif data_quality == "low":
        conf = max(0.0, conf - 0.15)
    
    return round(conf, 2)


def _overall_status(key_results: list[dict[str, Any]]) -> tuple[str, float]:
    """Compute aggregate status + weighted score from key results."""
    if not key_results:
        return "off_track", 0.0
    scores = [kr["progress_pct"] / 100.0 for kr in key_results]
    avg = sum(scores) / len(scores)
    return _status_from_score(avg), round(avg, 3)


# ─────────────────────────────────────────────────────────────────────────────
# OKR Inference
# ─────────────────────────────────────────────────────────────────────────────

def _infer_okrs(
    financial_summary: dict[str, Any] | None,
    tech_summary: dict[str, Any] | None,
    cross_risks: list[dict[str, Any]] | None,
    period: str | None,
    okr_definitions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Derive standard OKRs from CFO + CTO outputs.
    Now includes strategic weights and momentum tracking.
    """
    fin   = financial_summary or {}
    tech  = tech_summary or {}
    risks = cross_risks or []

    # Pull metrics
    net_margin          = fin.get("net_margin")
    revenue_cents       = fin.get("revenue_cents")
    cash_runway_months  = fin.get("cash_runway_months")
    forecast_12m_cents  = fin.get("forecast_base_12m_cents")
    prev_net_margin     = fin.get("prev_net_margin")

    infra_waste_cents   = tech.get("infra_waste_cents")
    infra_cost_cents    = tech.get("infra_cost_cents")
    debt_score          = tech.get("debt_score")
    mttr_hours          = tech.get("mttr_hours")
    avg_velocity        = tech.get("avg_velocity")
    prev_mttr_hours     = tech.get("prev_mttr_hours")

    critical_risk_count = sum(1 for r in risks if r.get("severity") == "critical")

    # ── Strategic weights (sum = 1.0) ──────────────────────────────────────────
    # Higher weight = more strategic importance for this company
    weights = {
        "fin_profitability": 0.25,   # Sustainability
        "fin_growth":        0.15,   # Revenue expansion
        "tech_reliability":  0.20,   # Operational resilience
        "tech_efficiency":   0.15,   # Cost optimization
        "team_velocity":     0.15,   # Execution capability
        # Remaining 10% reserved for emergent objectives
    }

    # ── Default OKR definitions with strategic weights ───────────────────────
    defaults: dict[str, dict[str, Any]] = {
        "fin_profitability": {
            "title":   "Sürdürülebilir Kârlılığı Sağla",
            "owner":   "CFO",
            "weight":  weights["fin_profitability"],
            "krs": [
                {
                    "kr":               "Net marj ≥ 15%",
                    "target":           0.15,
                    "actual":           net_margin,
                    "unit":             "oran",
                    "higher_is_better": True,
                    "data_freshness_days": 7,
                },
                {
                    "kr":               "Nakit pisti ≥ 12 ay",
                    "target":           12.0,
                    "actual":           cash_runway_months,
                    "unit":             "ay",
                    "higher_is_better": True,
                    "data_freshness_days": 5,
                },
            ],
        },
        "fin_growth": {
            "title":   "Gelir Büyümesini Sürükle",
            "owner":   "CFO",
            "weight":  weights["fin_growth"],
            "krs": [
                {
                    "kr":               "12 aylık tahmin ≥ gelirin %110'u",
                    "target":           1.10,
                    "actual":           (forecast_12m_cents / revenue_cents)
                                        if (forecast_12m_cents and revenue_cents and revenue_cents > 0)
                                        else None,
                    "unit":             "oran",
                    "higher_is_better": True,
                    "data_freshness_days": 14,
                },
            ],
        },
        "tech_reliability": {
            "title":   "Mühendislik Güvenilirliğini İyileştir",
            "owner":   "CTO",
            "weight":  weights["tech_reliability"],
            "krs": [
                {
                    "kr":               "MTTR ≤ 2 saat",
                    "target":           2.0,
                    "actual":           mttr_hours,
                    "unit":             "saat",
                    "higher_is_better": False,
                    "data_freshness_days": 7,
                    "prev_actual":      prev_mttr_hours,
                },
                {
                    "kr":               "Sıfır kritik çapraz alan riski",
                    "target":           0.0,
                    "actual":           float(critical_risk_count),
                    "unit":             "sayı",
                    "higher_is_better": False,
                    "data_freshness_days": 1,
                },
            ],
        },
        "tech_efficiency": {
            "title":   "Altyapı İsrafını Azalt",
            "owner":   "CTO",
            "weight":  weights["tech_efficiency"],
            "krs": [
                {
                    "kr":               "Altyapı israfı ≤ cost'un %10'u",
                    "target":           0.10,
                    "actual":           (infra_waste_cents / infra_cost_cents)
                                        if (infra_waste_cents is not None and infra_cost_cents and infra_cost_cents > 0)
                                        else None,
                    "unit":             "oran",
                    "higher_is_better": False,
                    "data_freshness_days": 3,
                },
                {
                    "kr":               "Teknik borç skoru ≤ 4 (0–10 scale)",
                    "target":           4.0,
                    "actual":           debt_score,
                    "unit":             "skor",
                    "higher_is_better": False,
                    "data_freshness_days": 30,
                },
            ],
        },
        "team_velocity": {
            "title":   "Mühendislik Hızını Artır",
            "owner":   "Engineering",
            "weight":  weights["team_velocity"],
            "krs": [
                {
                    "kr":               "Ortalama sprint hızı ≥ 40 puan",
                    "target":           40.0,
                    "actual":           avg_velocity,
                    "unit":             "puan/sprint",
                    "higher_is_better": True,
                    "data_freshness_days": 7,
                },
            ],
        },
    }

    # Apply custom okr_definitions overrides if provided
    if okr_definitions:
        for defn in okr_definitions:
            obj_id = defn.get("id")
            if obj_id and obj_id in defaults:
                for override_kr in (defn.get("key_results") or []):
                    for default_kr in defaults[obj_id]["krs"]:
                        if default_kr["kr"] == override_kr.get("kr"):
                            if "target" in override_kr:
                                default_kr["target"] = override_kr["target"]

    # ── Build scored objectives with momentum ─────────────────────────────────
    objectives: list[dict[str, Any]] = []
    for obj_id, obj_def in defaults.items():
        krs_out: list[dict[str, Any]] = []
        for kr_def in obj_def["krs"]:
            score = _score_kr(
                actual=kr_def["actual"],
                target=kr_def["target"],
                higher_is_better=kr_def["higher_is_better"],
            )
            
            # Momentum: compare actual vs previous actual
            momentum_val, momentum_label = _momentum_score(
                kr_def.get("actual"),
                kr_def.get("prev_actual"),
            )
            
            # Confidence based on data freshness
            confidence = _confidence_from_data_freshness(
                days_since_update=kr_def.get("data_freshness_days", 30),
                data_quality="high" if kr_def.get("data_freshness_days", 100) <= 14 else "low",
            )

            krs_out.append({
                "kr":           kr_def["kr"],
                "target":       kr_def["target"],
                "actual":       kr_def["actual"],
                "unit":         kr_def["unit"],
                "status":       _status_from_score(score),
                "progress_pct": round(score * 100),
                "momentum":     round(momentum_val, 3),
                "momentum_label": momentum_label,
                "confidence":   confidence,
            })

        overall_status, avg_score = _overall_status(krs_out)
        weight = obj_def.get("weight", 0.20)
        weighted_score = round(avg_score * weight, 3)
        
        # Objective-level momentum
        obj_momentum_vals = [kr["momentum"] for kr in krs_out if kr.get("momentum") is not None]
        if obj_momentum_vals:
            obj_momentum = sum(obj_momentum_vals) / len(obj_momentum_vals)
            obj_momentum_label = (
                "accelerating" if obj_momentum > 0.05
                else "decelerating" if obj_momentum < -0.05
                else "flat"
            )
        else:
            obj_momentum = 0.0
            obj_momentum_label = "unknown"

        objectives.append({
            "id":               obj_id,
            "title":            obj_def["title"],
            "owner":            obj_def["owner"],
            "weight":           weight,
            "key_results":      krs_out,
            "overall_status":   overall_status,
            "score":            avg_score,
            "weighted_score":   weighted_score,
            "momentum":         round(obj_momentum, 3),
            "momentum_label":   obj_momentum_label,
        })

    return objectives


# ─────────────────────────────────────────────────────────────────────────────
# OKR Narrative (with momentum & weighted scores)
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_okr_narrative(
    objectives: list[dict[str, Any]],
    period: str | None,
    company_weighted_score: float,
    settings: Any,
) -> str:
    """Generate Türkçe OKR summary with weighted scores and momentum."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        achieved  = [o for o in objectives if o["overall_status"] == "achieved"]
        on_track  = [o for o in objectives if o["overall_status"] == "on_track"]
        at_risk   = [o for o in objectives if o["overall_status"] == "at_risk"]
        off_track = [o for o in objectives if o["overall_status"] == "off_track"]

        accel = len([o for o in objectives if o.get("momentum_label") == "accelerating"])
        decel = len([o for o in objectives if o.get("momentum_label") == "decelerating"])

        summary_lines = []
        for obj in objectives:
            kr_lines = ", ".join(
                f"{kr['kr']} ({kr['progress_pct']}% — {kr['status']})"
                for kr in obj["key_results"]
            )
            summary_lines.append(
                f"• {obj['title']} [{obj['overall_status']} — {obj['momentum_label']:12}] "
                f"(W={obj['weight']:.0%}): {kr_lines}"
            )

        prompt = (
            f"Dönem: {period or 'mevcut'}\n"
            f"Ağırlıklandırılmış OKR Skoru: {company_weighted_score:.0%}\n\n"
            "OKR Özetleri:\n" + "\n".join(summary_lines) + "\n\n"
            f"İstatistik: {len(achieved)} tamamlandı, {len(on_track)} yolunda, "
            f"{len(at_risk)} riskli, {len(off_track)} geride.\n"
            f"Momentum: {accel} hızlanıyor, {decel} yavaşlıyor.\n\n"
            "Türkçe olarak 3-4 cümlelik yönetici OKR güncellemesi yaz. "
            "Nelerin iyi gittiğini, nelerin riskli olduğunu, momentum trendlerini ve "
            "yapılması gereken tek en önemli eylemi belirt. Sade ve doğrudan yaz."
        )

        llm = ChatOpenAI(
            model=getattr(settings, "llm_model", "gpt-4o-mini"),
            api_key=settings.openai_api_key,
            base_url=getattr(settings, "llm_base_url", None) or None,
            temperature=0.3,
            max_tokens=450,
        )
        response = await llm.ainvoke([
            SystemMessage(content="Sen Türkçe olarak kısa, öz ve aksiyon odaklı OKR durum güncellemeleri yazan deneyimli yönetim danışmanısın."),
            HumanMessage(content=prompt),
        ])
        return response.content.strip()

    except Exception as exc:
        logger.warning("OKR narrative generation failed: %s", exc)
        # Fallback: rule-based summary
        achieved_titles  = [o["title"] for o in objectives if o["overall_status"] == "achieved"]
        at_risk_titles   = [o["title"] for o in objectives if o["overall_status"] == "at_risk"]
        off_track_titles = [o["title"] for o in objectives if o["overall_status"] == "off_track"]
        accel_titles     = [o["title"] for o in objectives if o.get("momentum_label") == "accelerating"]
        decel_titles     = [o["title"] for o in objectives if o.get("momentum_label") == "decelerating"]

        parts: list[str] = []
        if achieved_titles:
            parts.append(f"Tamamlanan: {', '.join(achieved_titles)}.")
        if on_track_titles := [o["title"] for o in objectives if o["overall_status"] == "on_track"]:
            parts.append(f"Yolunda: {', '.join(on_track_titles)}.")
        if at_risk_titles:
            parts.append(f"Riskli: {', '.join(at_risk_titles)}.")
        if off_track_titles:
            parts.append(f"Geride: {', '.join(off_track_titles)}.")
        if accel_titles:
            parts.append(f"Hızlanma trendi: {', '.join(accel_titles)}.")
        if not parts:
            parts.append("Tüm hedefler izleniyor.")
        return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Main Agent Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def run_okr_agent(
    state: dict[str, Any],
    config: dict,
) -> dict[str, Any]:
    """
    OKR Tracking Agent node for the CEO LangGraph.
    
    Enhancements:
    - Weighted scoring: strategic importance per objective
    - Momentum tracking: acceleration/deceleration indicators
    - Confidence intervals on estimates
    - Company-level weighted OKR score
    
    Reads: financial_summary, tech_summary, cross_risks, period
    Writes: okr_status (with weighted_score, momentum, confidence)
    """
    from app.agents.ceo.state import CEOStepLog

    logger.info("OKR agent: starting with momentum & weighted scoring")
    try:
        from app.config import get_settings
        settings = get_settings()

        objectives = _infer_okrs(
            financial_summary=state.get("financial_summary"),
            tech_summary=state.get("tech_summary"),
            cross_risks=state.get("cross_risks") or [],
            period=state.get("period"),
            okr_definitions=state.get("okr_definitions"),
        )

        # Compute company-level weighted OKR score
        company_weighted_score = round(
            sum(obj.get("weighted_score", 0) for obj in objectives),
            3,
        )

        narrative = await _generate_okr_narrative(
            objectives=objectives,
            period=state.get("period"),
            company_weighted_score=company_weighted_score,
            settings=settings,
        )

        okr_status: dict[str, Any] = {
            "objectives":              objectives,
            "period":                  state.get("period"),
            "company_weighted_okr_score": company_weighted_score,
            "generated_at":            datetime.now(timezone.utc).isoformat(),
            "narrative":               narrative,
        }

        log = CEOStepLog(
            step="okr_agent",
            ok=True,
            detail=f"{len(objectives)} objectives scored; weighted OKR: {company_weighted_score:.0%}",
            confidence=0.95,
        )

        logs = list(state.get("logs") or [])
        logs.append(log)
        return {**state, "okr_status": okr_status, "logs": logs}

    except Exception as exc:
        logger.exception("OKR agent failed: %s", exc)
        log = CEOStepLog(step="okr_agent", ok=False, detail=str(exc), confidence=0.0)
        logs = list(state.get("logs") or [])
        logs.append(log)
        return {**state, "logs": logs}
