"""
Alembic environment — async SQLAlchemy engine.

Run migrations:
  cd backend
  alembic upgrade head        # apply all pending migrations
  alembic revision --autogenerate -m "describe change"  # generate new migration
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models.agent_conflict
import app.models.agent_job
import app.models.agent_run
import app.models.alert_preference
import app.models.analysis_job
import app.models.anomaly
import app.models.audit_log
import app.models.authority_policy
import app.models.canonical_eng_signal
import app.models.canonical_transaction
import app.models.cash_radar_snapshot
import app.models.category_rule
import app.models.company_context
import app.models.company_semantic_snapshot
import app.models.connector_connection
import app.models.data_source
import app.models.defensibility_packet
import app.models.erp_integration
import app.models.in_app_notification
import app.models.institutionalization_snapshot
import app.models.llm_call_log
import app.models.organization
import app.models.pilot
import app.models.rag_chunk
import app.models.report
import app.models.smmm_onay
import app.models.smmm_portal
import app.models.sync_run
import app.models.transaction
import app.models.trigger
import app.models.user  # noqa: F401
from alembic import context
from app.config import get_settings

# ── Import all models so Alembic can detect schema changes ────────────────────
from app.database import Base

# Alembic Config object — gives access to .ini values
config = context.config

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata

# Override sqlalchemy.url with the real DB URL from Settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — no live DB connection needed.
    Useful for generating SQL scripts.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using the async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to a live DB."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
