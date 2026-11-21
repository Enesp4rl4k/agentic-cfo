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

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.api import ws_auth
from app.api.access import can_access

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


async def _owns_job(job_id: str, user: Any) -> bool:
    from app.database import session_factory
    from app.models.analysis_job import AnalysisJob

    try:
        async with session_factory()() as db:
            job = await db.get(AnalysisJob, job_id)
    except Exception as exc:
        logger.warning("Chat job ownership check failed: %s", exc)
        return False
    return job is not None and can_access(user, org_id=job.org_id, user_id=job.user_id)


async def _build_chat_prompt(
    question: str,
    job_id: str | None,
    org_id: str | None,
    user: Any,
) -> tuple[str, str, Any | None]:
    """Returns (system_prompt, user_prompt, GroundedChatPack|None).

    `org_id` is the caller's own organisation, never one the client named; a
    `job_id` that is not the caller's is treated as absent.
    """
    # A job the caller does not own is treated as absent, before anything
    # reads it. (A block here used to put the job's P&L into the prompt from
    # `job.result`; AnalysisJob has no such attribute, so it raised, was
    # swallowed, and never added a figure. Grounding below is the real path.)
    if job_id and not await _owns_job(job_id, user):
        job_id = None

    context_block = "Genel finansal analiz modu."

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
async def websocket_chat(
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    # The socket used to take no token and to ground its answer in whatever
    # job and organisation the client named: another company's figures, on
    # our model bill. Signed-in callers only, and only their own data.
    user = await ws_auth.websocket_caller(token)
    if user is None:
        await websocket.close(code=ws_auth.REFUSED)
        return
    own_org_id = str(user.org_id) if user.org_id else None
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

            # The token was checked once, at connect. Everything after it is asked again, per message:
            # a removed, deactivated or switched-away person is refused and the socket closed, so the
            # answer is never grounded in a company they no longer act in.
            user = await ws_auth.websocket_caller(token)
            if user is None or (user.org_id and str(user.org_id) != own_org_id) or (
                own_org_id is not None and not await ws_auth.still_acting_in(str(user.id), own_org_id)
            ) or (own_org_id is None and user.org_id):
                await _send(websocket, {"type": "error", "message": "Oturum bu şirket için artık geçerli değil."})
                await websocket.close(code=ws_auth.REFUSED)
                return

            if msg_type == "chat":
                question = msg.get("question", "").strip()
                job_id = msg.get("job_id") or None

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
                        question, job_id, own_org_id, user
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
