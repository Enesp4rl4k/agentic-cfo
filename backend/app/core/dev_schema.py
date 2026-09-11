"""SQLite geliştirme veritabanını modellerle aynı hizada tut — yalnızca ekleyerek.

Dev mode runs `Base.metadata.create_all` at startup. That creates tables that
are missing and never touches ones that exist, so every column added since a
developer's `aicfo_dev.db` was first created is absent from it — and the app
fails on the first query that names one ("no such column: transactions.
kdv_kurus"). The local database is not alembic-stamped either, so `alembic
upgrade head` fails at migration 001 on "table already exists".

This closes the gap the narrow way: Alembic's own model/database comparison,
of which only one kind of difference is acted on — a column the model has and
the table lacks. Nothing is dropped, altered or retyped; a column that cannot
be added to a populated table (NOT NULL with no server default) is reported,
not forced. Production does not run this: PostgreSQL goes through migrations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


@dataclass
class SchemaSync:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # NOT NULL, no default


def sync_dev_schema(conn: Connection, metadata: sa.MetaData) -> SchemaSync:
    """Add the columns `metadata` declares and the database lacks.

    Run after `create_all`, inside the same connection. Every other difference
    Alembic reports is ignored on purpose: this is not a migration tool, it is
    the one repair `create_all` cannot make.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    ops = Operations(ctx)
    result = SchemaSync()

    for diff in compare_metadata(ctx, metadata):
        if not isinstance(diff, tuple) or diff[0] != "add_column":
            continue
        _op, _schema, table, column = diff
        name = f"{table}.{column.name}"
        if not column.nullable and column.server_default is None:
            # SQLite cannot add a NOT NULL column without a default to a table
            # that has rows, and inventing a default would put a value in every
            # existing row that nobody chose.
            result.skipped.append(name)
            continue
        ops.add_column(
            table,
            sa.Column(
                column.name,
                column.type,
                nullable=column.nullable,
                server_default=column.server_default,
            ),
        )
        result.added.append(name)

    if result.added:
        logger.warning("SQLite dev şeması güncellendi, eklenen kolonlar: %s", ", ".join(result.added))
    if result.skipped:
        logger.error(
            "SQLite dev şemasında eksik ama eklenemeyen kolonlar (NOT NULL, varsayılansız): %s "
            "— veritabanını yeniden oluşturun",
            ", ".join(result.skipped),
        )
    return result
