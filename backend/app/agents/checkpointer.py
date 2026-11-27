"""
LangGraph checkpointer factory — durable per-step state of CFO pipeline runs (nothing resumes it today).

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

Thread id convention: `<org_id>:<job_id>:<run_id>` (`thread_key`), built ONLY by `checkpoint_config` (a structural
test, `tests/test_checkpoint_thread_ids.py`, fails on any other construction). The organisation prefix is what keeps
one tenant from ever loading another's checkpoint and what organisation erasure selects on. The run id is fresh for
every run (`run_cfo_pipeline`): no production code resumes a checkpoint, so a run must not start on top of an earlier
run's channel values, and two runs on one job must not write one thread. A run without an organisation (a job whose
`org_id` is NULL) is NOT checkpointed at all: `run_cfo_pipeline` runs it on a graph compiled without a checkpointer,
because a row that does not start with its organisation is a row no erasure can find.

Nothing reads the durable rows back today (no resume, no inspection tool); they exist for at most
`RETENTION_CHECKPOINT_DAYS` (default 3). Deserialisation is strict (`_serde`): only the library's safe types and the
app's own state dataclasses are rebuilt from a row, anything else comes back as plain data.

Production never falls back: LANGGRAPH_CHECKPOINT=postgres (or sqlite) that cannot be built raises
`CheckpointerUnavailable` there, and startup stops (`verify_checkpointer`, called by the API lifespan and the
workers). Development and tests fall back to memory with a DURABILITY LOST warning.

Tables (Postgres): `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations` belong to the
langgraph library, not to Alembic. `_postgres_saver` creates them (idempotent `setup()` under an advisory lock, so
two processes starting together do not race). They hold agent state, which can contain company data: see
`erase_org_checkpoints` and `purge_old_checkpoints`.
"""
from __future__ import annotations

import inspect
import logging
import os
from typing import TYPE_CHECKING, Any, TypeGuard, cast

if TYPE_CHECKING:
    from langgraph.checkpoint.base import CheckpointMetadata

from app.services.checkpoint_data import (  # noqa: F401  (re-exported)
    CHECKPOINT_DATA_TABLES,
    LIBRARY_TABLES,
    erase_org_checkpoints,
    purge_old_checkpoints,
    thread_key,
    thread_like,
)

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None
_STATUS: dict[str, Any] = {"backend": None, "durable": None, "error": None}

_SETUP_LOCK_KEY = 7_302_411_901  # pg_advisory_lock key: one process runs the library's setup() at a time


class CheckpointerUnavailable(RuntimeError):
    """The configured durable checkpointer cannot be built, and this process is a production one."""


def _production() -> bool:
    try:
        from app.config import get_settings
        from app.core.preflight import is_production

        return is_production(get_settings())
    except Exception:
        return False


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


# The app's own types that live in CFO state (`logs` holds StepLog; the run config may be stored with a run).
STATE_TYPES: tuple[tuple[str, str], ...] = (
    ("app.agents.state", "StepLog"),
    ("app.agents.state", "AgentRunConfig"),
)

# The CFO graph is acyclic with 13 nodes (one super-step each); 25 leaves room and still stops a routing loop.
RECURSION_LIMIT = 25


def _serde() -> Any:
    """Strict msgpack: a checkpoint row can rebuild only the library's safe types and `STATE_TYPES`.

    The library's default allows any importable type (with a warning), so a row written by anyone who can write to
    these tables could construct arbitrary objects when it is read (GHSA-g48c-2wqr-h844). Blocked types come back as
    their plain serialised data."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


def _memory_saver() -> Any:
    try:
        from langgraph.checkpoint.memory import MemorySaver

        return _compatify(MemorySaver(serde=_serde()))
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
    return _compatify(SqliteSaver(conn, serde=_serde()), async_via_thread=True)


def _acquire_setup_lock(conn: Any, timeout: float = 90.0) -> None:
    """Take the setup advisory lock by POLLING `pg_try_advisory_lock`, never by blocking on it.

    The library's migrations include CREATE INDEX CONCURRENTLY, which waits for every other transaction that is
    open. A second process blocked inside `pg_advisory_lock` IS such a transaction: the first would wait for it
    and it for the first (both API workers hung at startup on a fresh database). A poll is over in a moment."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        row = conn.execute("SELECT pg_try_advisory_lock(%s) AS got", (_SETUP_LOCK_KEY,)).fetchone()
        if row and row["got"]:
            return
        if time.monotonic() > deadline:
            raise TimeoutError("another process holds the checkpoint setup lock")
        time.sleep(0.25)


def _postgres_saver(dsn: str) -> Any:
    """A durable saver on a psycopg connection pool; creates the library's tables if they are missing.

    Sync `PostgresSaver` over a thread-safe `ConnectionPool` (autocommit, as the library requires: its index
    migrations run CONCURRENTLY). The graphs run async, so the async methods hop to a worker thread
    (`_compatify(..., async_via_thread=True)`), exactly as the SQLite saver does: checkpoints are written once per
    super-step, and a thread hop is cheaper than binding a pool to one event loop (the API and the ARQ workers each
    have their own). Raises to the caller on purpose: `get_checkpointer` decides what a failure means.
    """
    clean = (
        dsn.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        clean,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
        name="langgraph-checkpoints",
    )
    pool.open(wait=True, timeout=15)
    try:
        saver = PostgresSaver(cast("Any", pool), serde=_serde())
        with pool.connection() as lock_conn:  # session-level advisory lock, held while setup() runs on another one
            _acquire_setup_lock(lock_conn)
            try:
                saver.setup()
            finally:
                lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_SETUP_LOCK_KEY,))
    except Exception:
        pool.close()
        raise
    return _compatify(saver, async_via_thread=True)


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
        failure = exc
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
        failure = exc
    if saver is None:
        if backend != "memory" and _production():
            _STATUS.update(backend=backend, durable=False, error=type(failure).__name__)
            raise CheckpointerUnavailable(
                f"LANGGRAPH_CHECKPOINT={backend} cannot be built ({type(failure).__name__}: {failure}); "
                "production does not fall back to per-process memory, which would lose every run on restart "
                "and make resume in another process impossible"
            ) from failure
        _STATUS.update(backend="memory(fallback)", durable=False, error=type(failure).__name__)
        backend = "memory(fallback)"
        saver = _memory_saver()
    else:
        _STATUS.update(backend=backend, durable=backend != "memory", error=None)

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
    _STATUS.update(backend=None, durable=None, error=None)


def persists(org_id: str | None) -> TypeGuard[str]:
    """Whether a run for this organisation may be checkpointed durably: only with an organisation UUID."""
    from app.services.privacy.erasure_cleanup import valid_id

    return valid_id(org_id)


def checkpoint_config(job_id: str, *, org_id: str, run_id: str, run_config: Any = None) -> dict[str, Any]:
    """The ainvoke config of a CHECKPOINTED run: thread `<org_id>:<job_id>:<run_id>`, explicit recursion limit.

    Fails closed: without an organisation UUID it raises `InvalidTargetError` and nothing is written. A caller that
    may have no organisation checks `persists(org_id)` first and runs uncheckpointed (`ephemeral_config`)."""
    configurable: dict[str, Any] = {"thread_id": thread_key(org_id, str(job_id), str(run_id)), "checkpoint_ns": ""}
    if run_config is not None:
        configurable["run_config"] = run_config
    return {"recursion_limit": RECURSION_LIMIT, "configurable": configurable}


def ephemeral_config(run_config: Any = None) -> dict[str, Any]:
    """The ainvoke config of a run on a graph compiled WITHOUT a checkpointer: no thread id, nothing persisted."""
    configurable: dict[str, Any] = {}
    if run_config is not None:
        configurable["run_config"] = run_config
    return {"recursion_limit": RECURSION_LIMIT, "configurable": configurable}


def checkpointer_status() -> dict[str, Any]:
    """What `/ready` reports: builds the saver if this process has not yet, then says whether it is durable.

    `durable` is True for postgres/sqlite, False for the memory fallback, None for memory chosen on purpose.
    """
    try:
        get_checkpointer()
    except CheckpointerUnavailable:
        pass
    backend = _STATUS["backend"]
    durable: bool | None = _STATUS["durable"]
    if backend == "memory":
        durable = None  # chosen explicitly (tests, throw-away runs): not a failure
    return {"backend": backend, "durable": durable, "error": _STATUS["error"]}


def verify_checkpointer() -> None:
    """Build the checkpointer now. Production: raises `CheckpointerUnavailable` (the process must not start).
    Elsewhere a failure is only the logged fallback. Called by the API lifespan and by the workers."""
    get_checkpointer()
