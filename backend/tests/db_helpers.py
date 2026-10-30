"""A throwaway database per test, with a real connection per session.

Tests used `sqlite+aiosqlite:///:memory:`, which SQLAlchemy serves with
StaticPool: every session on the engine shares ONE sqlite connection, so the
sessions are not isolated from each other. A session's uncommitted writes are
visible to the others, and any session that closes with a transaction open
(a test polling a row, a request's `get_db`) issues ROLLBACK on that shared
connection — discarding another session's INSERT/UPDATE that has run but not
yet committed. Its `commit()` then succeeds with nothing to commit. Code that
writes from a background task (the review continuation, the worker,
`app.core.background.spawn`) while a test or a request reads through another
session lost writes this way, at random, depending on how the event loop
interleaved the two: the "flaky" approval, category-rule and company-view
tests.

A file gets a normal pool: one connection per session, real transaction
isolation, and SQLite's own locking serialises writers, as Postgres would.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_DIR = tempfile.mkdtemp(prefix="aicfo_test_db_")
atexit.register(shutil.rmtree, _DIR, ignore_errors=True)


def gecici_motor(**kwargs: Any) -> AsyncEngine:
    """An engine on a fresh SQLite file, deleted when the engine is disposed."""
    path = os.path.join(_DIR, f"{uuid.uuid4().hex}.db")
    kwargs.setdefault("connect_args", {}).setdefault("timeout", 30)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", **kwargs)

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        # WAL: readers and the writer do not block each other, closer to
        # Postgres than rollback-journal locking. Durability is not the point
        # of a throwaway file, so no fsync.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=OFF")
        cur.close()

    @event.listens_for(engine.sync_engine, "engine_disposed")
    def _sil(_engine: Any) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass

    return engine
