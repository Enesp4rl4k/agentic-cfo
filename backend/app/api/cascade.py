"""
Cascade Risk Simulator API

POST /cascade/simulate  — Zincirleme risk simülasyonu
GET  /cascade/triggers  — Desteklenen tetikleyici listesi

Tetikleyici türleri:
  cash_crisis         → runway_months
  revenue_drop        → drop_pct
  key_person_loss     → role
  market_shock        → usd_try_increase_pct, inflation_pct
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request şemaları ──────────────────────────────────────────────────────────

class CashCrisisParams(BaseModel):
    runway_months: float = Field(..., gt=0, le=60, description="Kalan nakit ömrü (ay)")


class RevenueDropParams(BaseModel):
    drop_pct: float = Field(..., gt=0, le=1.0, description="Gelir düşüş oranı (0.0–1.0)")


class KeyPersonLossParams(BaseModel):
    role: Literal["cto", "cfo", "ceo", "cmo", "chro"] = Field(
        ..., description="Ayrılan kişinin rolü"
    )


class MarketShockParams(BaseModel):
    usd_try_increase_pct: float = Field(30.0, ge=0, le=500, description="USD/TRY artış yüzdesi")
    inflation_pct: float = Field(50.0, ge=0, le=200, description="Yıllık enflasyon yüzdesi")


class CascadeSimulateRequest(BaseModel):
    """Cascade simülasyon isteği."""
    trigger: Literal[
        "cash_crisis",
        "revenue_drop",
        "key_person_loss",
        "market_shock",
    ] = Field(..., description="Tetikleyici olay tipi")

    # Bağlam kaynağı — biri sağlanmalı
    job_id: str | None = Field(None, description="CFO analiz job_id'si (şirket verisi için)")
    org_id: str | None = Field(None, description="Org ID (CompanyContext'ten veri çek)")

    # Tetikleyiciye özel parametreler
    cash_crisis:      CashCrisisParams     | None = None
    revenue_drop:     RevenueDropParams    | None = None
    key_person_loss:  KeyPersonLossParams  | None = None
    market_shock:     MarketShockParams    | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _load_context_from_job(
    job_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Job ID'den P&L, cashflow, forecast verisi çek."""
    from app.models.report import Report, ReportFormat  # type: ignore[attr-defined]

    stmt = (
        select(Report)
        .where(Report.job_id == job_id, Report.format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row or not row.content:
        return {}
    try:
        import json
        data = json.loads(row.content) if isinstance(row.content, str) else row.content
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _load_context_from_org(org_id: str) -> dict[str, Any]:
    """CompanyContext'ten agent sonuçlarını yükle."""
    try:
        from app.services.company_context import get_company_context
        ctx = await get_company_context(org_id)
        if not ctx:
            return {}
        results = ctx.get("agent_results") or {}
        return {
            "cfo":  results.get("cfo")  or {},
            "chro": results.get("chro") or {},
            "cto":  results.get("cto")  or {},
            "cmo":  results.get("cmo")  or {},
            "coo":  results.get("coo")  or {},
        }
    except Exception as exc:
        logger.debug("CompanyContext yüklenemedi: %s", exc)
        return {}


# ── Endpoint'ler ───────────────────────────────────────────────────────────────

@router.post("/cascade/simulate")
async def simulate_cascade(
    req: CascadeSimulateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Zincirleme risk simülasyonu.

    Bir tetikleyici olay (nakit krizi, gelir düşüşü vb.) verildiğinde
    tüm C-Suite domain'lerine zincirleme etkisini hesaplar.

    3 senaryo döner: iyimser / baz / kötümser.
    """
    from app.services.cascade_simulator import TriggerType, get_cascade_simulator

    # Veri yükle
    ctx: dict[str, Any] = {}
    if req.job_id:
        report_data = await _load_context_from_job(req.job_id, db)
        ctx = {
            "pnl":      report_data.get("pnl") or {},
            "cashflow": report_data.get("cashflow") or {},
            "forecast": report_data.get("forecast") or {},
        }
    elif req.org_id:
        org_ctx = await _load_context_from_org(req.org_id)
        cfo_r = org_ctx.get("cfo") or {}
        ctx = {
            "pnl":       cfo_r.get("pnl") or {},
            "cashflow":  cfo_r.get("cashflow") or {},
            "forecast":  cfo_r.get("forecast") or {},
            "chro_data": org_ctx.get("chro") or {},
            "cto_data":  org_ctx.get("cto") or {},
            "cmo_data":  org_ctx.get("cmo") or {},
            "coo_data":  org_ctx.get("coo") or {},
        }

    sim = get_cascade_simulator(**ctx)

    # Tetikleyici parametrelerini hazırla
    try:
        trigger = TriggerType(req.trigger)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Geçersiz tetikleyici: {req.trigger}")

    kwargs: dict[str, Any] = {}
    if trigger == TriggerType.CASH_CRISIS:
        if not req.cash_crisis:
            raise HTTPException(status_code=422, detail="cash_crisis parametreleri gerekli")
        kwargs["runway_months"] = req.cash_crisis.runway_months
    elif trigger == TriggerType.REVENUE_DROP:
        if not req.revenue_drop:
            raise HTTPException(status_code=422, detail="revenue_drop parametreleri gerekli")
        kwargs["drop_pct"] = req.revenue_drop.drop_pct
    elif trigger == TriggerType.KEY_PERSON_LOSS:
        if not req.key_person_loss:
            raise HTTPException(status_code=422, detail="key_person_loss parametreleri gerekli")
        kwargs["role"] = req.key_person_loss.role
    elif trigger == TriggerType.MARKET_SHOCK:
        p = req.market_shock or MarketShockParams()
        kwargs["usd_try_increase_pct"] = p.usd_try_increase_pct
        kwargs["inflation_pct"]        = p.inflation_pct

    try:
        result = sim.simulate(trigger, **kwargs)
    except Exception as exc:
        logger.exception("Cascade simülasyon hatası: %s", exc)
        raise HTTPException(status_code=500, detail=f"Simülasyon hatası: {exc}")

    return result.to_dict()


@router.get("/cascade/triggers")
async def list_triggers(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Desteklenen tetikleyici listesi ve parametreleri."""
    return {
        "triggers": [
            {
                "type":        "cash_crisis",
                "label":       "Nakit Krizi",
                "description": "Nakit ömrü kritik eşiğin altına düştüğünde zincirleme etki",
                "params": [
                    {"name": "runway_months", "type": "float", "label": "Kalan Nakit Ömrü (ay)", "default": 2.5},
                ],
            },
            {
                "type":        "revenue_drop",
                "label":       "Gelir Düşüşü",
                "description": "Ani gelir kaybının tüm domainlere etkisi",
                "params": [
                    {"name": "drop_pct", "type": "float", "label": "Düşüş Oranı (0–1)", "default": 0.3},
                ],
            },
            {
                "type":        "key_person_loss",
                "label":       "Kilit Kişi Kaybı",
                "description": "Kritik bir yöneticinin ayrılmasının organizasyona etkisi",
                "params": [
                    {"name": "role", "type": "select", "label": "Rol", "options": ["cto", "cfo", "ceo", "cmo", "chro"]},
                ],
            },
            {
                "type":        "market_shock",
                "label":       "Piyasa Şoku",
                "description": "Kur krizi veya yüksek enflasyonun etkisi",
                "params": [
                    {"name": "usd_try_increase_pct", "type": "float", "label": "USD/TRY Artışı (%)", "default": 30},
                    {"name": "inflation_pct",         "type": "float", "label": "Enflasyon (%)",      "default": 50},
                ],
            },
        ]
    }
