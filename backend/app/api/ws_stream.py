"""
WebSocket Streaming API
=======================

Token-level LLM streaming over WebSocket with optional dual-RAG grounding.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)
router = APIRouter()


async def _stream_llm_tokens(
    prompt: str,
    system_prompt: str,
    settings: Any,
    task_type: str = "quick_analysis",
) -> AsyncIterator[str]:
    try:
        from app.platform.model_gateway import stream as _gw_stream

        async for piece in _gw_stream(
            task=task_type, system_prompt=system_prompt, prompt=prompt,
        ):
            if piece:
                yield piece

    except Exception as exc:
        logger.error("LLM streaming failed: %s", exc)
        raise


async def _build_chat_prompt(
    question: str,
    job_id: str | None,
    org_id: str | None,
) -> tuple[str, str, Any | None]:
    """Returns (system_prompt, user_prompt, GroundedChatPack|None)."""
    context_lines: list[str] = []

    if job_id:
        try:
            from app.database import session_factory
            from app.models.analysis_job import AnalysisJob

            async with session_factory()() as db:
                job = await db.get(AnalysisJob, job_id)
                if job and job.result:
                    result = job.result
                    pnl = result.get("pnl", {})
                    if pnl:
                        rev = pnl.get("revenue", 0) / 100
                        gm = pnl.get("gross_margin", 0) * 100
                        nm = pnl.get("net_margin", 0) * 100
                        context_lines.append(
                            f"Finansal Özet: Gelir ₺{rev:,.0f}, Brüt Marj %{gm:.1f}, Net Marj %{nm:.1f}"
                        )
                    cf = result.get("cashflow", {})
                    if cf:
                        runway = cf.get("runway_months")
                        if runway:
                            context_lines.append(f"Nakit Pisti: {runway:.1f} ay")
        except Exception as exc:
            logger.debug("Could not load job context: %s", exc)

    context_block = "\n".join(context_lines) if context_lines else "Genel finansal analiz modu."

    base_system = (
        "Sen bir C-Suite düzeyinde Türk iş danışmanı ve CFO asistanısın. "
        "Şirket verilerini kullanarak kısa, net ve eyleme dönüştürülebilir cevaplar ver. "
        "Sayısal verileri vurgula. Türkçe yanıtla.\n\n"
        f"Mevcut Şirket Verisi:\n{context_block}"
    )

    if org_id:
        try:
            from app.database import session_factory
            from app.services.chat_grounding import prepare_grounded_chat

            async with session_factory()() as db:
                pack = await prepare_grounded_chat(
                    db=db,
                    org_id=org_id,
                    question=question,
                    base_system_prompt=base_system,
                    job_id=job_id,
                    locale="tr",
                )
                return pack.system_prompt, question, pack
        except Exception as exc:
            logger.warning("Grounded WS prompt failed, using base context: %s", exc)

    return base_system, question, None


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("WebSocket chat connection opened")

    try:
        from app.config import get_settings
        from app.services.llm_structured import _is_placeholder_key

        settings = get_settings()

        while True:
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

            if msg_type == "ping":
                await _send(websocket, {"type": "pong"})
                continue

            if msg_type == "chat":
                question = msg.get("question", "").strip()
                job_id = msg.get("job_id") or None
                org_id = msg.get("org_id") or None

                if not question:
                    await _send(websocket, {"type": "error", "message": "Soru boş olamaz"})
                    continue

                if _is_placeholder_key(settings.openai_api_key):
                    mock = (
                        f"[Demo mod] '{question}' sorunuz alındı. "
                        "Gerçek LLM yanıtı için OpenAI API anahtarı gereklidir."
                    )
                    await _send(websocket, {"type": "token", "content": mock})
                    await _send(
                        websocket,
                        {
                            "type": "done",
                            "full_text": mock,
                            "evidence_found": False,
                        },
                    )
                    continue

                await _send(websocket, {"type": "status", "message": "Analiz ediliyor…"})

                try:
                    system_prompt, user_prompt, grounded_pack = await _build_chat_prompt(
                        question, job_id, org_id
                    )
                except Exception as exc:
                    logger.warning("Context build failed: %s", exc)
                    system_prompt = (
                        "Sen bir C-Suite düzeyinde Türk iş danışmanısın. "
                        "Kısa ve net cevaplar ver. Türkçe yanıtla."
                    )
                    user_prompt = question
                    grounded_pack = None

                full_text = ""
                evidence_meta: dict[str, Any] = {
                    "evidence_found": False,
                    "evidence_tx_count": 0,
                    "evidence_semantic_count": 0,
                    "evidence_retriever_version": "none",
                    "grounding_validated": True,
                }
                try:
                    async for token in _stream_llm_tokens(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        settings=settings,
                        task_type="quick_analysis",
                    ):
                        full_text += token
                        await _send(websocket, {"type": "token", "content": token})

                    if grounded_pack is not None:
                        from app.services.chat_grounding import finalize_grounded_answer

                        full_text, validated = finalize_grounded_answer(
                            full_text, grounded_pack, locale="tr"
                        )
                        evidence_meta = grounded_pack.to_meta()
                        evidence_meta["grounding_validated"] = validated

                    await _send(
                        websocket,
                        {
                            "type": "done",
                            "full_text": full_text,
                            **evidence_meta,
                        },
                    )

                except Exception as exc:
                    logger.error("Streaming error: %s", exc)
                    await _send(
                        websocket,
                        {
                            "type": "error",
                            "message": f"LLM yanıt hatası: {str(exc)[:200]}",
                        },
                    )

            else:
                await _send(
                    websocket,
                    {"type": "error", "message": f"Bilinmeyen mesaj tipi: {msg_type}"},
                )

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
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass
