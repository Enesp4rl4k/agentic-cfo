"""The session factory can be the first thing to touch the database.

session_factory() held the module lock while calling engine(), which took the
same non-reentrant lock when no engine existed yet. On SQLite the lifespan
builds the engine first (create_all), so nothing noticed. On Postgres the
lifespan skips create_all, the first request's get_db was the first caller,
and the event loop thread deadlocked on itself: every request that touched the
database hung forever while /health kept answering. Found by the CI load
baseline, the first time the API ran against Postgres.
"""
from __future__ import annotations

import threading

import app.database as database


def test_session_factory_builds_the_engine_when_none_exists(monkeypatch):
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    built = []

    def call():
        built.append(database.session_factory())

    t = threading.Thread(target=call, daemon=True)
    t.start()
    t.join(timeout=10)
    try:
        assert not t.is_alive(), "session_factory() deadlocked building the engine"
        assert built and database._engine is not None
    finally:
        eng = database._engine
        if eng is not None and not t.is_alive():
            eng.sync_engine.dispose()
