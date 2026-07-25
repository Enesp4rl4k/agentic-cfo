"""
Chat API — POST /chat/{job_id}        CFO chat (finansal veriler)
           POST /chat/ceo             CEO chat (CEO/CTO pipeline sonuçları)

Finansal + teknoloji verileri üzerinde doğal dil soru-cevap.
Streaming ve tek seferlik iki mod desteklenir.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.report import Report, ReportFormat
from app.models.transaction import Transaction

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    stream: bool = False
    conversation_history: list[dict] = []


class CEOChatRequest(BaseModel):
    question: str
    stream: bool = False
    conversation_history: list[dict] = []
    # Direct pipeline results (from prior CEO/CTO analyze calls)
    ceo_result: dict[str, Any] | None = None
    cto_result: dict[str, Any] | None = None
    # Optional: also include CFO job context
    job_id: str | None = None


@router.post("/chat/job/{job_id}")
async def chat(
    job_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> dict | StreamingResponse:
    """
    Ask a financial question about a completed analysis job.
    Set stream=true for streaming SSE response.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job must be completed to use chat. Status: {job.status}",
        )

    # Load dashboard JSON
    report_result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = report_result.scalars().first()
    if not report or not report.data:
        raise HTTPException(
            status_code=404,
            detail="Dashboard data not found. Ensure analysis is complete.",
        )

    # Load recent transactions
    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.job_id == job_id)
        .order_by(Transaction.transaction_date.desc())
        .limit(100)
    )
    txs = tx_result.scalars().all()
    tx_dicts = [
        {
            "amount_cents": tx.amount_kurus,
            "type": tx.type,
            "category": tx.category,
            "description": tx.description,
            "vendor": tx.vendor,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
        }
        for tx in txs
    ]

    from app.agents.chat_agent import chat_with_cfo, stream_chat_with_cfo

    if body.stream:
        async def _generate():
            async for chunk in stream_chat_with_cfo(
                question=body.question,
                dashboard=report.data,
                transactions=tx_dicts,
                conversation_history=body.conversation_history,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming
    answer = await chat_with_cfo(
        question=body.question,
        dashboard=report.data,
        transactions=tx_dicts,
        conversation_history=body.conversation_history,
    )
    return {"data": {"answer": answer, "job_id": job_id}, "error": None}


@router.post("/chat/ceo")
# NOTE: /chat/job/{job_id} uses explicit /job/ prefix to avoid clashing with /chat/ceo
async def chat_ceo(
    body: CEOChatRequest,
    db: AsyncSession = Depends(get_db),
) -> dict | StreamingResponse:
    """
    CEO-level strategic chat.

    Accepts CEO pipeline results (cross_risks, strategic_priorities, board_deck)
    and/or CTO pipeline results directly in the request body.

    Optionally also loads a CFO job's dashboard for financial context.

    Example questions:
      - "What are our top 3 cross-domain risks?"
      - "How does our tech debt affect cash runway?"
      - "What should I present to the board this quarter?"
      - "En acil 2 aksiyon item'imiz nedir?"
    """
    from app.agents.chat_agent import chat_with_ceo, stream_chat_with_ceo

    if not body.ceo_result and not body.cto_result and not body.job_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide at least one of: ceo_result, cto_result, or job_id. "
                "Run /ceo/analyze or /cto/analyze first, then pass the result here."
            ),
        )

    # Optionally load CFO dashboard from DB
    dashboard: dict[str, Any] | None = None
    tx_dicts: list[dict[str, Any]] = []

    if body.job_id:
        job = await db.get(AnalysisJob, body.job_id)
        if job and job.status == JobStatus.COMPLETED:
            report_result = await db.execute(
                select(Report).where(
                    Report.job_id == body.job_id,
                    Report.report_format == ReportFormat.JSON,
                )
            )
            report = report_result.scalars().first()
            if report and report.data:
                dashboard = report.data

            tx_result = await db.execute(
                select(Transaction)
                .where(Transaction.job_id == body.job_id)
                .order_by(Transaction.transaction_date.desc())
                .limit(50)
            )
            txs = tx_result.scalars().all()
            tx_dicts = [
                {
                    "amount_cents": tx.amount_kurus,
                    "type": tx.type,
                    "category": tx.category,
                    "description": tx.description,
                    "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                }
                for tx in txs
            ]

    if body.stream:
        async def _generate():
            async for chunk in stream_chat_with_ceo(
                question=body.question,
                ceo_result=body.ceo_result,
                cto_result=body.cto_result,
                dashboard=dashboard,
                transactions=tx_dicts,
                conversation_history=body.conversation_history,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    answer = await chat_with_ceo(
        question=body.question,
        ceo_result=body.ceo_result,
        cto_result=body.cto_result,
        dashboard=dashboard,
        transactions=tx_dicts,
        conversation_history=body.conversation_history,
    )
    return {"data": {"answer": answer}, "error": None}


# ── NL Query Engine — Phase 6.1 ──────────────────────────────────────────────

class NLQueryRequest(BaseModel):
    query: str
    job_id: str


@router.post("/query")
async def natural_language_query(
    body: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Natural language query engine — Türkçe/İngilizce soru → yapılandırılmış yanıt.

    Mevcut chat endpoint'inden farkı:
    - Önce kural tabanlı intent classification yapar (LLM maliyeti olmadan)
    - Metrik değerini doğrudan dashboard JSON'dan çeker
    - LLM yalnızca açıklama + takip soruları için çağrılır
    - Her yanıt follow_up sorular içerir

    Örnekler:
      "Nakit akışım ne?"         → cashflow.net_change + yorum
      "En pahalı gider nedir?"   → opex karşılaştırması
      "Paramız ne zaman biter?"  → runway_query + monte carlo riski
      "Tahmin nedir?"            → 3 senaryo + P10/P50/P90
    """
    from sqlalchemy import desc as sa_desc

    from app.agents.nl_query_engine import execute_nl_query, generate_nl_insight
    from app.config import get_settings

    # Load dashboard JSON
    report_result = await db.execute(
        select(Report)
        .where(Report.job_id == body.job_id, Report.report_format == ReportFormat.JSON)
        .order_by(sa_desc(Report.created_at))
        .limit(1)
    )
    report = report_result.scalar_one_or_none()
    if not report or not report.data:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{body.job_id}' için analiz verisi bulunamadı.",
        )

    dashboard = report.data

    # Load recent transactions
    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.job_id == body.job_id)
        .limit(50)
    )
    txs = tx_result.scalars().all()
    tx_dicts = [
        {
            "id": str(t.id),
            "amount_cents": t.amount_kurus,
            "type": t.type,
            "category": t.category,
            "description": t.description,
            "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
        }
        for t in txs
    ]

    # Execute NL query (rule-based, fast)
    query_result = execute_nl_query(
        query=body.query,
        dashboard=dashboard,
        transactions=tx_dicts,
    )

    # Generate Turkish insight with LLM
    settings = get_settings()
    result = await generate_nl_insight(
        query=body.query,
        query_result=query_result,
        dashboard=dashboard,
        transactions=tx_dicts,
        settings=settings,
    )

    return {
        "data": {
            "query":      body.query,
            "intent":     result["intent"],
            "answer":     result["answer"],
            "follow_ups": result["follow_ups"],
            "value":      result.get("value"),
        },
        "error": None,
    }
