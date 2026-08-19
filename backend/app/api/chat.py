"""
Chat API — POST /chat/job/{job_id}    CFO chat (finansal veriler)
           POST /chat/ceo             CEO chat (CEO/CTO pipeline sonuçları)
           POST /chat/agent           Universal agent chat (tüm CompanyContext)

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
from app.api.auth import get_current_user
from app.models.user import User
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


# ── Universal Agent Chat — CompanyContext aware ───────────────────────────────

class AgentChatRequest(BaseModel):
    """
    Universal chat request — any C-Suite agent can answer.

    The backend loads the org's CompanyContext and builds a rich system prompt
    including all available agent results (CFO, CTO, CMO, COO, CHRO, Risk, etc.)
    so the model can answer cross-domain questions.

    agent_filter: if set, focuses the system prompt on that agent's data only.
    E.g. "cto" → only CTO data in context; "all" → full company context.

    session_id: optional client-provided session identifier for conversation
    continuity. If omitted, a daily session is auto-generated per user.

    use_reasoning: if True, runs the Think→Plan→Act reasoning loop before
    generating the final answer. Higher quality but ~2-3x slower.
    Recommended for complex multi-step questions.
    """
    question: str
    agent_filter: str = "all"   # "all" | "cfo" | "cto" | "cmo" | "coo" | "chro" | "risk" | "audit"
    conversation_history: list[dict] = []   # kept for backwards compat (client-side fallback)
    session_id: str | None = None           # server-side session identifier
    stream: bool = False
    use_reasoning: bool = False             # AGENT-3: Think→Plan→Act loop


def _build_agent_system_prompt(
    agent_filter: str,
    ctx_data: dict[str, Any],
    company_name: str | None,
) -> str:
    """
    Build a rich system prompt from CompanyContext data.
    Includes all agent results that are available.
    """
    company = company_name or "Şirket"
    lines = [
        f"Sen {company} şirketinin C-Suite AI danışmanısın.",
        "Aşağıdaki analiz sonuçlarına dayanarak Türkçe veya İngilizce (soruya göre) yanıt ver.",
        "Somut veriler ve sayılar kullan. Muğlak cevaplar verme.",
        "Her yanıtta 1–3 somut öneri sun.",
        "",
    ]

    # CFO / Financial data
    cfo = ctx_data.get("last_cfo_result")
    if cfo and agent_filter in ("all", "cfo"):
        pnl = cfo.get("pnl", {})
        cashflow = cfo.get("cashflow", {})
        forecast = cfo.get("forecast", {})
        lines += [
            "=== CFO — FİNANSAL DURUM ===",
            f"Gelir: {pnl.get('revenue', 0):,.0f} TRY",
            f"Brüt Marj: {pnl.get('gross_margin', 0)*100:.1f}%",
            f"Net Marj: {pnl.get('net_margin', 0)*100:.1f}%",
            f"FAVÖK: {pnl.get('ebitda', 0):,.0f} TRY ({pnl.get('ebitda_margin', 0)*100:.1f}%)",
            f"Nakit Akışı (İşletme): {cashflow.get('operating', 0):,.0f} TRY",
        ]
        base_fc = (forecast.get("scenarios") or {}).get("base", {})
        if base_fc.get("runway_months"):
            lines.append(f"Nakit Runway: {base_fc['runway_months']} ay")
        alerts = cfo.get("alerts", [])
        if alerts:
            lines.append(f"Aktif Uyarılar: {len(alerts)} adet")
            for a in alerts[:3]:
                lines.append(f"  • [{a.get('level','?').upper()}] {a.get('message','')}")
        lines.append("")

    # CTO data
    cto = ctx_data.get("last_cto_result")
    if cto and agent_filter in ("all", "cto"):
        summary = cto.get("cto_summary", {})
        infra = cto.get("infra", {})
        if summary or infra:
            lines += ["=== CTO — TEKNOLOJİ ==="]
            if summary.get("overall_health_score"):
                lines.append(f"Teknoloji Sağlık Skoru: {summary['overall_health_score']:.1f}/10")
            if infra.get("total_cost_cents"):
                lines.append(f"Bulut Maliyeti: {infra['total_cost_cents']/100:,.0f} TRY")
            if infra.get("waste_estimate_cents"):
                lines.append(f"Tahmini İsraf: {infra['waste_estimate_cents']/100:,.0f} TRY")
            if summary.get("quick_wins"):
                for w in summary["quick_wins"][:2]:
                    lines.append(f"  • Hızlı Kazanım: {w.get('action','')}")
            lines.append("")

    # CMO data
    cmo = ctx_data.get("last_cmo_result")
    if cmo and agent_filter in ("all", "cmo"):
        summary = cmo.get("cmo_summary", {})
        if summary:
            lines += ["=== CMO — PAZARLAMA ==="]
            if summary.get("overall_marketing_score"):
                lines.append(f"Pazarlama Skoru: {summary['overall_marketing_score']:.1f}/10")
            campaigns = cmo.get("campaigns", {})
            if campaigns.get("overall_roas"):
                lines.append(f"ROAS: {campaigns['overall_roas']:.2f}x")
            if campaigns.get("blended_cac_cents"):
                lines.append(f"CAC: {campaigns['blended_cac_cents']/100:,.0f} TRY")
            lines.append("")

    # COO data
    coo = ctx_data.get("last_coo_result")
    if coo and agent_filter in ("all", "coo"):
        summary = coo.get("coo_summary", {})
        if summary:
            lines += ["=== COO — OPERASYON ==="]
            if summary.get("overall_ops_score"):
                lines.append(f"Operasyon Skoru: {summary['overall_ops_score']:.1f}/10")
            sla = coo.get("sla", {})
            if sla.get("breach_rate") is not None:
                lines.append(f"SLA İhlal Oranı: {sla['breach_rate']*100:.1f}%")
            lines.append("")

    # CHRO data
    chro = ctx_data.get("last_chro_result")
    if chro and agent_filter in ("all", "chro"):
        summary = chro.get("chro_summary", {})
        if summary:
            lines += ["=== CHRO — İNSAN KAYNAKLARI ==="]
            if summary.get("overall_hr_score"):
                lines.append(f"İK Sağlık Skoru: {summary['overall_hr_score']:.1f}/10")
            headcount = chro.get("headcount", {})
            attrition = chro.get("attrition", {})
            if headcount.get("total_headcount"):
                lines.append(f"Toplam Çalışan: {headcount['total_headcount']}")
            if attrition.get("annualized_attrition_rate") is not None:
                lines.append(f"Yıllık Attrition: {attrition['annualized_attrition_rate']*100:.1f}%")
            lines.append("")

    # Risk data
    risk = ctx_data.get("last_risk_result")
    if risk and agent_filter in ("all", "risk"):
        summary = risk.get("risk_summary", {})
        if summary:
            lines += ["=== RİSK ==="]
            if summary.get("overall_risk_score"):
                lines.append(f"Risk Skoru: {summary['overall_risk_score']:.0f}/100")
            if summary.get("top_risks"):
                for r in (summary.get("top_risks") or [])[:2]:
                    lines.append(f"  • [{r.get('severity','?').upper()}] {r.get('message','')}")
            lines.append("")

    if not any([cfo, cto, cmo, coo, chro, risk]):
        lines.append("UYARI: Henüz analiz verisi yok. Kullanıcıya analiz çalıştırmasını öner.")

    return "\n".join(lines)


@router.post("/chat/agent")
async def chat_with_agent(
    body: AgentChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict | StreamingResponse:
    """
    Universal agent chat — answers questions using the full CompanyContext.

    Unlike /chat/job/{id} (CFO only) or /chat/ceo (CEO/CTO only),
    this endpoint loads ALL available agent results from the org's CompanyContext
    and can answer cross-domain questions like:
    - "CTO sağlık skorumu nasıl iyileştirebilirim?"
    - "Pazarlama harcamamı kısarsam nakit ne kadar artar?"
    - "En büyük cross-domain riskimiz nedir?"
    - "CHRO ve CFO verileri birlikte ne söylüyor?"

    Server-side conversation memory:
    - History is stored in Redis per (user_id, session_id).
    - session_id auto-generated as {user_id}:{date} if not provided.
    - Each completed exchange is persisted automatically.
    """
    from app.services.company_context import get_company_context
    from app.agents.chat_agent import chat_with_cfo
    from app.config import get_settings
    from app.services.conversation_memory import get_conversation_service
    from app.services.rag_service import retrieve_evidence

    user_id = str(user.id)
    # SEC-FIX: Never fall back to "default" — use user.id as isolated namespace
    # when org_id is missing (no org). This prevents cross-tenant data leakage
    # where multiple unaffiliated users shared the "default" context bucket.
    org_id = str(user.org_id) if user.org_id else f"user:{user.id}"

    # Resolve session ID
    conv_svc = get_conversation_service()
    session_id = body.session_id or conv_svc.make_session_id(user_id)

    # Load full company context
    ctx = await get_company_context(org_id, db)
    ctx_data = ctx.to_dict()

    # Build rich system prompt
    system_prompt = _build_agent_system_prompt(
        agent_filter=body.agent_filter,
        ctx_data=ctx_data,
        company_name=ctx.company_name,
    )

    # Build server-side conversation history (overrides client-sent history)
    server_history = await conv_svc.load(user_id, session_id, last_n=20)
    # Convert to dict format expected by chat agent
    conversation_history = [t.to_llm_message() for t in server_history]

    # If client sent history but server has none (first use / migration), use client history
    if not conversation_history and body.conversation_history:
        conversation_history = body.conversation_history

    # Build enriched dashboard context
    active_cfo_job_id = (ctx.active_cfo_job_id or None) if hasattr(ctx, "active_cfo_job_id") else None
    evidence_block = await retrieve_evidence(
        db=db,
        org_id=org_id,
        query=body.question,
        job_id=active_cfo_job_id,
        top_k=3,
        source_type="cfo_transactions_raw",
    )
    evidence_found = bool((evidence_block or "").strip())
    if not evidence_found:
        evidence_block = (
            "## RAG Kanıtlar (evidence)\n"
            "- Bu soruya doğrudan kanıt bulunamadı. Yanıt verirken varsayımları açık belirt "
            "ve mümkünse kullanıcıdan veri/periyot netleştirmesi iste."
        )
    system_prompt_with_evidence = (
        f"{system_prompt}\n\n{evidence_block}" if evidence_block else system_prompt
    )

    enriched_dashboard = {
        "pnl": (ctx.last_cfo_result or {}).get("pnl", {}),
        "cashflow": (ctx.last_cfo_result or {}).get("cashflow", {}),
        "forecast": (ctx.last_cfo_result or {}).get("forecast", {}),
        "anomalies": (ctx.last_cfo_result or {}).get("anomalies", []),
        "_system_context": system_prompt_with_evidence,
        "_agent_filter": body.agent_filter,
        "_cto_result": ctx.last_cto_result,
        "_cmo_result": ctx.last_cmo_result,
        "_coo_result": ctx.last_coo_result,
        "_chro_result": ctx.last_chro_result,
        "_risk_result": ctx.last_risk_result,
        "_evidence_found": evidence_found,
        "_evidence_job_scope": active_cfo_job_id,
    }

    settings = get_settings()

    context_agents = [
        k.replace("last_", "").replace("_result", "")
        for k in ctx_data.keys()
        if k.startswith("last_") and k.endswith("_result") and ctx_data[k] is not None
    ]

    if body.stream:
        from app.agents.chat_agent import stream_chat_with_cfo

        # Collect streamed chunks to persist after completion
        collected_answer: list[str] = []

        async def _generate():
            async for chunk in stream_chat_with_cfo(
                question=body.question,
                dashboard=enriched_dashboard,
                transactions=[],
                conversation_history=conversation_history,
                system_prompt_override=system_prompt_with_evidence,
            ):
                collected_answer.append(chunk)
                yield f"data: {chunk}\n\n"

            # Persist exchange after streaming completes
            full_answer = "".join(collected_answer)
            try:
                await conv_svc.append_turn(
                    user_id=user_id,
                    session_id=session_id,
                    user_message=body.question,
                    assistant_message=full_answer,
                    metadata={"agent_filter": body.agent_filter},
                )
            except Exception:
                pass  # Never fail a response due to memory persistence

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Choose execution path: reasoning loop vs direct LLM
    reasoning_trace: dict | None = None

    if body.use_reasoning:
        from app.services.reasoning_loop import get_reasoning_loop
        loop = get_reasoning_loop()
        result = await loop.run(
            question=body.question,
            context=enriched_dashboard,
            domain=body.agent_filter if body.agent_filter != "all" else "cfo",
        )
        answer = result.answer
        reasoning_trace = result.to_trace()
    else:
        answer = await chat_with_cfo(
            question=body.question,
            dashboard=enriched_dashboard,
            transactions=[],
            conversation_history=conversation_history,
            system_prompt_override=system_prompt_with_evidence,
        )

    from app.platform.contracts import EvidenceBundle
    from app.services.rag.grounding_validator import apply_disclaimer, validate_grounding

    evidence_bundle = EvidenceBundle(
        query=body.question,
        org_id=org_id,
        citations=[],
        job_scope="job_scoped" if active_cfo_job_id else "org_wide",
    ) if evidence_found else None
    grounding = validate_grounding(answer, evidence_bundle)
    if grounding.requires_disclaimer:
        answer = apply_disclaimer(answer, grounding, locale="tr")

    # Persist exchange to server-side memory
    try:
        await conv_svc.append_turn(
            user_id=user_id,
            session_id=session_id,
            user_message=body.question,
            assistant_message=answer,
            metadata={"agent_filter": body.agent_filter, "used_reasoning": body.use_reasoning},
        )
    except Exception:
        pass  # Never fail a response due to memory persistence

    return {
        "data": {
            "answer": answer,
            "agent_filter": body.agent_filter,
            "session_id": session_id,               # return so client can reuse
            "context_agents": context_agents,
            "company_name": ctx.company_name,
            "used_reasoning": body.use_reasoning,
            "reasoning_trace": reasoning_trace,     # None unless use_reasoning=True
            "evidence_found": evidence_found,
            "evidence_job_scope": active_cfo_job_id,
            "grounding_validated": not grounding.requires_disclaimer,
            "grounding_flags": grounding.flagged_claims,
        },
        "error": None,
    }


@router.get("/chat/sessions")
async def list_chat_sessions(
    user: User = Depends(get_current_user),
) -> dict:
    """List all conversation sessions for the current user."""
    from app.services.conversation_memory import get_conversation_service

    svc = get_conversation_service()
    sessions = await svc.list_sessions(str(user.id))
    return {"data": {"sessions": sessions}, "error": None}


@router.delete("/chat/sessions/{session_id}")
async def clear_chat_session(
    session_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Clear a conversation session's history."""
    from app.services.conversation_memory import get_conversation_service

    svc = get_conversation_service()
    await svc.clear(str(user.id), session_id)
    return {"data": {"cleared": True, "session_id": session_id}, "error": None}


@router.get("/chat/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    last_n: int = 20,
    user: User = Depends(get_current_user),
) -> dict:
    """Retrieve conversation history for a session."""
    from app.services.conversation_memory import get_conversation_service

    svc = get_conversation_service()
    turns = await svc.load(str(user.id), session_id, last_n=last_n)
    return {
        "data": {
            "session_id": session_id,
            "turns": [t.to_dict() for t in turns],
            "count": len(turns),
        },
        "error": None,
    }
