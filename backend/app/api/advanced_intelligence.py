"""
Advanced Intelligence API

POST /advanced/nl-simulate         -- NL sorgu → simulasyon
POST /advanced/proactive-scan      -- Manuel KRI tarama ve alert tetikleme
GET  /advanced/alert-history       -- Proaktif alert gecmisi
POST /advanced/board-deck-pdf      -- CEO board deck PDF export
POST /advanced/temporal/auto-record -- CFO analizini otomatik temporal kayit
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_org_id(user: User) -> str:
    org_id = getattr(user, "org_id", None) or getattr(user, "organization_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="Kullanici bir organizasyona bagli degil")
    return str(org_id)


def _assemble_board_deck(
    dashboard: dict[str, Any],
    *,
    company_name: str,
    period: str,
    include_swot: bool = True,
    include_kri: bool = True,
) -> dict[str, Any]:
    """Build a BoardDeckPDFBuilder-shaped deck dict from a CFO dashboard JSON.

    Reuses the same deck assembly as the TR vertical — the dashboard JSON has
    the `pnl` / `forecast` / `anomalies` keys `_board_deck_from` reads.
    """
    from app.agents.tr_vertical import _board_deck_from

    deck = _board_deck_from(company_name, period, dashboard or {}, None)
    if include_swot and "swot" not in deck:
        deck["swot"] = (dashboard or {}).get("swot") or {}
    if not include_kri:
        deck.pop("kri_posture", None)
    return deck


# ── NL Simulation ──────────────────────────────────────────────────────────────

class NLSimulateRequest(BaseModel):
    query:   str = Field(..., description="Dogal dil simulasyon sorusu")
    job_id:  str | None = None
    context: dict[str, Any] | None = None


@router.post("/advanced/nl-simulate")
async def nl_simulate(
    req:          NLSimulateRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Dogal dil sorgusu → simulasyon motoru.

    Ornek sorgular:
    - "5 muhendis isse alırsam 12 ayda ne olur?"
    - "Nakit 3 ayda biterse ne olur?"
    - "Pazarlama butcesini 2 katina cikarsak?"
    - "Giderleri %20 azaltırsak?"

    Bridge sorguyu otomatik sınıflandirir, parametreleri cikarir,
    uygun simulasyon motorunu calistirir ve Turkce yanit dondurur.
    """
    from app.services.nl_simulation_bridge import get_nl_simulation_bridge

    org_id = _get_org_id(current_user)
    bridge = get_nl_simulation_bridge()

    try:
        result = await bridge.process(
            query   = req.query,
            org_id  = org_id,
            job_id  = req.job_id,
            context = req.context,
        )
        return {
            "ok":                  result.error is None,
            "simulation_type":     result.simulation_type,
            "intent_confidence":   result.intent_confidence,
            "extracted_params":    result.extracted_params,
            "answer":              result.answer,
            "simulation_result":   result.simulation_result,
            "follow_up_questions": result.follow_up_questions,
            "error":               result.error,
        }
    except Exception as exc:
        logger.exception("NL simulate hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Proactive Alerts ────────────────────────────────────────────────────────────

@router.post("/advanced/proactive-scan")
async def proactive_scan(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Manuel KRI tarama ve alert tetikleme.
    Normalde scheduler calistirir; test ve debug icin manuel tetikleme.
    """
    from app.agents.orchestration.proactive_alerts import get_proactive_orchestrator

    org_id       = _get_org_id(current_user)
    orchestrator = get_proactive_orchestrator(db=db)

    try:
        result = await orchestrator.scan_and_alert(org_id=org_id)
        return {"data": {"org_id": org_id, **result}, "error": None}
    except Exception as exc:
        logger.exception("Proactive scan hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/advanced/alert-history")
async def get_alert_history(
    limit:        int = 20,
    severity:     str | None = None,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Son proaktif alertleri listele."""
    from sqlalchemy import text

    org_id = _get_org_id(current_user)

    try:
        query = """
            SELECT alert_id, trigger, severity, title, body,
                   channels, created_at, dispatched
            FROM proactive_alerts
            WHERE org_id = :org_id
        """
        params: dict[str, Any] = {"org_id": org_id}

        if severity:
            query += " AND severity = :severity"
            params["severity"] = severity

        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        result = await db.execute(text(query), params)
        rows   = result.fetchall()

        import json
        alerts = [
            {
                "alert_id":   row.alert_id,
                "trigger":    row.trigger,
                "severity":   row.severity,
                "title":      row.title,
                "body":       row.body[:200] + "..." if len(row.body or "") > 200 else row.body,
                "channels":   json.loads(row.channels) if row.channels else [],
                "created_at": row.created_at,
                "dispatched": row.dispatched,
            }
            for row in rows
        ]
        return {"data": {"alerts": alerts, "count": len(alerts)}, "error": None}

    except Exception as exc:
        # Tablo henuz yoksa bos dondur
        logger.debug("Alert history hatasi (table may not exist): %s", exc)
        return {"data": {"alerts": [], "count": 0}, "error": None}


# ── Board Deck PDF ─────────────────────────────────────────────────────────────

class BoardDeckPDFRequest(BaseModel):
    job_id:       str | None = None
    org_id_param: str | None = None
    company_name: str | None = None
    period:       str | None = None
    include_swot:     bool = True
    include_kri:      bool = True
    include_cascade:  bool = False


@router.post("/advanced/board-deck-pdf")
async def board_deck_pdf(
    req:          BoardDeckPDFRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    CEO board deck + SWOT + KRI + Cross-domain insights → PDF.

    Dosya tarayicida dogrudan indirilir.
    """
    org_id = _get_org_id(current_user)

    try:
        from app.api.reports_pdf import _load_dashboard_for_job
        from app.services.board_deck_pdf import BoardDeckPDFBuilder

        dashboard = await _load_dashboard_for_job(req.job_id, db) if req.job_id else {}
        deck = _assemble_board_deck(
            dashboard,
            company_name=req.company_name or "Şirket",
            period=req.period or "",
            include_swot=req.include_swot,
            include_kri=req.include_kri,
        )
        pdf_bytes = BoardDeckPDFBuilder().build_pdf(deck)
        filename = f"board-deck-{org_id[:8]}.pdf"
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type = "application/pdf",
            headers    = {
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length":      str(len(pdf_bytes)),
            },
        )
    except Exception as exc:
        logger.exception("Board deck PDF hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Temporal Auto-record ──────────────────────────────────────────────────────

class TemporalAutoRecordRequest(BaseModel):
    agent:      str = Field(..., description="cfo|cto|cmo|chro|coo|risk")
    period:     str = Field(..., description="2024-12 veya 2024-Q4")
    job_id:     str | None = None
    data_source: str = "manual"


@router.post("/advanced/temporal/auto-record")
async def temporal_auto_record(
    req:          TemporalAutoRecordRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    CompanyContext'teki mevcut agent sonucunu temporal log'a otomatik kaydet.
    Her analiz sonrasinda cagirilmasi onerilir.
    """
    from app.services.company_context import get_company_context
    from app.services.temporal_intelligence import get_temporal_engine

    org_id = _get_org_id(current_user)

    try:
        ctx     = await get_company_context(org_id) or {}
        results = ctx.get("agent_results") or {}
        cfo_r   = results.get("cfo") if req.agent == "cfo" else results.get(req.agent) or {}

        # Agent bazinda metrik cikarimi
        metrics: dict[str, Any] = {}
        if req.agent == "cfo" and cfo_r:
            pnl      = cfo_r.get("pnl") or {}
            cashflow = cfo_r.get("cashflow") or {}
            forecast = cfo_r.get("forecast") or {}
            base_sc  = (forecast.get("scenarios") or {}).get("base") or {}
            metrics  = {
                "revenue":       pnl.get("revenue", 0),
                "net_margin":    pnl.get("net_margin", 0),
                "gross_margin":  pnl.get("gross_margin", 0),
                "runway_months": base_sc.get("runway_months"),
                "net_change":    cashflow.get("net_change", 0),
            }
        else:
            metrics = {k: v for k, v in (cfo_r or {}).items() if isinstance(v, (int, float))}

        if not metrics:
            return {"ok": False, "reason": f"{req.agent} icin metrik bulunamadi"}

        engine = get_temporal_engine(db=db)
        event  = await engine.record_analysis(
            org_id      = org_id,
            agent       = req.agent,
            period      = req.period,
            metrics     = metrics,
            confidence  = 0.85,
            data_source = req.data_source,
        )
        return {"ok": True, "event_id": event.event_id, "metrics_recorded": len(metrics)}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
