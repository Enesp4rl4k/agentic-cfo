"""Plan v10 §O1 — a managed Postgres wants TLS, and the two drivers spell it differently.

asyncpg (the app) takes `?ssl=require`; psycopg (the LangGraph checkpointer and the
agent memory) takes `?sslmode=require`. One query string handed to both breaks one of
them, so each URL is written for its own driver from a single setting.
"""
from __future__ import annotations

import pytest

from app.config import Settings


def _pg(**over: object) -> Settings:
    return Settings(
        use_sqlite=False, postgres_host="db.example.com", postgres_user="u", postgres_password="p",
        postgres_db="aicfo", database_url_override="", **over,  # type: ignore[arg-type]
    )


def test_without_a_mode_nothing_is_added():
    s = _pg()
    assert s.database_url == "postgresql+asyncpg://u:p@db.example.com:5432/aicfo"
    assert s.database_url_sync == "postgresql://u:p@db.example.com:5432/aicfo"


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_each_driver_gets_its_own_spelling_of_the_mode(mode):
    s = _pg(postgres_sslmode=mode)
    assert s.database_url.endswith(f"/aicfo?ssl={mode}")
    assert s.database_url_sync.endswith(f"/aicfo?sslmode={mode}")


def test_an_unknown_mode_is_refused_rather_than_sent_to_the_driver():
    with pytest.raises(ValueError, match="postgres_sslmode"):
        _pg(postgres_sslmode="sometimes")


def test_an_override_written_for_psycopg_is_translated_for_asyncpg():
    s = Settings(use_sqlite=False, database_url_override="postgresql+asyncpg://u:p@h:5432/d?sslmode=require")
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d?ssl=require"
    assert s.database_url_sync == "postgresql://u:p@h:5432/d?sslmode=require"


def test_an_override_written_for_asyncpg_is_translated_for_psycopg():
    s = Settings(use_sqlite=False, database_url_override="postgresql+asyncpg://u:p@h:5432/d?ssl=verify-full")
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d?ssl=verify-full"
    assert s.database_url_sync == "postgresql://u:p@h:5432/d?sslmode=verify-full"


def test_other_query_parameters_of_an_override_survive():
    s = Settings(use_sqlite=False,
                 database_url_override="postgresql+asyncpg://u:p@h:5432/d?sslmode=require&application_name=aicfo")
    assert "application_name=aicfo" in s.database_url
    assert "application_name=aicfo" in s.database_url_sync
    assert "sslmode" not in s.database_url
    assert "ssl=" not in s.database_url_sync


def test_an_override_without_a_mode_is_left_as_written():
    url = "postgresql+asyncpg://u:p@h:5432/d"
    s = Settings(use_sqlite=False, database_url_override=url)
    assert s.database_url == url
    assert s.database_url_sync == "postgresql://u:p@h:5432/d"


def test_sqlite_is_untouched():
    s = Settings(use_sqlite=True, database_url_override="", postgres_sslmode="require")
    assert s.database_url == "sqlite+aiosqlite:///./aicfo_dev.db"
    assert s.database_url_sync == "sqlite:///./aicfo_dev.db"
