"""
Risk Agent API Endpoints

POST /risk/analyze   — Run full Risk pipeline (register, losses, KRIs)
POST /risk/cascade   — Cascade Risk Simulator: "what if X happens?" → all domains
GET  /risk/health-check — Service health
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.risk.orchestrator import run_risk_pipeline
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


class RiskAnalyzeRequest(BaseModel):
    register_csv: str = ""
    loss_csv: str = ""
    kri_csv: str = ""
    company_name: str | None = None
    reporting_period: str | None = None


# ── Cascade Simulator ─────────────────────────────────────────────────────────

class CascadeRequest(BaseModel):
    """
    Trigger event that starts the cascade simulation.
    At least one of the financial fields should be provided
    so the simulator can project realistic downstream effects.
    """
    trigger_type: str          # e.g. "cash_crisis", "revenue_drop", "key_person_loss", "cyber_incident", "custom"
    trigger_description: str   # Human-readable description of the trigger
    severity: str = "high"     # "low" | "medium" | "high" | "critical"

    # Optional financial context (from CompanyContext / CFO result)
    monthly_burn_rate: float | None = None   # TRY / month
    monthly_revenue: float | None = None     # TRY / month
    cash_runway_months: float | None = None  # Current runway
    headcount: int | None = None
    company_name: str | None = None
    reporting_period: str | None = None


class DomainImpact(BaseModel):
    domain: str
    impact_level: str          # "none" | "low" | "medium" | "high" | "critical"
    impact_score: int          # 0-100
    primary_effect: str        # Short description
    secondary_effects: list[str]
    recommended_actions: list[str]
    time_to_impact_weeks: int  # How quickly this domain feels the effect


class CascadeResult(BaseModel):
    simulation_id: str
    trigger_type: str
    trigger_description: str
    severity: str
    overall_risk_score: int    # 0-100
    overall_risk_level: str    # "low" | "medium" | "high" | "critical"
    executive_summary: str
    domain_impacts: list[DomainImpact]
    cascade_sequence: list[str]   # Ordered list of "domain → effect" steps
    recommended_priorities: list[str]
    estimated_recovery_weeks: int


def _severity_multiplier(severity: str) -> float:
    return {"low": 0.3, "medium": 0.6, "high": 0.85, "critical": 1.0}.get(severity, 0.85)


def _impact_level(score: int) -> str:
    if score >= 80: return "critical"
    if score >= 60: return "high"
    if score >= 35: return "medium"
    if score >= 10: return "low"
    return "none"


def _simulate_cascade(req: CascadeRequest) -> CascadeResult:
    """
    Rule-based cascade simulator.
    Uses the trigger type + financial context to project domain-level impacts.
    Each domain impact is scored 0-100 based on the trigger severity and context.
    """
    sim_id = str(uuid.uuid4())[:8]
    mult = _severity_multiplier(req.severity)

    # ── Domain impact templates per trigger type ──────────────────────────────

    if req.trigger_type == "cash_crisis":
        runway = req.cash_runway_months or 3.0
        burn = req.monthly_burn_rate or 1_000_000
        tension = max(0, 1 - (runway / 12))  # More tension as runway shrinks

        domains = [
            DomainImpact(
                domain="CFO / Finance",
                impact_level=_impact_level(int(85 * mult)),
                impact_score=int(85 * mult),
                primary_effect=f"Nakit {runway:.1f} aylık çalışma süresi — acil likidite yönetimi gerekli",
                secondary_effects=[
                    "Kredi limitleri baskı altında",
                    f"Aylık burn rate: {burn:,.0f} TRY",
                    "Vadesi gelen borçlarda gecikme riski",
                ],
                recommended_actions=[
                    "Hemen alacak tahsilatını hızlandır",
                    "Ertelenebilir harcamaları dondur",
                    "Acil kredi/yatırımcı görüşmeleri başlat",
                ],
                time_to_impact_weeks=1,
            ),
            DomainImpact(
                domain="CHRO / People",
                impact_level=_impact_level(int((55 + tension * 30) * mult)),
                impact_score=int((55 + tension * 30) * mult),
                primary_effect="İşe alım dondurulur, attrition riski yükselir",
                secondary_effects=[
                    "Kritik çalışanlar teklif arayışına girebilir",
                    "Maaş gecikmesi ihtimali morale zarar verir",
                    "Yetenek kaybı operasyonel kapasiteyi düşürür",
                ],
                recommended_actions=[
                    "Kilit çalışanlarla şeffaf iletişim kur",
                    "Retention paketi için öncelik belirle",
                    "Yeni işe alımları geçici olarak dondur",
                ],
                time_to_impact_weeks=int(2 + runway),
            ),
            DomainImpact(
                domain="CTO / Technology",
                impact_level=_impact_level(int(45 * mult)),
                impact_score=int(45 * mult),
                primary_effect="Teknik borç birikir, yeni geliştirmeler yavaşlar",
                secondary_effects=[
                    "Bulut/altyapı harcamaları kısılır",
                    "Lisans yenilemelerinde risk",
                    "Mühendis motivasyonu düşer",
                ],
                recommended_actions=[
                    "Kritik olmayan projeleri ertele",
                    "Bulut maliyetlerini optimize et",
                    "Teknik ekibe roadmap şeffaflığı sağla",
                ],
                time_to_impact_weeks=4,
            ),
            DomainImpact(
                domain="CMO / Marketing",
                impact_level=_impact_level(int(60 * mult)),
                impact_score=int(60 * mult),
                primary_effect="Marketing bütçesi kesilir, büyüme yavaşlar",
                secondary_effects=[
                    "CAC (müşteri edinme maliyeti) artar",
                    "Pipeline daralır, gelecek gelir düşer",
                    "Marka bilinirliği yatırımı durur",
                ],
                recommended_actions=[
                    "En yüksek ROI kanallara odaklan",
                    "Organik büyümeye geç",
                    "Mevcut müşteri genişletmesine öncelik ver",
                ],
                time_to_impact_weeks=3,
            ),
            DomainImpact(
                domain="COO / Operations",
                impact_level=_impact_level(int(40 * mult)),
                impact_score=int(40 * mult),
                primary_effect="Operasyonel verimlilik düşer, tedarikçi ilişkileri gerilir",
                secondary_effects=[
                    "Tedarikçi ödemelerinde gecikme",
                    "SLA ihlalleri artabilir",
                    "Süreç iyileştirme yatırımları durur",
                ],
                recommended_actions=[
                    "Kritik tedarikçilerle erken iletişim",
                    "En karlı süreçlere odaklan",
                    "Manuel süreçleri geçici olarak kabul et",
                ],
                time_to_impact_weeks=3,
            ),
            DomainImpact(
                domain="Risk / Compliance",
                impact_level=_impact_level(int(70 * mult)),
                impact_score=int(70 * mult),
                primary_effect="Operasyonel ve düzenleyici risk artar",
                secondary_effects=[
                    "Uyum harcamaları ertelenebilir ama risk birikir",
                    "Sigorta ve denetim maliyetleri artabilir",
                    "Düzenleyici ceza riski",
                ],
                recommended_actions=[
                    "Zorunlu uyum aktivitelerini belirle ve koru",
                    "Hukuk danışmanlığından öncelik al",
                    "Risk kayıt defterini güncelle",
                ],
                time_to_impact_weeks=2,
            ),
        ]
        cascade_seq = [
            "CFO: Nakit kriz tetiklendi → Harcama dondurma kararı",
            "CMO: Marketing bütçesi kesildi → Pipeline daralması başlıyor",
            "CHRO: İşe alım durduruldu → Mevcut ekip baskı altına giriyor",
            "CTO: Yatırımlar ertelendi → Teknik borç birikiyor",
            "COO: Tedarikçi ödemeleri gecikmesi → SLA riski",
            "Risk: Operasyonel riskler uyum boşluklarıyla buluşuyor",
        ]
        exec_summary = (
            f"Nakit krizi senaryosu: {runway:.1f} aylık mevcut runway ile şirket, "
            f"tüm domainlerde zincirleme etkiler yaşıyor. "
            f"En kritik: CMO büyüme durması ve CHRO yetenek kaybı riski."
        )
        recovery_weeks = int(max(8, runway * 4))

    elif req.trigger_type == "revenue_drop":
        drop_pct = 0.3 * mult

        domains = [
            DomainImpact(
                domain="CFO / Finance",
                impact_level=_impact_level(int(75 * mult)),
                impact_score=int(75 * mult),
                primary_effect=f"Gelirde tahmini %{int(drop_pct*100)} düşüş — nakit akışı bozuluyor",
                secondary_effects=["Bütçe revizyonu gerekli", "Profitability hedefleri kaçırılabilir"],
                recommended_actions=["Gelir tahminini revize et", "Gider kısma planı hazırla"],
                time_to_impact_weeks=2,
            ),
            DomainImpact(
                domain="CMO / Marketing",
                impact_level=_impact_level(int(80 * mult)),
                impact_score=int(80 * mult),
                primary_effect="Satış pipeline'ı ve conversion oranları incelenmeli",
                secondary_effects=["Churn artışı mümkün", "CAC/LTV dengesizleşiyor"],
                recommended_actions=["Churn analizi yap", "Retention kampanyaları başlat"],
                time_to_impact_weeks=1,
            ),
            DomainImpact(
                domain="COO / Operations",
                impact_level=_impact_level(int(35 * mult)),
                impact_score=int(35 * mult),
                primary_effect="Kapasite planlaması revize edilmeli",
                secondary_effects=["Üretim/teslimat planları bozulabilir"],
                recommended_actions=["Esnek kapasite modeline geç"],
                time_to_impact_weeks=4,
            ),
            DomainImpact(
                domain="CHRO / People",
                impact_level=_impact_level(int(40 * mult)),
                impact_score=int(40 * mult),
                primary_effect="İşe alım planları tehlikeye giriyor",
                secondary_effects=["Komisyon/prim hedefleri kaçırılabilir", "Satış ekibi motivasyonu düşer"],
                recommended_actions=["Satış ekibiyle şeffaf iletişim", "OKR revizyonu"],
                time_to_impact_weeks=3,
            ),
            DomainImpact(
                domain="CTO / Technology",
                impact_level=_impact_level(int(25 * mult)),
                impact_score=int(25 * mult),
                primary_effect="Ürün yatırımları yavaşlayabilir",
                secondary_effects=["Feature roadmap ertelenebilir"],
                recommended_actions=["Kritik müşteri ihtiyaçlarına odaklan"],
                time_to_impact_weeks=6,
            ),
            DomainImpact(
                domain="Risk / Compliance",
                impact_level=_impact_level(int(45 * mult)),
                impact_score=int(45 * mult),
                primary_effect="Gelir düşüşü regülasyon ve sözleşme risklerini artırır",
                secondary_effects=["Sözleşme taahhütleri tutturulamayabilir"],
                recommended_actions=["Sözleşme yükümlülüklerini gözden geçir"],
                time_to_impact_weeks=3,
            ),
        ]
        cascade_seq = [
            "CMO: Gelir düşüşü tespit edildi → Churn analizi başlıyor",
            "CFO: Nakit akışı projeksiyonu revize edildi → Bütçe baskısı",
            "CHRO: Komisyon/prim planları tehlikede → Motivasyon riski",
            "COO: Kapasite planı revize gerekiyor → Operasyonel uyarlama",
            "CTO: Yatırım öncelikleri değişiyor → Roadmap revizyonu",
        ]
        exec_summary = f"Gelir düşüşü senaryosu: %{int(drop_pct*100)} gelir kaybı beklentisiyle CMO ve CFO en hızlı etkileniyor."
        recovery_weeks = 12

    else:
        # Generic / custom trigger
        base_score = int(50 * mult)
        domains = [
            DomainImpact(
                domain=d,
                impact_level=_impact_level(base_score + offset),
                impact_score=base_score + offset,
                primary_effect=f"{req.trigger_description} — {d} domainine etki",
                secondary_effects=["İkincil etkiler analiz edilmeli"],
                recommended_actions=["Acil değerlendirme yapın", "Domain liderini devreye alın"],
                time_to_impact_weeks=2 + i,
            )
            for i, (d, offset) in enumerate([
                ("CFO / Finance", 20), ("Risk / Compliance", 15),
                ("COO / Operations", 5), ("CHRO / People", 0),
                ("CTO / Technology", -5), ("CMO / Marketing", -10),
            ])
        ]
        cascade_seq = [f"{req.trigger_description} → Tüm domainler etkileniyor"]
        exec_summary = f"Özel senaryo: {req.trigger_description}. Kapsamlı etki analizi yapılması önerilir."
        recovery_weeks = 16

    overall_score = max(d.impact_score for d in domains)
    priorities = [
        f"#{i+1} {d.domain}: {d.recommended_actions[0]}"
        for i, d in enumerate(sorted(domains, key=lambda x: x.impact_score, reverse=True)[:3])
    ]

    return CascadeResult(
        simulation_id=sim_id,
        trigger_type=req.trigger_type,
        trigger_description=req.trigger_description,
        severity=req.severity,
        overall_risk_score=overall_score,
        overall_risk_level=_impact_level(overall_score),
        executive_summary=exec_summary,
        domain_impacts=sorted(domains, key=lambda x: x.impact_score, reverse=True),
        cascade_sequence=cascade_seq,
        recommended_priorities=priorities,
        estimated_recovery_weeks=recovery_weeks,
    )


@router.post("/risk/cascade")
async def run_cascade_simulation(body: CascadeRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    Cascade Risk Simulator — "What if X happens?" → all domain impacts.

    Given a trigger event (cash crisis, revenue drop, cyber incident, etc.),
    simulates the knock-on effects across CFO, CHRO, CTO, CMO, COO, Risk domains.
    """
    try:
        result = _simulate_cascade(body)
        return {
            "data": result.model_dump(),
            "error": None,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cascade simulation failed: {exc}")


@router.post("/risk/analyze")
async def run_risk_analysis(
    body: RiskAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Run full Risk pipeline synchronously.
    Returns: { job_id, register, losses, kris, risk_summary, logs, error }
    """
    try:
        job_id = str(uuid.uuid4())
        result = await run_risk_pipeline(
            register_csv=body.register_csv,
            loss_csv=body.loss_csv,
            kri_csv=body.kri_csv,
            company_name=body.company_name,
            reporting_period=body.reporting_period,
        )

        if current_user.org_id and not result.get("error"):
            try:
                from app.agents.orchestration.auto_chain import on_agent_complete
                from app.services.context_persist import persist_agent_completion

                await persist_agent_completion(
                    str(current_user.org_id),
                    "risk",
                    dict(result),
                    db,
                    job_id=job_id,
                    company_name=body.company_name,
                    reporting_period=body.reporting_period,
                    auto_chain_hook=on_agent_complete,
                )
            except Exception as exc:
                logger.warning("Risk context persist failed: %s", exc)

        logs_serializable = [
            {
                "node":    log.node,
                "status":  log.status,
                "message": log.message,
                "metrics": log.metrics,
            }
            for log in (result.get("logs") or [])
        ]

        return {
            "job_id":       job_id,
            "register":     result.get("register"),
            "losses":       result.get("losses"),
            "kris":         result.get("kris"),
            "risk_summary": result.get("risk_summary"),
            "logs":         logs_serializable,
            "error":        result.get("error"),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Risk analysis failed: {exc}")


@router.get("/risk/health-check")
async def risk_health(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "risk",
        "capabilities": [
            "risk_register_scoring",
            "loss_event_tracking",
            "kri_threshold_monitoring",
            "enterprise_risk_posture",
        ],
    }
