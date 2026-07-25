"""
Internal Audit Orchestrator

LangGraph pipeline: findings → controls → coverage → audit_summary → END

Enhancements:
- IIA maturity labels in Turkish (OPTİMİZE / YÖNETİLİYOR / TANIMLI / GELİŞİYOR / BAŞLANGIÇ)
- IIA control effectiveness classification
- Repeat finding trend detection → risk-based audit priorities
- LLM narrative in Turkish for Denetim Komitesi
- Türkçe top_issues + quick_wins
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from langgraph.graph import StateGraph, END

from app.agents.audit.state import AuditState, AuditStepLog
from app.agents.audit.findings_agent import run_findings_agent
from app.agents.audit.controls_agent import run_controls_agent
from app.agents.audit.coverage_agent import run_coverage_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IIA Maturity model — Turkish labels
# ---------------------------------------------------------------------------
_IIA_MATURITY: dict[str, dict[str, str]] = {
    "optimised": {
        "label": "OPTİMİZE",
        "description": "İç denetim süreci sürekli iyileştirme döngüsünde; proaktif risk yönetimi.",
        "iia_level": "5",
    },
    "managed": {
        "label": "YÖNETİLİYOR",
        "description": "Denetim süreci ölçülüyor ve kontrol ediliyor; KPI'lar takip ediliyor.",
        "iia_level": "4",
    },
    "defined": {
        "label": "TANIMLI",
        "description": "Standart süreçler belgelenmiş; tutarlı uygulama mevcut.",
        "iia_level": "3",
    },
    "developing": {
        "label": "GELİŞİYOR",
        "description": "Bazı süreçler tanımlanmış ancak tutarsız uygulanıyor.",
        "iia_level": "2",
    },
    "initial": {
        "label": "BAŞLANGIÇ",
        "description": "Ad-hoc süreçler; reaktif denetim yaklaşımı; acil iyileştirme gerekli.",
        "iia_level": "1",
    },
}

# IIA control effectiveness thresholds
_CTRL_EFFECTIVENESS_LABELS = [
    (75, "Etkili",           "Kontroller amacına uygun çalışıyor."),
    (55, "Genellikle Etkili","Küçük boşluklar mevcut; izleme yeterli."),
    (35, "Kısmen Etkili",   "Önemli boşluklar var; güçlendirme gerekli."),
    (0,  "Yetersiz",        "Kontrol ortamı ciddi risk altında; acil aksiyon gerekli."),
]


def _ctrl_effectiveness_label(score: float) -> tuple[str, str]:
    for threshold, label, desc in _CTRL_EFFECTIVENESS_LABELS:
        if score >= threshold:
            return label, desc
    return "Yetersiz", "Kontrol ortamı ciddi risk altında."


# ---------------------------------------------------------------------------
# Repeat finding detection
# ---------------------------------------------------------------------------

def _detect_repeat_findings(findings: dict[str, Any]) -> dict[str, Any]:
    """
    Analyse repeat finding patterns from findings data.
    Returns risk-based audit priorities based on recurring issues.
    """
    raw_findings: list[dict[str, Any]] = findings.get("raw_findings", [])
    if not raw_findings:
        return {"repeat_count": 0, "repeat_rate": 0.0, "high_risk_areas": [], "priorities": []}

    # Count category/area occurrences across findings
    area_counter: Counter = Counter()
    category_counter: Counter = Counter()
    critical_areas: list[str] = []

    for f in raw_findings:
        area = (f.get("area") or f.get("department") or "Genel").strip()
        category = (f.get("category") or f.get("type") or "Diğer").strip()
        area_counter[area] += 1
        category_counter[category] += 1
        if (f.get("severity") or "").lower() in ("critical", "yüksek", "high"):
            critical_areas.append(area)

    repeat_count = int(findings.get("repeat_findings", 0))
    total = max(int(findings.get("total_findings", 1)), 1)
    repeat_rate = repeat_count / total

    # High-risk areas: appeared 2+ times or had critical findings
    critical_area_set = set(critical_areas)
    high_risk_areas = [
        area for area, count in area_counter.most_common(10)
        if count >= 2 or area in critical_area_set
    ]

    # Risk-based audit priorities
    priorities: list[dict[str, str]] = []
    for area, count in area_counter.most_common(5):
        severity = "Yüksek" if area in critical_area_set else ("Orta" if count >= 2 else "Düşük")
        priorities.append({
            "area": area,
            "finding_count": str(count),
            "risk_level": severity,
            "recommendation": (
                f"'{area}' alanında {count} bulgu tespit edildi"
                + (" — kritik bulgular mevcut, öncelikli denetim planlanmalı." if area in critical_area_set
                   else " — tekrarlayan örüntü, kök neden analizi yapılmalı." if count >= 2
                   else " — rutin izleme yeterli.")
            ),
        })

    return {
        "repeat_count": repeat_count,
        "repeat_rate": round(repeat_rate, 3),
        "high_risk_areas": high_risk_areas[:5],
        "top_categories": [c for c, _ in category_counter.most_common(3)],
        "priorities": priorities,
    }


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

async def node_findings(state: AuditState, config: dict) -> AuditState:
    result = await run_findings_agent(state, config)
    return {**state, "findings": result["findings"],
            "logs": result["logs"], "error": result.get("error")}


async def node_controls(state: AuditState, config: dict) -> AuditState:
    result = await run_controls_agent(state, config)
    return {**state, "controls": result["controls"],
            "logs": result["logs"], "error": result.get("error")}


async def node_coverage(state: AuditState, config: dict) -> AuditState:
    result = await run_coverage_agent(state, config)
    return {**state, "coverage": result["coverage"],
            "logs": result["logs"], "error": result.get("error")}


# ---------------------------------------------------------------------------
# Main summary node
# ---------------------------------------------------------------------------

async def node_audit_summary(state: AuditState, config: dict) -> AuditState:  # noqa: C901
    """
    Synthesise findings + controls + coverage into Internal Audit Score.
    Score 0-100 (higher = healthier audit posture).
    Adds IIA maturity labels, control effectiveness, repeat finding analysis, LLM narrative.
    """
    fin  = state.get("findings") or {}
    ctrl = state.get("controls") or {}
    cov  = state.get("coverage") or {}
    logs: list[AuditStepLog] = list(state.get("logs") or [])

    settings = (config or {}).get("configurable", {}).get("settings")

    # -- Audit Health Score (0-100) -----------------------------------------
    # findings_score  : finding_health_score (0-100), weight 35 %
    # control_score   : overall_control_score (0-100), weight 40 %
    # coverage_score  : coverage_rate * 100,           weight 25 %

    findings_score = float(fin.get("finding_health_score", 100.0))
    control_score  = float(ctrl.get("overall_control_score", 100.0))
    coverage_score = float(cov.get("coverage_rate", 1.0)) * 100.0

    audit_health = round(
        findings_score * 0.35
        + control_score  * 0.40
        + coverage_score * 0.25,
        1,
    )

    # -- IIA Maturity (Turkish labels) --------------------------------------
    if audit_health >= 80:
        maturity_key = "optimised"
    elif audit_health >= 65:
        maturity_key = "managed"
    elif audit_health >= 50:
        maturity_key = "defined"
    elif audit_health >= 35:
        maturity_key = "developing"
    else:
        maturity_key = "initial"

    maturity_info = _IIA_MATURITY[maturity_key]
    maturity_label = maturity_info["label"]

    # -- IIA Control Effectiveness ------------------------------------------
    ctrl_eff_label, ctrl_eff_desc = _ctrl_effectiveness_label(control_score)

    # -- Repeat Finding Analysis --------------------------------------------
    repeat_analysis = _detect_repeat_findings(fin)
    repeat_count = repeat_analysis["repeat_count"]
    repeat_rate  = repeat_analysis["repeat_rate"]
    high_risk_areas = repeat_analysis["high_risk_areas"]

    # -- Top Issues (Turkish) -----------------------------------------------
    top_issues: list[dict[str, Any]] = []

    open_critical = fin.get("open_critical", 0)
    if open_critical:
        top_issues.append({
            "source":   "bulgular",
            "title":    f"{open_critical} kritik bulgu çözümsüz bekliyor",
            "severity": "kritik",
            "action":   "Denetim Komitesi'ne ilet; 30 günlük düzeltme planı oluştur.",
        })

    ineffective = len(ctrl.get("ineffective_controls", []))
    if ineffective:
        top_issues.append({
            "source":   "kontroller",
            "title":    f"{ineffective} kontrol yetersiz/etkisiz",
            "severity": "kritik",
            "action":   "Etkilenen kontrolleri yeniden tasarla; geçici telafi edici kontroller devreye al.",
        })

    hr_coverage = cov.get("high_risk_coverage", 1.0)
    if hr_coverage < 0.80:
        top_issues.append({
            "source":   "kapsam",
            "title":    f"Yüksek riskli birimlerde kapsam oranı %{hr_coverage:.0%} — yetersiz",
            "severity": "yüksek",
            "action":   "Gelecek çeyrekte denetlenmemiş yüksek riskli birimler önceliklendirilmeli.",
        })

    overdue_findings = fin.get("overdue_count", 0)
    if overdue_findings:
        top_issues.append({
            "source":   "bulgular",
            "title":    f"{overdue_findings} bulgunun düzeltmesi gecikiyor",
            "severity": "orta",
            "action":   "Sorumlu yöneticileri takibe al; 60 günü geçenler için eskalasyon başlat.",
        })

    if repeat_rate > 0.20:
        top_issues.append({
            "source":   "tekrar bulgular",
            "title":    f"Bulgular içinde %{repeat_rate:.0%} tekrarlayan bulgu — sistemik sorun sinyali",
            "severity": "yüksek",
            "action":   f"Kök neden analizi yapılmalı; özellikle şu alanlar: {', '.join(high_risk_areas[:3]) or 'belirsiz'}.",
        })

    # -- Quick Wins (Turkish) -----------------------------------------------
    quick_wins: list[dict[str, str]] = []

    backlog = cov.get("audit_backlog", 0)
    if backlog:
        total_units = max(cov.get("total_units", 1), 1)
        quick_wins.append({
            "aksiyon": f"Bekleyen {min(backlog, 5)} denetimi planla — acil birikimi temizle",
            "efor":    "orta",
            "etki":    f"Kapsam oranını ~%{min(backlog, 5) / total_units:.0%} artırır",
        })

    if repeat_count > 0:
        quick_wins.append({
            "aksiyon": "Tekrarlayan bulgular için kök neden analizi başlat (RCA workshop)",
            "efor":    "yüksek",
            "etki":    "Sistemik kontrol açıklarını kapatır; denetim kültürünü güçlendirir",
        })

    stale = ctrl.get("stale_controls", 0)
    if stale:
        quick_wins.append({
            "aksiyon": f"12 aydan uzun süredir test edilmemiş {stale} kontrolü test et",
            "efor":    "orta",
            "etki":    "Kontrol etkinliğini belgele; potansiyel açıkları erkenden tespit et",
        })

    if audit_health < 50:
        quick_wins.append({
            "aksiyon": "İç Denetim Birimi'nin IIA IPPF standartlarına uyumunu değerlendiren dış kalite değerlendirmesi planla",
            "efor":    "yüksek",
            "etki":    "Denetim fonksiyonunu kurumsal seviyeye taşır",
        })

    # -- Risk-Based Audit Priorities ----------------------------------------
    audit_priorities = repeat_analysis.get("priorities", [])

    # -- LLM Narrative (Turkish) --------------------------------------------
    narrative = _build_rule_based_narrative(
        audit_health, maturity_label, maturity_info["description"],
        fin, ctrl, cov, ctrl_eff_label, ctrl_eff_desc,
        repeat_rate, high_risk_areas,
    )

    try:
        if settings and getattr(settings, "openai_api_key", None):
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.2,
                api_key=settings.openai_api_key,
                max_tokens=500,
            )
            context = {
                "audit_health": audit_health,
                "maturity": maturity_label,
                "total_findings": fin.get("total_findings", 0),
                "open_critical": open_critical,
                "overdue": overdue_findings,
                "repeat_rate_pct": f"{repeat_rate:.0%}",
                "high_risk_areas": high_risk_areas[:3],
                "control_score": round(control_score, 1),
                "ctrl_effectiveness": ctrl_eff_label,
                "ineffective_controls": ineffective,
                "coverage_rate_pct": f"{cov.get('coverage_rate', 0):.0%}",
                "high_risk_coverage_pct": f"{hr_coverage:.0%}",
            }
            system_prompt = (
                "Sen kurumsal iç denetim alanında uzman bir CAE (Chief Audit Executive) asistanısın. "
                "Denetim Komitesi için Türkçe, profesyonel ve aksiyon odaklı bültenler yazıyorsun. "
                "Yanıt SADECE bülten metni olmalı — başlık, madde işareti, açıklama içermemeli."
            )
            human_prompt = (
                f"Aşağıdaki iç denetim verilerine dayanarak Denetim Komitesi için "
                f"4-6 cümlelik Türkçe bir yönetici özeti yaz:\n\n"
                f"Denetim Sağlık Skoru: {context['audit_health']}/100 (IIA Olgunluk: {context['maturity']})\n"
                f"Bulgular: {context['total_findings']} toplam, {context['open_critical']} kritik açık, "
                f"{context['overdue']} gecikmiş\n"
                f"Tekrar bulgu oranı: {context['repeat_rate_pct']}"
                + (f" — riskli alanlar: {', '.join(context['high_risk_areas'])}" if context['high_risk_areas'] else "") + "\n"
                f"Kontrol etkinliği: {context['ctrl_effectiveness']} (skor: {context['control_score']}/100), "
                f"{context['ineffective_controls']} yetersiz kontrol\n"
                f"Denetim evreni kapsamı: {context['coverage_rate_pct']} (yüksek riskli: {context['high_risk_coverage_pct']})\n\n"
                "Özet; mevcut durumu, kritik riskleri ve öncelikli 2-3 aksiyonu içermeli."
            )
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ])
            if response and response.content:
                narrative = response.content.strip()
    except Exception as exc:
        logger.warning("Audit LLM narrative failed: %s", exc)

    # -- Assemble Summary ---------------------------------------------------
    summary = {
        "audit_health_score": audit_health,
        "maturity_level":     maturity_key,
        "maturity_label":     maturity_label,
        "maturity_iia_level": maturity_info["iia_level"],
        "maturity_description": maturity_info["description"],
        "component_scores": {
            "findings": round(findings_score, 1),
            "controls": round(control_score, 1),
            "coverage": round(coverage_score, 1),
        },
        "control_effectiveness":      ctrl_eff_label,
        "control_effectiveness_desc": ctrl_eff_desc,
        "repeat_analysis": {
            "repeat_count":    repeat_count,
            "repeat_rate":     repeat_rate,
            "high_risk_areas": high_risk_areas,
            "top_categories":  repeat_analysis.get("top_categories", []),
        },
        "audit_priorities": audit_priorities,
        "top_issues":  top_issues[:5],
        "quick_wins":  quick_wins[:4],
        "narrative":   narrative,
    }

    logs.append(AuditStepLog(
        node="audit_summary", status="completed",
        message=f"Denetim sağlık skoru: {audit_health}/100 ({maturity_label})",
        metrics={"audit_health_score": audit_health},
    ))

    return {**state, "audit_summary": summary, "logs": logs}


def _build_rule_based_narrative(
    audit_health: float,
    maturity_label: str,
    maturity_desc: str,
    fin: dict[str, Any],
    ctrl: dict[str, Any],
    cov: dict[str, Any],
    ctrl_eff_label: str,
    ctrl_eff_desc: str,
    repeat_rate: float,
    high_risk_areas: list[str],
) -> str:
    open_critical = fin.get("open_critical", 0)
    overdue = fin.get("overdue_count", 0)
    total_findings = fin.get("total_findings", 0)
    coverage_rate = cov.get("coverage_rate", 0.0)
    hr_coverage = cov.get("high_risk_coverage", 1.0)
    ineffective = len(ctrl.get("ineffective_controls", []))

    parts: list[str] = [
        f"İç denetim sağlık skoru {audit_health}/100 olarak hesaplandı; "
        f"IIA olgunluk seviyesi '{maturity_label}' ({maturity_desc}).",
    ]

    if total_findings:
        finding_line = f"Dönem içinde {total_findings} bulgu kayıt altına alındı"
        if open_critical:
            finding_line += f"; bunların {open_critical}'i kritik düzeyde açık"
        if overdue:
            finding_line += f" ve {overdue}'i düzeltme takvimini aştı"
        parts.append(finding_line + ".")

    parts.append(
        f"Kontrol etkinliği '{ctrl_eff_label}' düzeyinde değerlendirildi — {ctrl_eff_desc}"
        + (f" {ineffective} kontrol yeniden tasarım gerektiriyor." if ineffective else "")
    )

    if repeat_rate > 0.10:
        area_str = ", ".join(high_risk_areas[:3]) if high_risk_areas else "çeşitli alanlarda"
        parts.append(
            f"Bulguların %{repeat_rate:.0%}'i tekrarlayan nitelikte ({area_str}); "
            "sistemik kök neden analizi önceliklendirilmeli."
        )

    parts.append(
        f"Denetim evreni kapsamı %{coverage_rate:.0%}"
        + (f" (yüksek riskli birimler: %{hr_coverage:.0%})" if hr_coverage < 1.0 else "")
        + "."
    )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_audit_graph() -> StateGraph:
    builder = StateGraph(AuditState)
    builder.add_node("findings",      node_findings)
    builder.add_node("controls",      node_controls)
    builder.add_node("coverage",      node_coverage)
    builder.add_node("audit_summary", node_audit_summary)

    builder.add_edge("findings",      "controls")
    builder.add_edge("controls",      "coverage")
    builder.add_edge("coverage",      "audit_summary")
    builder.add_edge("audit_summary", END)

    builder.set_entry_point("findings")
    return builder.compile()


_audit_graph = build_audit_graph()


async def run_audit_pipeline(
    findings_csv: str,
    controls_csv: str,
    coverage_csv: str,
    company_name: str | None = None,
    audit_period: str | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """Run the complete Internal Audit pipeline."""
    initial: AuditState = {
        "findings_csv":  findings_csv,
        "controls_csv":  controls_csv,
        "coverage_csv":  coverage_csv,
        "company_name":  company_name,
        "audit_period":  audit_period,
        "findings":      None,
        "controls":      None,
        "coverage":      None,
        "audit_summary": None,
        "logs":          [],
        "error":         None,
    }
    result: AuditState = await _audit_graph.ainvoke(
        initial, config={"configurable": {"settings": settings}}
    )
    return {
        "findings":      result.get("findings"),
        "controls":      result.get("controls"),
        "coverage":      result.get("coverage"),
        "audit_summary": result.get("audit_summary"),
        "logs":          result.get("logs"),
        "error":         result.get("error"),
    }
