"""
LangGraph checkpointer factory — resume failed / interrupted agent runs.

Backend selection:
  - sqlite (default when use_sqlite / LANGGRAPH_CHECKPOINT=sqlite)
  - postgres (prod DATABASE_URL / LANGGRAPH_CHECKPOINT=postgres)
  - memory (fallback when optional savers are unavailable)

Thread id convention: AnalysisJob.id (passed as configurable.thread_id).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None


def _memory_saver() -> Any:
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def _sqlite_saver(path: str) -> Any:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3

        conn = sqlite3.connect(path, check_same_thread=False)
        return SqliteSaver(conn)
    except Exception as exc:
        logger.warning("Sqlite checkpointer unavailable (%s) — using MemorySaver", exc)
        return _memory_saver()


def _postgres_saver(dsn: str) -> Any:
    clean = (
        dsn.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )
    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore

        saver = PostgresSaver.from_conn_string(clean)
        # Some versions return a context manager / need setup().
        if hasattr(saver, "setup"):
            try:
                saver.setup()
            except Exception:
                pass
        return saver
    except Exception as exc:
        logger.warning("Postgres checkpointer unavailable (%s) — using MemorySaver", exc)
        return _memory_saver()


def resolve_checkpoint_backend() -> str:
    explicit = (os.environ.get("LANGGRAPH_CHECKPOINT") or "").strip().lower()
    if explicit in {"memory", "sqlite", "postgres"}:
        return explicit
    try:
        from app.config import get_settings

        settings = get_settings()
        if getattr(settings, "use_sqlite", True):
            return "sqlite"
        return "postgres"
    except Exception:
        return "memory"


def get_checkpointer() -> Any:
    """
    Process-wide checkpointer singleton.

    Safe to call from FastAPI and ARQ worker. MemorySaver always works;
    durable backends enable resume across process restarts.
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    backend = resolve_checkpoint_backend()
    if backend == "memory":
        saver = _memory_saver()
    elif backend == "sqlite":
        path = os.environ.get("LANGGRAPH_CHECKPOINT_SQLITE", "./langgraph_checkpoints.sqlite")
        saver = _sqlite_saver(path)
    else:
        try:
            from app.config import get_settings

            dsn = get_settings().database_url_sync
        except Exception:
            dsn = os.environ.get("DATABASE_URL", "")
        if not dsn or "sqlite" in str(dsn):
            saver = _sqlite_saver(
                os.environ.get("LANGGRAPH_CHECKPOINT_SQLITE", "./langgraph_checkpoints.sqlite")
            )
        else:
            saver = _postgres_saver(str(dsn))

    _CHECKPOINTER = saver
    logger.info("LangGraph checkpointer ready: backend=%s type=%s", backend, type(saver).__name__)
    return saver


def checkpoint_config(thread_id: str, *, run_config: Any = None) -> dict[str, Any]:
    """Build ainvoke config dict with thread_id for resume."""
    configurable: dict[str, Any] = {"thread_id": str(thread_id)}
    if run_config is not None:
        configurable["run_config"] = run_config
    return {"configurable": configurable}
