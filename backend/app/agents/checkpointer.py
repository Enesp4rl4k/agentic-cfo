"""
LangGraph checkpointer factory — resume failed / interrupted agent runs.

Backend selection (DDIA Ch.1 — durable state cannot live in one process):
  - explicit LANGGRAPH_CHECKPOINT=memory|sqlite|postgres always wins
  - otherwise derived from settings: sqlite in dev (a file every worker
    process shares), postgres in prod
  - any backend that fails to construct falls back to in-memory **loudly**:
    memory means checkpoints die with the process, so cross-process resume is
    impossible. Correctness survives — pipeline nodes are idempotent
    recomputes (see `agents/run_ledger.py`) and the worker purges outputs
    before rewriting them — but every run recomputes from scratch.

Before this file was fixed, all three branches of `get_checkpointer` called
`_memory_saver()`: the sqlite and postgres savers existed as dead code and
the "durable" claim in the run ledger was false. The failure mode was silent,
which is worse than slow.

Thread id convention: AnalysisJob.id (passed as configurable.thread_id).
"""
from __future__ import annotations

import inspect
import logging
import os
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from langgraph.checkpoint.base import CheckpointMetadata

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None


def _takes(method: Any, name: str) -> bool:
    """Whether the saver underneath accepts this argument.

    The saver's signature differs between langgraph releases — and between
    langgraph's own `langgraph.checkpoint` and the separate
    `langgraph-checkpoint` package that shadows it. Passing an argument it
    does not take raised `MemorySaver.aput() takes 4 positional arguments but
    5 were given` on every checkpointed run, which is what a clean install of
    the pinned versions does.
    """
    try:
        return name in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


def _compatify(saver: Any, *, async_via_thread: bool = False) -> Any:
    """Wrap any saver in the signature-tolerant shims the memory backend
    needed (missing `checkpoint_ns` / `checkpoint_id`, optional
    `new_versions` / `task_path` arguments, KeyErrors on writes for threads
    that do not exist yet).

    The shims are written against `type(saver)` rather than MemorySaver so
    SqliteSaver / PostgresSaver get the same tolerance — they share the same
    upstream signature drift, and an unwrapped saver raised on a clean
    install just as readily.

    `async_via_thread` bridges async methods to the sync ones on a worker
    thread. SqliteSaver (pinned langgraph) has async methods that only raise
    `NotImplementedError`, while its async sibling cannot be constructed
    without an awaited connect — and `get_checkpointer()` is sync. Checkpoint
    writes happen once per super-step; a thread hop is cheaper than an
    async-only rewrite of a working sync path.
    """
    base = type(saver)

    class _Compat(base):  # type: ignore[misc, valid-type]
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

        def put_writes(
            self, config: Any, writes: Any, task_id: Any, task_path: Any = "", *args: Any, **kwargs: Any
        ) -> Any:
            self._normalize_config(config)
            if isinstance(config, dict):
                config.setdefault("configurable", {}).setdefault("checkpoint_id", "")
            rest = (task_path, *args) if _takes(base.put_writes, "task_path") else args
            try:
                return super().put_writes(config, writes, task_id, *rest, **kwargs)
            except KeyError:
                return None

        async def aput_writes(
            self, config: Any, writes: Any, task_id: Any, task_path: Any = "", *args: Any, **kwargs: Any
        ) -> Any:
            self._normalize_config(config)
            if isinstance(config, dict):
                config.setdefault("configurable", {}).setdefault("checkpoint_id", "")
            rest = (task_path, *args) if _takes(base.aput_writes, "task_path") else args
            try:
                return await super().aput_writes(config, writes, task_id, *rest, **kwargs)
            except KeyError:
                return None

        def put(
            self,
            config: Any,
            checkpoint: Any,
            metadata: Any = None,
            new_versions: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            rest = (
                ({} if new_versions is None else new_versions,)
                if _takes(base.put, "new_versions")
                else ()
            )
            return super().put(
                self._normalize_config(config),
                checkpoint,
                cast("CheckpointMetadata", metadata or {}),
                *rest,
                *args,
                **kwargs,
            )

        async def aput(
            self,
            config: Any,
            checkpoint: Any,
            metadata: Any = None,
            new_versions: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            rest = (
                ({} if new_versions is None else new_versions,)
                if _takes(base.aput, "new_versions")
                else ()
            )
            return await super().aput(
                self._normalize_config(config),
                checkpoint,
                cast("CheckpointMetadata", metadata or {}),
                *rest,
                *args,
                **kwargs,
            )

    try:
        obj = _Compat.__new__(_Compat)
        obj.__dict__.update(saver.__dict__)
    except Exception as exc:  # exotic saver with slots / exotic state
        logger.warning("Could not compat-wrap %s (%s) — using it bare", base.__name__, exc)
        return saver

    if async_via_thread:
        import asyncio

        async def _aget_tuple(self: Any, config: Any) -> Any:
            return await asyncio.to_thread(self.get_tuple, config)

        async def _aput(
            self: Any,
            config: Any,
            checkpoint: Any,
            metadata: Any = None,
            new_versions: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            return await asyncio.to_thread(
                self.put, config, checkpoint, metadata, new_versions, *args, **kwargs
            )

        async def _aput_writes(
            self: Any,
            config: Any,
            writes: Any,
            task_id: Any,
            task_path: Any = "",
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            return await asyncio.to_thread(
                self.put_writes, config, writes, task_id, task_path, *args, **kwargs
            )

        _Compat.aget_tuple = _aget_tuple  # type: ignore[method-assign]
        _Compat.aput = _aput  # type: ignore[method-assign]
        _Compat.aput_writes = _aput_writes  # type: ignore[method-assign]

    return obj


def _memory_saver() -> Any:
    try:
        from langgraph.checkpoint.memory import MemorySaver

        return _compatify(MemorySaver())
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
    """A file every process on this host shares — dev and single-node deploys.

    Raises to the caller on purpose: falling back silently to memory is how
    the "durable" claim went untrue in the first place. `get_checkpointer`
    decides what a construction failure means.
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
    try:
        # WAL: readers (a second worker process) do not block the writer.
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass  # network filesystems refuse WAL — durability still holds
    return _compatify(SqliteSaver(conn), async_via_thread=True)


def _postgres_saver(dsn: str) -> Any:
    clean = (
        dsn.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )
    from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore[import-not-found]

    saver = PostgresSaver.from_conn_string(clean)
    # Some versions return a context manager / need setup().
    if hasattr(saver, "setup"):
        try:
            saver.setup()
        except Exception:
            pass
    return _compatify(saver)


def resolve_checkpoint_backend() -> str:
    """Explicit env wins; otherwise derive from the deployment.

    The old default was unconditionally "memory" — which meant the sqlite and
    postgres branches below could never be reached without setting the env
    var yourself, and nobody did.
    """
    explicit = (os.environ.get("LANGGRAPH_CHECKPOINT") or "").strip().lower()
    if explicit in {"memory", "sqlite", "postgres"}:
        return explicit
    try:
        from app.config import get_settings

        return "sqlite" if get_settings().use_sqlite else "postgres"
    except Exception:
        return "sqlite"


def get_checkpointer() -> Any:
    """
    Process-wide checkpointer singleton.

    Safe to call from FastAPI and ARQ worker. A backend that cannot be
    constructed falls back to memory with a DURABILITY-LOST warning: better a
    loud log than a resume that quietly cannot happen.
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    backend = resolve_checkpoint_backend()
    saver: Any | None = None
    try:
        from app.config import get_settings

        settings = get_settings()
        if backend == "memory":
            saver = _memory_saver()
        elif backend == "sqlite":
            saver = _sqlite_saver(settings.checkpoint_sqlite_path)
        else:
            saver = _postgres_saver(settings.database_url_sync)
    except Exception as exc:
        logger.warning(
            "LangGraph checkpointer backend=%s unavailable (%s) — DURABILITY LOST: "
            "falling back to in-memory, checkpoints die with this process. "
            "Runs still converge (nodes are idempotent recomputes) but resume "
            "starts from scratch.",
            backend,
            exc,
            exc_info=True,
        )
        saver = None
    if saver is None:
        backend = "memory(fallback)"
        saver = _memory_saver()

    _CHECKPOINTER = saver
    logger.info(
        "LangGraph checkpointer ready: backend=%s type=%s",
        backend,
        type(saver).__name__,
    )
    return saver


def reset_checkpointer() -> None:
    """Drop the singleton — tests reconfigure the backend between cases."""
    global _CHECKPOINTER
    _CHECKPOINTER = None


def checkpoint_config(thread_id: str, *, run_config: Any = None) -> dict[str, Any]:
    """Build ainvoke config dict with thread_id for resume."""
    configurable: dict[str, Any] = {"thread_id": str(thread_id), "checkpoint_ns": ""}
    if run_config is not None:
        configurable["run_config"] = run_config
    return {"configurable": configurable}
