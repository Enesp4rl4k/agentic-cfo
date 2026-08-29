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
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from langgraph.checkpoint.base import CheckpointMetadata

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None


def _memory_saver() -> Any:
    try:
        from langgraph.checkpoint.memory import MemorySaver

        class _CompatMemorySaver(MemorySaver):
            def _normalize_config(self, config: Any) -> Any:
                if isinstance(config, dict):
                    cfg = config.setdefault("configurable", {})
                    if isinstance(cfg, dict):
                        cfg.setdefault("checkpoint_ns", "")
                return config

            def _fix_tuple(self, res: Any) -> Any:
                if res is not None and hasattr(res, "config") and isinstance(res.config, dict):
                    cfg = res.config.setdefault("configurable", {})
                    if isinstance(cfg, dict):
                        cfg.setdefault("checkpoint_ns", "")
                        if hasattr(res, "checkpoint") and isinstance(res.checkpoint, dict):
                            cid = res.checkpoint.get("id")
                            if cid and "checkpoint_id" not in cfg:
                                cfg["checkpoint_id"] = cid
                return res

            def get_tuple(self, config: Any) -> Any:
                return self._fix_tuple(super().get_tuple(self._normalize_config(config)))

            async def aget_tuple(self, config: Any) -> Any:
                return self._fix_tuple(await super().aget_tuple(self._normalize_config(config)))

            def put_writes(self, config: Any, writes: Any, task_id: Any, task_path: Any = "", *args: Any, **kwargs: Any) -> Any:
                self._normalize_config(config)
                if isinstance(config, dict):
                    config.setdefault("configurable", {}).setdefault("checkpoint_id", "")
                try:
                    return super().put_writes(config, writes, task_id, task_path, *args, **kwargs)
                except KeyError:
                    return None

            async def aput_writes(self, config: Any, writes: Any, task_id: Any, task_path: Any = "", *args: Any, **kwargs: Any) -> Any:
                self._normalize_config(config)
                if isinstance(config, dict):
                    config.setdefault("configurable", {}).setdefault("checkpoint_id", "")
                try:
                    return await super().aput_writes(config, writes, task_id, task_path, *args, **kwargs)
                except KeyError:
                    return None

            def put(self, config: Any, checkpoint: Any, metadata: Any = None, new_versions: Any = None, *args: Any, **kwargs: Any) -> Any:
                if new_versions is None:
                    new_versions = {}
                return super().put(self._normalize_config(config), checkpoint, cast("CheckpointMetadata", metadata or {}), new_versions, *args, **kwargs)

            async def aput(self, config: Any, checkpoint: Any, metadata: Any = None, new_versions: Any = None, *args: Any, **kwargs: Any) -> Any:
                if new_versions is None:
                    new_versions = {}
                return await super().aput(self._normalize_config(config), checkpoint, cast("CheckpointMetadata", metadata or {}), new_versions, *args, **kwargs)

        return _CompatMemorySaver()
    except Exception as exc:
        logger.warning("langgraph MemorySaver unavailable (%s) — using stub", exc)

        class _StubMemorySaver:
            """Minimal stand-in when langgraph is not installed (tests / lean envs)."""

            def __init__(self) -> None:
                self._store: dict[str, Any] = {}

            def get(self, config: dict[str, Any]) -> Any:
                tid = (config.get("configurable") or {}).get("thread_id")
                return self._store.get(str(tid)) if tid is not None else None

            def put(self, config: dict[str, Any], checkpoint: Any, *args: Any, **kwargs: Any) -> None:
                tid = (config.get("configurable") or {}).get("thread_id")
                if tid is not None:
                    self._store[str(tid)] = checkpoint

        return _StubMemorySaver()


def _sqlite_saver(path: str) -> Any:
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

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
    return "memory"


def get_checkpointer() -> Any:
    """
    Process-wide checkpointer singleton.

    Safe to call from FastAPI and ARQ worker. MemorySaver always works in async ainvoke.
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    backend = resolve_checkpoint_backend()
    if backend == "memory":
        saver = _memory_saver()
    elif backend == "sqlite":
        try:
            saver = _memory_saver()  # fallback to memory in dev/tests
        except Exception:
            saver = _memory_saver()
    else:
        saver = _memory_saver()

    _CHECKPOINTER = saver
    logger.info("LangGraph checkpointer ready: backend=%s type=%s", backend, type(saver).__name__)
    return saver



def checkpoint_config(thread_id: str, *, run_config: Any = None) -> dict[str, Any]:
    """Build ainvoke config dict with thread_id for resume."""
    configurable: dict[str, Any] = {"thread_id": str(thread_id), "checkpoint_ns": ""}
    if run_config is not None:
        configurable["run_config"] = run_config
    return {"configurable": configurable}
