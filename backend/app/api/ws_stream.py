"""
WebSocket Streaming API
=======================

Token-level LLM streaming over WebSocket.

Endpoint:
    WS /api/v1/ws/chat

Protocol (client → server):
    {"type": "chat", "question": "...", "job_id": "...", "org_id": "..."}
    {"type": "ping"}

Protocol (server → client):
    {"type": "token",  "content": "..."}          ← streaming token
    {"type": "done",   "full_text": "..."}         ← stream complete
    {"type": "error",  "message": "..."}           ← error
    {"type": "pong"}                               ← ping reply
    {"type": "status", "message": "..."}           ← status update

Why WebSocket over SSE for token streaming?
  - Bidirectional: client can cancel, send follow-ups mid-stream
  - Lower overhead per-message (no HTTP headers on each chunk)
  - Native browser support via WebSocket API
  - DDIA: streaming pipeline principle — process data as it arrives
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Token streaming helper ────────────────────────────────────────────────────

async def _stream_llm_tokens(
    prompt: str,
    system_prompt: str,
    settings: Any,
    task_type: str = "quick_analysis",
) -> AsyncIterator[str]:
    """
    Stream LLM tokens via LangChain streaming callback.
    Uses LLMTaskRouter to select the appropriate model.
    Falls back to non-streaming if streaming unavailable.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.services.llm_router import get_llm_router

        router_svc = get_llm_router()
        config = router_svc.select_model(task_type, len(prompt))

        llm = ChatOpenAI(
            model=config.model_id,
            temperature=0.3,
            max_tokens=config.max_tokens,
            api_key=settings.openai_api_key,
            base_url=getattr(settings, "llm_base_url", None) or None,
            streaming=True,
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]

        async for chunk in llm.astream(messages):
            content = chunk.content
            if content:
                yield content

    except Exception as exc:
        logger.error("LLM streaming failed: %s", exc)
        raise


async def _build_chat_prompt(
    question: str,
    job_id: str | None,
    org_id: str | None,
) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) from job/org context.
    Returns simple prompts if no context is available.
    """
    context_lines: list[str] = []

    if job_id:
        try:
            from app.database import get_db
            from app.models.analysis_job import AnalysisJob
            from app.models.report import Report, ReportFormat

            async for db in get_db():
                job = await db.get(AnalysisJob, job_id)
                if job and job.result:
                    result = job.result
                    pnl = result.get("pnl", {})
                    if pnl:
                        rev = pnl.get("revenue", 0) / 100
                        gm  = pnl.get("gross_margin", 0) * 100
                        nm  = pnl.get("net_margin",   0) * 100
                        context_lines.append(
                            f"Finansal Özet: Gelir ₺{rev:,.0f}, Brüt Marj %{gm:.1f}, Net Marj %{nm:.1f}"
                        )
                    cf = result.get("cashflow", {})
                    if cf:
                        runway = cf.get("runway_months")
                        if runway:
                            context_lines.append(f"Nakit Pisti: {runway:.1f} ay")
                break
        except Exception as exc:
            logger.debug("Could not load job context: %s", exc)

    if org_id:
        try:
            from app.services.company_context import get_company_context_service
            svc = get_company_context_service()
            ctx = await svc.get_context(org_id)
            if ctx:
                snapshot = ctx.get("snapshot", {})
                if snapshot:
                    context_lines.append(f"Şirket Bağlamı: {json.dumps(snapshot, ensure_ascii=False)[:500]}")
        except Exception as exc:
            logger.debug("Could not load org context: %s", exc)

    context_block = "\n".join(context_lines) if context_lines else "Genel finansal analiz modu."

    system_prompt = (
        "Sen bir C-Suite düzeyinde Türk iş danışmanı ve CFO asistanısın. "
        "Şirket verilerini kullanarak kısa, net ve eyleme dönüştürülebilir cevaplar ver. "
        "Sayısal verileri vurgula. Türkçe yanıtla.\n\n"
        f"Mevcut Şirket Verisi:\n{context_block}"
    )

    return system_prompt, question


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """
    Token-level streaming chat over WebSocket.

    Client connects, sends a chat message, receives tokens in real-time.
    Supports multiple messages per connection (stateful session).

    Message flow:
        client → {"type": "chat", "question": "...", "job_id": "...", "org_id": "..."}
        server → {"type": "token", "content": "Analiz..."}  (multiple)
        server → {"type": "done", "full_text": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket chat connection opened")

    try:
        from app.config import get_settings
        settings = get_settings()

        while True:
            # Receive message
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, {"type": "error", "message": "Geçersiz JSON"})
                continue

            msg_type = msg.get("type", "chat")

            # ── Ping/pong ────────────────────────────────────────────────────
            if msg_type == "ping":
                await _send(websocket, {"type": "pong"})
                continue

            # ── Chat request ─────────────────────────────────────────────────
            if msg_type == "chat":
                question = msg.get("question", "").strip()
                job_id   = msg.get("job_id") or None
                org_id   = msg.get("org_id") or None

                if not question:
                    await _send(websocket, {"type": "error", "message": "Soru boş olamaz"})
                    continue

                # Check if LLM is available
                from app.services.llm_structured import _is_placeholder_key
                if _is_placeholder_key(settings.openai_api_key):
                    # Fallback: non-streaming mock response
                    mock = (
                        f"[Demo mod] '{question}' sorunuz alındı. "
                        "Gerçek LLM yanıtı için OpenAI API anahtarı gereklidir."
                    )
                    await _send(websocket, {"type": "token", "content": mock})
                    await _send(websocket, {"type": "done",  "full_text": mock})
                    continue

                # Build context-aware prompt
                await _send(websocket, {"type": "status", "message": "Analiz ediliyor…"})

                try:
                    system_prompt, user_prompt = await _build_chat_prompt(
                        question, job_id, org_id
                    )
                except Exception as exc:
                    logger.warning("Context build failed: %s", exc)
                    system_prompt = (
                        "Sen bir C-Suite düzeyinde Türk iş danışmanısın. "
                        "Kısa ve net cevaplar ver. Türkçe yanıtla."
                    )
                    user_prompt = question

                # Stream tokens
                full_text = ""
                try:
                    async for token in _stream_llm_tokens(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        settings=settings,
                        task_type="quick_analysis",
                    ):
                        full_text += token
                        await _send(websocket, {"type": "token", "content": token})

                    await _send(websocket, {"type": "done", "full_text": full_text})

                except Exception as exc:
                    logger.error("Streaming error: %s", exc)
                    await _send(websocket, {
                        "type": "error",
                        "message": f"LLM yanıt hatası: {str(exc)[:200]}",
                    })

            else:
                await _send(websocket, {
                    "type": "error",
                    "message": f"Bilinmeyen mesaj tipi: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket chat disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await _send(websocket, {"type": "error", "message": "Sunucu hatası"})
            except Exception:
                pass
    finally:
        logger.info("WebSocket chat connection closed")


async def _send(ws: WebSocket, data: dict) -> None:
    """Send JSON message, silently ignore disconnected socket."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass
