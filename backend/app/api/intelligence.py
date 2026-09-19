"""
Temporal Intelligence + Agent Negotiation API

GET  /temporal/history/{agent}          -- Gecmis analizler
POST /temporal/record                   -- Yeni analiz kaydet
POST /temporal/delta                    -- Delta hesapla
POST /temporal/trends                   -- Trend analizi
GET  /temporal/health-timeline          -- Sirket saglik zaman serisi

POST /negotiation/cash-crisis           -- Nakit krizi protokolu
POST /negotiation/budget-revision       -- Butce revizyon protokolu
POST /negotiation/ask                   -- Tek agent'a soru sor
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_org_id(user: User) -> str:
    org_id = getattr(user, "org_id", None) or getattr(user, "organization_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="Kullanici bir organizasyona bagli degil")
    return str(org_id)


# ── Temporal Request Schemas ──────────────────────────────────────────────────

class RecordAnalysisRequest(BaseModel):
    agent:       str = Field(..., description="cfo|cto|cmo|chro|coo|risk")
    period:      str = Field(..., description="2024-12 veya 2024-Q4")
    period_type: str = Field("monthly", description="monthly|quarterly|weekly")
    metrics:     dict[str, Any]
    narrative:   str = ""
    confidence:  float = Field(0.8, ge=0, le=1)
    data_source: str = "manual"


class DeltaRequest(BaseModel):
    agent:           str
    current_metrics: dict[str, Any]
    current_period:  str = "current"


class TrendRequest(BaseModel):
    agent:   str
    window:  int = Field(6, ge=2, le=24)
    metrics: list[str] | None = None


# ── Temporal Endpoints ────────────────────────────────────────────────────────

@router.get("/temporal/history/{agent}")
async def get_analysis_history(
    agent:        str,
    limit:        int = 12,
    min_confidence: float = 0.5,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Organizasyonun belirli bir agent icin gecmis analizlerini getir.

    DDIA okuma yolu: cache-first (Redis → InMemory → PostgreSQL).
    """
    from app.services.temporal_intelligence import get_temporal_engine

    org_id = _get_org_id(current_user)
    engine = get_temporal_engine(db=db)

    try:
        history = await engine.get_history(
            org_id=org_id, agent=agent, limit=limit, min_confidence=min_confidence
        )
        return {
            "org_id":  org_id,
            "agent":   agent,
            "count":   len(history),
            "events":  [e.to_dict() for e in history],
        }
    except Exception as exc:
        logger.exception("Temporal history hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/temporal/record")
async def record_analysis(
    req:          RecordAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Yeni bir analiz sonucunu immutable event olarak kaydet.

    DDIA: append-only. Ayni donem icin kayit yapilabilir
    (onceki deger degismez, yeni event eklenir).
    """
    from app.services.temporal_intelligence import get_temporal_engine

    org_id = _get_org_id(current_user)
    engine = get_temporal_engine(db=db)

    try:
        event = await engine.record_analysis(
            org_id      = org_id,
            agent       = req.agent,
            period      = req.period,
            metrics     = req.metrics,
            narrative   = req.narrative,
            confidence  = req.confidence,
            data_source = req.data_source,
        )
        return {"data": {"event_id": event.event_id, "recorded_at": event.recorded_at}, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/temporal/delta")
async def compute_delta(
    req:          DeltaRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Mevcut metrikler ile son kayitli analiz arasindaki delta hesapla.
    Hangi metrikler iyilesti, hangileri geriledi?
    """
    from app.services.temporal_intelligence import get_temporal_engine

    org_id = _get_org_id(current_user)
    engine = get_temporal_engine(db=db)

    try:
        delta = await engine.compute_delta(
            org_id          = org_id,
            agent           = req.agent,
            current_metrics = req.current_metrics,
            current_period  = req.current_period,
        )
        if delta is None:
            return {"data": None, "error": "Karsilastirilacak gecmis veri bulunamadi"}
        return {"data": delta.to_dict(), "error": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/temporal/trends")
async def detect_trends(
    req:          TrendRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Son N analizden trend cikar. Her metrik icin:
    rising | falling | stable | volatile + regresyon gucü (R²)
    """
    from app.services.temporal_intelligence import get_temporal_engine

    org_id = _get_org_id(current_user)
    engine = get_temporal_engine(db=db)

    try:
        trends = await engine.detect_trends(
            org_id  = org_id,
            agent   = req.agent,
            window  = req.window,
            metrics = req.metrics,
        )
        return {
            "data": {
                "agent":  req.agent,
                "window": req.window,
                "trends": [
                    {
                        "metric":           t.metric,
                        "trend":            t.trend,
                        "slope":            t.slope,
                        "r_squared":        t.r_squared,
                        "seasonal_pattern": t.seasonal_pattern,
                        "values":           t.values,
                        "periods":          t.periods,
                    }
                    for t in trends
                ],
            },
            "error": None,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/temporal/health-timeline")
async def health_timeline(
    limit:        int = 12,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Tum agent'larin gecmisini birlestirerek sirket saglik zaman serisini donder.
    """
    from app.services.temporal_intelligence import get_temporal_engine

    org_id = _get_org_id(current_user)
    engine = get_temporal_engine(db=db)

    try:
        timeline = await engine.get_health_timeline(org_id=org_id, limit=limit)
        return {"data": {"org_id": org_id, "timeline": timeline}, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Negotiation Request Schemas ───────────────────────────────────────────────

class CashCrisisRequest(BaseModel):
    runway_months: float = Field(..., gt=0, le=60)
    job_id:        str | None = None


class BudgetRevisionRequest(BaseModel):
    cut_target_pct: float = Field(..., gt=0, le=0.5)
    job_id:         str | None = None


class AskAgentRequest(BaseModel):
    to_agent:   str
    query_type: str
    payload:    dict[str, Any] = Field(default_factory=dict)
    timeout:    float = Field(10.0, gt=0, le=30)
    job_id:     str | None = None


# ── Negotiation Endpoints ──────────────────────────────────────────────────────

@router.post("/negotiation/cash-crisis")
async def negotiation_cash_crisis(
    req:          CashCrisisRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Nakit krizi protokolunu baslat.

    CFO nakit kriziyle karsilastiginda tum C-Suite'e paralel soru sorar:
    - CHRO: ise alim plani ertelenebilir mi?
    - CTO: tech butce kesilebilir mi? velocity ne kadar etkiler?
    - CMO: pazarlama butcesi azaltilabilir mi?

    Hepsinin cevabini alarak revize nakit ömrü hesaplar.
    """
    from app.services.agent_negotiation import get_negotiation_session

    org_id  = _get_org_id(current_user)
    session = get_negotiation_session(org_id=org_id, job_id=req.job_id)

    try:
        result = await session.run_cash_crisis_protocol(runway_months=req.runway_months)
        return {"data": result, "error": None}
    except Exception as exc:
        logger.exception("Cash crisis protokol hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/negotiation/budget-revision")
async def negotiation_budget_revision(
    req:          BudgetRevisionRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Butce revizyon protokolunu baslat.

    Hedeflenen tasarruf oranının HR, teknoloji ve gelir uzerindeki
    birlesik etkisini tum agent'lardan toplayarak hesaplar.
    """
    from app.services.agent_negotiation import get_negotiation_session

    org_id  = _get_org_id(current_user)
    session = get_negotiation_session(org_id=org_id, job_id=req.job_id)

    try:
        result = await session.run_budget_revision_protocol(cut_pct=req.cut_target_pct)
        return {"data": result, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/negotiation/ask")
async def negotiation_ask(
    req:          AskAgentRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Tek bir agent'a dogrudan soru sor.

    Genel amacli negotiation endpoint'i.
    from_agent = "user" (kullanici tetikliyor).
    """
    from app.services.agent_bus import get_agent_bus

    org_id = _get_org_id(current_user)
    bus    = get_agent_bus()

    try:
        response = await bus.ask(
            from_agent = "user",
            to_agent   = req.to_agent,
            query_type = req.query_type,
            payload    = req.payload,
            org_id     = org_id,
            job_id     = req.job_id,
            timeout    = req.timeout,
        )
        if response:
            return {"data": {"response": response.payload, "from_agent": response.from_agent}, "error": None}
        else:
            return {"data": None, "error": f"Agent '{req.to_agent}' yanit vermedi (timeout {req.timeout}s)"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/negotiation/agents")
async def list_negotiable_agents(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Negotiation destekleyen agent'lar ve destekledikleri query tipleri."""
    from app.services.agent_bus import QueryType

    return {
        "agents": {
            "cfo":  {
                "label":    "CFO Agent",
                "queries":  [QueryType.HIRING_PLAN, QueryType.TECH_BUDGET_CUT, QueryType.MARKETING_ROI],
                "protocols": ["cash_crisis", "budget_revision"],
            },
            "chro": {
                "label":   "CHRO Agent",
                "queries": [QueryType.HIRING_PLAN, QueryType.SALARY_FORECAST, QueryType.ATTRITION_RISK],
            },
            "cto":  {
                "label":   "CTO Agent",
                "queries": [QueryType.TECH_BUDGET_CUT, QueryType.VELOCITY_IMPACT, QueryType.CLOUD_SAVINGS],
            },
            "cmo":  {
                "label":   "CMO Agent",
                "queries": [QueryType.MARKETING_ROI, QueryType.CAC_TREND, QueryType.REVENUE_FORECAST],
            },
        },
        "protocols": [
            {
                "id":          "cash_crisis",
                "label":       "Nakit Krizi Protokolu",
                "description": "Nakit ömrü kritik oldugunda tüm C-Suite ile revize senaryo muzakeresi",
                "endpoint":    "/negotiation/cash-crisis",
            },
            {
                "id":          "budget_revision",
                "label":       "Butce Revizyon Protokolu",
                "description": "Hedeflenen tasarrufun tüm domainlere birleşik etkisi",
                "endpoint":    "/negotiation/budget-revision",
            },
        ],
    }
