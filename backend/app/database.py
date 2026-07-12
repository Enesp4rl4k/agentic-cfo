from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Module-level singletons — created once, reused across requests
_engine = None
_session_factory = None


def engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory(engine())
    return _session_factory


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with session_factory()() as session:
        yield session
