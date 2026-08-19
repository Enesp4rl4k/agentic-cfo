"""
Conversation Memory — Server-side multi-turn chat history.

Problem: chat.py currently relies on the client to send back the full
conversation_history on each turn. This means:
  - History is lost if the client refreshes or crashes
  - No server-side audit trail of conversations
  - No ability to inject memory from past *sessions*

This module adds:
  1. ConversationSession: persistent Redis-backed turn store per (user, session)
  2. ConversationMemoryService: load/save/summarise conversation turns
  3. MemoryInjector: merges episodic agent memory + conversation history
     into a ready-to-use list for LLM calls

Architecture
------------
  Redis key: conv:{user_id}:{session_id}  → JSON list of turns (TTL 7 days)
  Fallback: in-memory dict when Redis is unavailable (dev mode)

Turn format (compatible with OpenAI messages):
  {"role": "user" | "assistant" | "system", "content": "...", "ts": 1234567890}

Session ID:
  - If client sends X-Session-Id header, that is used.
  - Otherwise auto-generated as {user_id}:{date} (one session per day).

Usage
-----
    svc = ConversationMemoryService()

    # At start of request: load history
    history = await svc.load(user_id="u1", session_id="s1")

    # After generating answer: persist turn
    await svc.append_turn(
        user_id="u1", session_id="s1",
        user_message="Nakit durumum ne?",
        assistant_message="Mevcut nakit 450K TL...",
    )

    # Build context for LLM: episodic memory + conversation turns
    injector = MemoryInjector(memory_store=get_memory_store())
    messages = await injector.build_messages(
        user_id="u1",
        org_id="org-123",
        session_id="s1",
        system_prompt="Sen bir CFO asistanısın...",
        current_question="Geçen aya göre ne değişti?",
    )
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Redis helper ──────────────────────────────────────────────────────────────

_redis_client: Any = None


async def _get_redis() -> Any | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        from app.config import get_settings

        settings = get_settings()
        redis_url = getattr(settings, "redis_url", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception:
        return None


# ── Turn model ────────────────────────────────────────────────────────────────

@dataclass
class ConversationTurn:
    """A single message exchange in a conversation."""

    role: str                        # "user" | "assistant" | "system"
    content: str
    ts: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "ts": self.ts,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConversationTurn":
        return cls(
            role=d["role"],
            content=d["content"],
            ts=d.get("ts", time.time()),
            metadata=d.get("metadata", {}),
        )

    def to_llm_message(self) -> dict[str, str]:
        """Convert to OpenAI-compatible message format."""
        return {"role": self.role, "content": self.content}


# ── In-memory fallback ────────────────────────────────────────────────────────

_fallback_store: dict[str, list[dict[str, Any]]] = {}


def _fallback_key(user_id: str, session_id: str) -> str:
    return f"conv:{user_id}:{session_id}"


# ── ConversationMemoryService ─────────────────────────────────────────────────

class ConversationMemoryService:
    """
    Load and persist conversation turns for a user session.

    Redis TTL: 7 days per session (sliding window — resets on activity).
    Max turns kept: `max_turns` (oldest pruned beyond that).
    """

    REDIS_TTL = 60 * 60 * 24 * 7   # 7 days in seconds
    DEFAULT_MAX_TURNS = 40          # per session

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        self.max_turns = max_turns

    def make_session_id(self, user_id: str) -> str:
        """Generate a daily session ID (one session per calendar day)."""
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return f"{user_id}:{today}"

    def _redis_key(self, user_id: str, session_id: str) -> str:
        return f"conv:{user_id}:{session_id}"

    async def load(
        self,
        user_id: str,
        session_id: str,
        last_n: int | None = None,
    ) -> list[ConversationTurn]:
        """
        Load conversation turns for a session.

        Parameters
        ----------
        last_n : int, optional
            Return only the last N turns (for context window trimming).
        """
        key = self._redis_key(user_id, session_id)
        redis = await _get_redis()

        raw_list: list[dict[str, Any]] = []

        if redis:
            try:
                data = await redis.get(key)
                if data:
                    raw_list = json.loads(data)
            except Exception as e:
                logger.warning("ConversationMemory: Redis load failed: %s", e)
                raw_list = _fallback_store.get(key, [])
        else:
            raw_list = _fallback_store.get(key, [])

        turns = [ConversationTurn.from_dict(d) for d in raw_list]

        if last_n is not None:
            turns = turns[-last_n:]

        return turns

    async def append_turn(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a user+assistant exchange to the session history."""
        key = self._redis_key(user_id, session_id)
        redis = await _get_redis()

        # Load existing
        existing: list[dict[str, Any]] = []
        if redis:
            try:
                data = await redis.get(key)
                if data:
                    existing = json.loads(data)
            except Exception:
                existing = list(_fallback_store.get(key, []))
        else:
            existing = list(_fallback_store.get(key, []))

        # Append new turns
        ts = time.time()
        existing.append(ConversationTurn(
            role="user",
            content=user_message,
            ts=ts,
            metadata=metadata or {},
        ).to_dict())
        existing.append(ConversationTurn(
            role="assistant",
            content=assistant_message,
            ts=ts + 0.001,
            metadata={"agent": "cfo_chat"},
        ).to_dict())

        # Prune oldest turns beyond max
        if len(existing) > self.max_turns * 2:  # *2 because user+assistant pairs
            existing = existing[-(self.max_turns * 2):]

        # Persist
        serialised = json.dumps(existing)
        if redis:
            try:
                await redis.set(key, serialised, ex=self.REDIS_TTL)
            except Exception as e:
                logger.warning("ConversationMemory: Redis save failed: %s", e)
                _fallback_store[key] = existing
        else:
            _fallback_store[key] = existing

    async def clear(self, user_id: str, session_id: str) -> None:
        """Clear a session's history."""
        key = self._redis_key(user_id, session_id)
        redis = await _get_redis()
        if redis:
            try:
                await redis.delete(key)
            except Exception:
                pass
        _fallback_store.pop(key, None)

    async def list_sessions(self, user_id: str) -> list[str]:
        """List all session IDs for a user (Redis SCAN)."""
        redis = await _get_redis()
        if not redis:
            prefix = f"conv:{user_id}:"
            return [
                k.removeprefix(prefix)
                for k in _fallback_store
                if k.startswith(prefix)
            ]
        try:
            keys: list[str] = []
            pattern = f"conv:{user_id}:*"
            async for key in redis.scan_iter(pattern):
                session_id = key.removeprefix(f"conv:{user_id}:")
                keys.append(session_id)
            return keys
        except Exception:
            return []

    async def get_summary(self, user_id: str, session_id: str) -> str:
        """Return a short text summary of the session for context injection."""
        turns = await self.load(user_id, session_id, last_n=10)
        if not turns:
            return ""

        lines = [f"## Mevcut Oturum Geçmişi (son {len(turns)} mesaj)"]
        for t in turns:
            if t.role == "user":
                lines.append(f"  Kullanıcı: {t.content[:120]}")
            elif t.role == "assistant":
                lines.append(f"  Asistan: {t.content[:200]}")

        return "\n".join(lines)


# ── MemoryInjector ────────────────────────────────────────────────────────────

class MemoryInjector:
    """
    Merges episodic agent memory + conversation turn history into
    an ordered list of LLM messages.

    Output format (OpenAI-compatible):
        [
            {"role": "system",    "content": "<system prompt + episodic memory>"},
            {"role": "user",      "content": "previous Q1"},
            {"role": "assistant", "content": "previous A1"},
            ...
            {"role": "user",      "content": "<current question>"},
        ]
    """

    def __init__(
        self,
        memory_store: Any | None = None,
        conversation_svc: ConversationMemoryService | None = None,
    ) -> None:
        self._memory = memory_store
        self._conv = conversation_svc or ConversationMemoryService()

    async def build_messages(
        self,
        user_id: str,
        org_id: str,
        session_id: str,
        system_prompt: str,
        current_question: str,
        last_n_turns: int = 10,
        include_episodic: bool = True,
        episodic_top_k: int = 3,
    ) -> list[dict[str, str]]:
        """
        Build a complete messages list for LLM call.

        Parameters
        ----------
        last_n_turns : int
            How many past turns to include (trimmed for token budget).
        include_episodic : bool
            Whether to inject episodic agent memory into the system prompt.
        """
        # 1. Optionally enrich system prompt with episodic memory
        enriched_system = system_prompt
        if include_episodic and self._memory:
            try:
                episodes = await _safe_retrieve(
                    self._memory, org_id=org_id, top_k=episodic_top_k, query=current_question
                )
                memory_block = self._memory.format_for_context(episodes)
                if memory_block:
                    enriched_system = f"{system_prompt}\n\n{memory_block}"
            except Exception as e:
                logger.debug("MemoryInjector: episodic memory retrieval failed: %s", e)

        # 1.5 RAG evidence injection (best-effort)
        # Adds factual “evidence snippets” so the LLM can ground claims.
        try:
            from app.services.rag_service import retrieve_evidence

            evidence_block = await retrieve_evidence(
                org_id=org_id,
                query=current_question,
                top_k=3,
                source_type="cfo_transactions_raw",
            )
            if evidence_block:
                enriched_system = f"{enriched_system}\n\n{evidence_block}"
        except Exception as exc:
            logger.debug("MemoryInjector: RAG evidence retrieval failed: %s", exc)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": enriched_system}
        ]

        # 2. Load recent conversation turns
        past_turns = await self._conv.load(user_id, session_id, last_n=last_n_turns * 2)
        for turn in past_turns:
            if turn.role in ("user", "assistant"):
                messages.append(turn.to_llm_message())

        # 3. Append the current question
        messages.append({"role": "user", "content": current_question})

        return messages

    async def persist_exchange(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a completed exchange to conversation memory."""
        await self._conv.append_turn(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            metadata=metadata,
        )


async def _safe_retrieve(memory_store: Any, org_id: str, top_k: int, query: str) -> list:
    """Wrapper: handles both sync and async retrieve methods."""
    import asyncio
    try:
        result = memory_store.retrieve(org_id=org_id, top_k=top_k, query=query)
        if asyncio.iscoroutine(result):
            return await result
        return result
    except Exception:
        return []


# ── Module singletons ─────────────────────────────────────────────────────────

_conversation_svc: ConversationMemoryService | None = None
_memory_injector: MemoryInjector | None = None


def get_conversation_service() -> ConversationMemoryService:
    global _conversation_svc
    if _conversation_svc is None:
        _conversation_svc = ConversationMemoryService()
    return _conversation_svc


def get_memory_injector() -> MemoryInjector:
    global _memory_injector
    if _memory_injector is None:
        from app.services.agent_memory import get_memory_store
        _memory_injector = MemoryInjector(
            memory_store=get_memory_store(),
            conversation_svc=get_conversation_service(),
        )
    return _memory_injector
