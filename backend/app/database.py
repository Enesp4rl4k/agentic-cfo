"""
Database module — async SQLAlchemy engine and session factory.

SOLID-2 fix: replaced bare global mutable variables with threading.Lock-guarded
initialization to prevent race conditions under multi-threaded startup.

PERF-3 fix: engine is created once and cached; subsequent calls are O(1)
lock checks rather than rebuilding the engine.

Usage:
    # In FastAPI endpoints (dependency injection):
    async def my_endpoint(db: AsyncSession = Depends(get_db)):
        ...

    # In background tasks / scripts:
    from app.database import session_factory
    async with session_factory()() as db:
        ...
"""
from __future__ import annotations

import threading

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# ── Thread-safe singleton engine ──────────────────────────────────────────────

_engine = None
_session_factory = None
_lock = threading.Lock()


def _build_engine():
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        kwargs: dict = {
            "echo": False,
            "connect_args": {"check_same_thread": False},
        }
    else:
        kwargs = {
            "echo": False,
            "pool_pre_ping": True,
            "pool_size": 20,
            "max_overflow": 10,
            "pool_recycle": 1800,
        }
    return create_async_engine(settings.database_url, **kwargs)


def engine():
    """Return the singleton async engine. Thread-safe initialization."""
    global _engine
    if _engine is None:
        with _lock:
            # Double-checked locking pattern
            if _engine is None:
                _engine = _build_engine()
    return _engine


def session_factory():
    """Return the singleton async_sessionmaker. Thread-safe initialization."""
    global _session_factory
    if _session_factory is None:
        with _lock:
            if _session_factory is None:
                _session_factory = async_sessionmaker(
                    engine(),
                    expire_on_commit=False,
                    class_=AsyncSession,
                )
    return _session_factory


# ── Public helpers ────────────────────────────────────────────────────────────

def get_engine():
    """Alias for engine() — kept for backward compatibility."""
    return engine()


def get_session_factory(eng=None):
    """
    Return session factory for a given engine.

    If eng is None, uses the singleton engine.
    Useful in tests where you want to inject a test engine.
    """
    if eng is None:
        return session_factory()
    return async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields an async session, auto-closed on exit."""
    async with session_factory()() as session:
        yield session
