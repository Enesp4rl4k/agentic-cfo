"""
SWOT Analysis Agent -- CEO Skill 4

Tum C-Suite agent sonuclarindan otomatik SWOT matrisi olusturur.

Her SWOT maddesi:
  - Hangi domain'den geldigini belirtir (CFO, CTO, CMO, ...)
  - Kanit zincirine sahiptir (sayi + kaynak)
  - Oncelik skoru vardir (1-10)
  - Aksiyon onerisi icerir

Guclu yonler (Strengths)   -- icsel olumlu gostergeler
Zayif yonler (Weaknesses)  -- icsel olumsuz gostergeler
Firsatlar   (Opportunities) -- dissal gelisme potansiyeli
Tehditler   (Threats)       -- dissal risk faktorleri

Calistirma:
    result = await run_swot_agent(ceo_state, run_config)
    # result.patch["swot_matrix"] -> dict with S/W/O/T lists
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.ceo.state import CEOState, CEORunConfig, CEOSkillResult

logger = logging.getLogger(__name__)


# ── SWOT item ─────────────────────────────────────────────────────────────────

def _item(
    text: str,
    domain: str,
    priority: int,
    evidence: str,
    action: str = "",
) -> dict[str, Any]:
    return {
        "text":     text,
        "domain":   domain,
        "priority": priority,   # 1 (dusuk) .. 10 (kritik)
        "evidence": evidence,
        "action":   action,
    }


# ── Rule-based SWOT extractor ─────────────────────────────────────────────────

def _extract_swot(
    fin:        dict[str, Any],
    tech:       dict[str, Any],
    mkt:        dict[str, Any] | None,
    hr:         dict[str, Any] | None,
    ops:        dict[str, Any] | None,
    risk:       dict[str, Any] | None,
    compliance: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Deterministik SWOT cikarimi -- LLM yok, hizli ve auditable.
    """
    strengths:     list[dict[str, Any]] = []
    weaknesses:    list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    threats:       list[dict[str, Any]] = []

    # ── CFO / Finansal ────────────────────────────────────────────────────────
    net_margin    = fin.get("net_margin", 0) or 0
    runway        = fin.get("cash_runway_months") or fin.get("runway_months")
    revenue_trend = fin.get("revenue_trend", 0) or 0
    revenue       = fin.get("revenue", 0) or 0

    if net_margin > 0.15:
        strengths.append(_item(
            f"Guclu net kar marji: %{net_margin*100:.1f}",
            "cfo", 8,
            f"Net marj {net_margin*100:.1f}% -- sektor ortalamasinin ustunde",
            "Marji korumak icin maliyet disiplinini surdur",
        ))
    elif net_margin < 0:
        weaknesses.append(_item(
            f"Negatif net marj: %{net_margin*100:.1f}",
            "cfo", 9,
            f"Net zarar -- operasyonel verimlilik sorunu",
            "Acil maliyet optimizasyonu ve gelir artirici aksiyonlar",
        ))

    if runway is not None:
        if runway > 18:
            strengths.append(_item(
                f"Guclu nakit pozisyonu: {runway:.0f} ay runway",
                "cfo", 7,
                f"Nakit omru {runway:.0f} ay -- yatirim ve buyume kapasitesi var",
                "Stratejik yatirimlari degerlendir",
            ))
        elif runway < 6:
            threats.append(_item(
                f"Kritik nakit riski: {runway:.1f} ay runway",
                "cfo", 10,
                f"Mevcut burn rate ile {runway:.1f} ay nakit kaldi",
                "Acil fundraising veya maliyet kesintisi gerekli",
            ))

    if revenue_trend > 0.1:
        strengths.append(_item(
            f"Gelir buyumesi: %{revenue_trend*100:.0f} artis",
            "cfo", 7,
            f"Son donemde %{revenue_trend*100:.0f} gelir artisi",
            "Buyume kanallarini scale et",
        ))
    elif revenue_trend < -0.1:
        weaknesses.append(_item(
            f"Gelir gerilemeleri: %{abs(revenue_trend)*100:.0f} dusus",
            "cfo", 8,
            f"Son donemde %{abs(revenue_trend)*100:.0f} gelir kaybi",
            "Musteri kayip nedenini analiz et, retention programi baslat",
        ))

    # ── CTO / Teknoloji ───────────────────────────────────────────────────────
    tech_health   = tech.get("overall_health_score") or tech.get("health_score", 5)
    debt_score    = tech.get("debt_score", 0) or 0
    infra_waste   = tech.get("infra_waste_pct", 0) or 0
    vel_trend     = tech.get("velocity_trend", "stable") or "stable"

    if tech_health and tech_health >= 8:
        strengths.append(_item(
            f"Yuksek teknoloji saglik skoru: {tech_health}/10",
            "cto", 7,
            f"Tech health {tech_health}/10 -- guclu muhendislik pratikleri",
            "Teknik ustunlugu urun farklilasmasi olarak kullan",
        ))
    elif tech_health and tech_health < 5:
        weaknesses.append(_item(
            f"Dusuk teknoloji saglik skoru: {tech_health}/10",
            "cto", 8,
            f"Tech health {tech_health}/10 -- teknik borc kritik seviyede",
            "Teknik borc azaltma sprintleri planla",
        ))

    if debt_score > 7:
        weaknesses.append(_item(
            f"Yuksek teknik borc: {debt_score}/10",
            "cto", 7,
            f"Teknik borc skoru {debt_score}/10",
            "Her sprintin %20'sini teknik borc odemeye ayir",
        ))

    if infra_waste > 0.2:
        opportunities.append(_item(
            f"Altyapi israf optimizasyon firsati: %{infra_waste*100:.0f}",
            "cto", 6,
            f"Altyapi maliyetlerinin %{infra_waste*100:.0f}'i israf",
            "Cloud cost optimization -- hemen hayata gec",
        ))

    if vel_trend == "increasing":
        strengths.append(_item(
            "Artan muhendislik velocity",
            "cto", 6,
            "Son sprintlerde velocity artis trendi",
            "Sureci dokumante et, diger takimlara yay",
        ))
    elif vel_trend == "decreasing":
        weaknesses.append(_item(
            "Dusen muhendislik velocity",
            "cto", 7,
            "Son sprintlerde velocity dusus trendi",
            "Blocker'lari tespit et, sprint retrospektif yap",
        ))

    # ── CMO / Pazarlama ───────────────────────────────────────────────────────
    if mkt:
        roas    = mkt.get("overall_roas", 0) or 0
        cac     = (mkt.get("cac") or mkt.get("avg_cac_cents", 0) or 0) / 100
        churn   = mkt.get("avg_monthly_churn", 0) or 0
        ltv_cac = mkt.get("ltv_cac_ratio", 0) or 0

        if roas > 3:
            strengths.append(_item(
                f"Yuksek pazarlama ROI: {roas:.1f}x ROAS",
                "cmo", 7,
                f"Pazarlama yatiriminin {roas:.1f}x getirisi var",
                "En iyi performansli kanallara yatirimi artir",
            ))
        elif roas < 1.5 and roas > 0:
            weaknesses.append(_item(
                f"Dusuk pazarlama verimliligi: {roas:.1f}x ROAS",
                "cmo", 6,
                f"Pazarlama ROAS hedefin ({roas:.1f}x) altinda",
                "Kanal karisimini revize et, dusuk ROAS'li kanallari kes",
            ))

        if churn > 0.05:
            threats.append(_item(
                f"Yuksek musteri kayip orani: aylik %{churn*100:.1f}",
                "cmo", 8,
                f"Aylik %{churn*100:.1f} churn -- LTV/CAC oranini baski altina aliyor",
                "Retention programi ve NPS iyilestirme kampanyasi baslat",
            ))

        if ltv_cac > 3:
            strengths.append(_item(
                f"Guclu LTV/CAC orani: {ltv_cac:.1f}x",
                "cmo", 8,
                f"Musteri yasam boyu degeri CAC'nin {ltv_cac:.1f}x'i",
                "Buyume icin musteri edinme butcesini artir",
            ))

    # ── CHRO / Insan Kaynaklari ───────────────────────────────────────────────
    if hr:
        turnover      = hr.get("annual_turnover_rate", 0) or 0
        headcount     = hr.get("total_headcount", 0) or 0
        engagement    = hr.get("engagement_score", 0) or 0
        open_roles    = hr.get("open_critical_roles", 0) or 0

        if turnover < 0.10:
            strengths.append(_item(
                f"Dusuk personel devir hizi: %{turnover*100:.0f}",
                "chro", 7,
                f"Yillik turnover %{turnover*100:.0f} -- guclU ekip istikrari",
                "Retention programlarini surdurulebilir yap",
            ))
        elif turnover > 0.20:
            weaknesses.append(_item(
                f"Yuksek personel devir hizi: %{turnover*100:.0f}",
                "chro", 8,
                f"Yillik %{turnover*100:.0f} turnover -- yuksek ise alim maliyeti ve bilgi kaybi",
                "Exit interview analizi yap, compensation benchmark guncelle",
            ))

        if engagement > 75:
            strengths.append(_item(
                f"Yuksek calisan baglilik skoru: {engagement}/100",
                "chro", 6,
                f"Calisan baglilik skoru {engagement}/100",
                "Basari hikayelerini paylas, kultur elcilerini guclendir",
            ))
        elif engagement and engagement < 50:
            threats.append(_item(
                f"Dusuk calisan baglilik: {engagement}/100",
                "chro", 7,
                f"Calisan baglilik {engagement}/100 -- attrition riski",
                "Acil eNPS anketi ve takip planı hazirla",
            ))

        if open_roles > 3:
            weaknesses.append(_item(
                f"{open_roles} kritik rol acik",
                "chro", 7,
                f"{open_roles} kritik pozisyon dolu degil",
                "Oncelikli rolleri belirle, ise alim surecini hizlandir",
            ))

    # ── COO / Operasyon ───────────────────────────────────────────────────────
    if ops:
        sla_compliance = ops.get("sla_compliance", 0) or 0
        ops_score      = ops.get("overall_ops_score", 0) or 0

        if sla_compliance > 0.95:
            strengths.append(_item(
                f"Yuksek SLA uyumu: %{sla_compliance*100:.0f}",
                "coo", 6,
                f"SLA uyum orani %{sla_compliance*100:.0f}",
                "Operasyonel mukemmelligi urun satisinda on plana cikart",
            ))
        elif sla_compliance < 0.80 and sla_compliance > 0:
            weaknesses.append(_item(
                f"Dusuk SLA uyumu: %{sla_compliance*100:.0f}",
                "coo", 7,
                f"SLA uyum orani %{sla_compliance*100:.0f} -- musteri memnuniyeti riski",
                "Kritik SLA'lari belirle, kapasite planlama guncelle",
            ))

    # ── Risk / Uyumluluk ──────────────────────────────────────────────────────
    if risk:
        critical_risks = risk.get("critical_count", 0) or 0
        if critical_risks > 2:
            threats.append(_item(
                f"{critical_risks} kritik risk aktif",
                "risk", 9,
                f"Risk kayit defterinde {critical_risks} kritik risk acik",
                "Risk mitigasyon planlarini haftaik takip et",
            ))

    if compliance:
        violations = compliance.get("violation_count", 0) or 0
        if violations > 0:
            threats.append(_item(
                f"{violations} uyumluluk ihlali",
                "compliance", 10,
                f"{violations} aktif uyumluluk ihlali -- yasal risk",
                "Hukuk danismani ile acil degerlendirme yap",
            ))

    # ── Firsatlar (cross-domain) ──────────────────────────────────────────────
    if fin and mkt:
        if revenue_trend > 0.05 and roas > 2:  # type: ignore[possibly-undefined]
            opportunities.append(_item(
                "Buyume momentum: gelir + pazarlama verimliligi birlikte yukseliyor",
                "cfo+cmo", 8,
                "Hem gelir artisi hem yuksek ROAS ayni anda gozlemleniyor",
                "Pazarlama butcesini %20-30 artirarak buyumeyi hizlandir",
            ))

    if tech and hr:
        if (tech_health or 0) >= 7 and (turnover or 0) < 0.15:  # type: ignore[possibly-undefined]
            opportunities.append(_item(
                "Guclü teknik ekip + istikrar -- urun gelistirme kapasitesi hazir",
                "cto+chro", 7,
                f"Tech health {tech_health}/10, turnover %{(turnover or 0)*100:.0f}",
                "Yeni urun/ozellik roadmap'ini hizlandir",
            ))

    # Onceliklere gore sirala
    for lst in [strengths, weaknesses, opportunities, threats]:
        lst.sort(key=lambda x: -x["priority"])

    return {
        "strengths":     strengths[:6],
        "weaknesses":    weaknesses[:6],
        "opportunities": opportunities[:5],
        "threats":       threats[:5],
    }


# ── LLM zenginlestirme (opsiyonel) ───────────────────────────────────────────

async def _enrich_with_llm(
    swot: dict[str, list[dict[str, Any]]],
    company_name: str | None,
    run_config: CEORunConfig,
) -> str:
    """
    SWOT matrisini LLM ile ozet narrative'e donustur.
    LLM yoksa veya basarisiz olursa deterministik fallback kullanir.
    """
    total_s = len(swot["strengths"])
    total_w = len(swot["weaknesses"])
    total_o = len(swot["opportunities"])
    total_t = len(swot["threats"])

    fallback = (
        f"SWOT analizi tamamlandi: {total_s} guclu yon, {total_w} zayif yon, "
        f"{total_o} firsat, {total_t} tehdit tespit edildi. "
        "En yuksek oncelikli maddeler icin domain bazli detaylari inceleyin."
    )

    if not run_config.use_llm:
        return fallback

    try:
        from app.services.llm_structured import call_llm

        top_s = swot["strengths"][0]["text"]   if swot["strengths"]     else "yok"
        top_w = swot["weaknesses"][0]["text"]  if swot["weaknesses"]    else "yok"
        top_o = swot["opportunities"][0]["text"] if swot["opportunities"] else "yok"
        top_t = swot["threats"][0]["text"]     if swot["threats"]       else "yok"

        prompt = (
            f"Asagidaki SWOT analizi verilerine dayanarak "
            f"{'icin ' + company_name if company_name else 'sirket icin'} "
            f"3-4 cumlelik Turkce yonetici ozeti yaz.\n\n"
            f"En guclu yon: {top_s}\n"
            f"En onemli zayiflik: {top_w}\n"
            f"En buyuk firsat: {top_o}\n"
            f"En kritik tehdit: {top_t}\n\n"
            f"Toplam: {total_s} guclu yon, {total_w} zayiflik, "
            f"{total_o} firsat, {total_t} tehdit.\n"
            "Ozet (Turkce, 3-4 cumle):"
        )
        summary = await call_llm(prompt, max_tokens=300)
        return summary.strip() if summary else fallback
    except Exception as exc:
        logger.debug("SWOT LLM zenginlestirme atlandi: %s", exc)
        return fallback


# ── Ana agent fonksiyonu ──────────────────────────────────────────────────────

async def run_swot_agent(
    state: CEOState,
    run_config: CEORunConfig,
) -> CEOSkillResult:
    """
    CEO state'inden SWOT matrisi olusturur.

    Input:  state["financial_summary"], state["tech_summary"],
            state["marketing_summary"], state["hr_summary"],
            state["ops_summary"]
    Output: state["swot_matrix"] + state["swot_summary"]
    """
    fin  = state.get("financial_summary") or {}
    tech = state.get("tech_summary")      or {}
    mkt  = state.get("marketing_summary")
    hr   = state.get("hr_summary")
    ops  = state.get("ops_summary")

    # Risk/compliance varsa cek
    risk       = None
    compliance = None
    try:
        from app.agents.ceo.synthesis_agent import _condense_risk_summary   # type: ignore[attr-defined]
        risk_r = state.get("_risk_result") or {}
        if risk_r:
            risk = risk_r
    except Exception:
        pass

    if not fin and not tech:
        return CEOSkillResult(
            ok=False,
            detail="SWOT icin en az CFO veya CTO verisi gerekli",
            confidence=0.0,
            patch={},
        )

    swot = _extract_swot(fin, tech, mkt, hr, ops, risk, compliance)

    summary = await _enrich_with_llm(
        swot,
        state.get("company_name"),
        run_config,
    )

    total_items = sum(len(v) for v in swot.values())
    confidence  = min(0.95, 0.6 + (total_items / 20) * 0.35)

    return CEOSkillResult(
        ok=True,
        detail=(
            f"SWOT: {len(swot['strengths'])}G / {len(swot['weaknesses'])}Z / "
            f"{len(swot['opportunities'])}F / {len(swot['threats'])}T"
        ),
        confidence=round(confidence, 2),
        patch={
            "swot_matrix":  swot,
            "swot_summary": summary,
        },
    )


# ── Standalone entry point (API'den direk cagirmak icin) ──────────────────────

async def run_swot_from_context(
    pnl:        dict[str, Any] | None = None,
    cashflow:   dict[str, Any] | None = None,
    forecast:   dict[str, Any] | None = None,
    chro_data:  dict[str, Any] | None = None,
    cto_data:   dict[str, Any] | None = None,
    cmo_data:   dict[str, Any] | None = None,
    coo_data:   dict[str, Any] | None = None,
    company_name: str | None = None,
    use_llm:    bool = True,
) -> dict[str, Any]:
    """
    CEO state olmadan direk veri ile SWOT olustur.
    API endpoint'i bu fonksiyonu cagirabilir.
    """
    from app.agents.ceo.state import DEFAULT_CEO_RUN_CONFIG

    cfg = DEFAULT_CEO_RUN_CONFIG
    if not use_llm:
        from dataclasses import replace
        cfg = replace(cfg, use_llm=False)

    # Minimal summaries
    fin: dict[str, Any] = {}
    if pnl:
        fin.update({
            "revenue":            pnl.get("revenue", 0),
            "net_margin":         pnl.get("net_margin", 0),
            "revenue_trend":      pnl.get("revenue_growth_pct", 0),
            "cash_runway_months": (forecast or {}).get("scenarios", {}).get("base", {}).get("runway_months"),
        })
    if cashflow:
        fin["cash_runway_months"] = fin.get("cash_runway_months") or cashflow.get("runway_months")

    tech: dict[str, Any] = {}
    if cto_data:
        tech.update({
            "overall_health_score": cto_data.get("overall_health_score", 5),
            "debt_score":           cto_data.get("tech_debt_score", 0),
            "infra_waste_pct":      cto_data.get("infra_waste_pct", 0),
            "velocity_trend":       cto_data.get("velocity_trend", "stable"),
        })

    mkt: dict[str, Any] | None = None
    if cmo_data:
        mkt = {
            "overall_roas":     cmo_data.get("overall_roas", 0),
            "cac":              cmo_data.get("avg_cac_cents", 0),
            "avg_monthly_churn": cmo_data.get("avg_monthly_churn", 0),
            "ltv_cac_ratio":    cmo_data.get("ltv_cac_ratio", 0),
        }

    hr: dict[str, Any] | None = None
    if chro_data:
        hr = {
            "annual_turnover_rate": chro_data.get("annual_turnover_rate", 0),
            "total_headcount":      chro_data.get("total_headcount", 0),
            "engagement_score":     chro_data.get("engagement_score", 0),
            "open_critical_roles":  chro_data.get("open_critical_roles", 0),
        }

    ops: dict[str, Any] | None = None
    if coo_data:
        ops = {
            "sla_compliance":    coo_data.get("sla_compliance", 0),
            "overall_ops_score": coo_data.get("overall_ops_score", 5),
        }

    synthetic_state: CEOState = {  # type: ignore[typeddict-item]
        "job_id":            "swot-standalone",
        "company_name":      company_name,
        "period":            None,
        "financial_summary": fin,
        "tech_summary":      tech,
        "marketing_summary": mkt,
        "hr_summary":        hr,
        "ops_summary":       ops,
        "logs":              [],
        "min_confidence":    1.0,
        "awaiting_review":   False,
        "halted":            False,
        "error":             None,
    }

    result = await run_swot_agent(synthetic_state, cfg)
    return {
        "swot_matrix":  result.patch.get("swot_matrix", {}),
        "swot_summary": result.patch.get("swot_summary", ""),
        "confidence":   result.confidence,
        "ok":           result.ok,
        "detail":       result.detail,
    }
