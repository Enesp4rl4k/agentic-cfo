"""One clock for stamps: a timestamp column the application later compares with `datetime.now()` must be
written by the application clock (app/core/clock.py), not by the database's `now()`.

A database-stamped `created_at` carries the REAL time while the app (and every test) runs on the pinned one, so
`now - created_at` was negative and the trigger cooldown always looked active. The server default stays as the
fallback for rows written outside the ORM (no migration); the ORM insert carries the clock's value.
"""
from __future__ import annotations

from sqlalchemy import DateTime

import app.models  # noqa: F401  (registers every table)
from app.database import Base


def test_every_database_stamped_timestamp_is_also_stamped_by_the_application_clock() -> None:
    bare = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, DateTime) and column.server_default is not None and column.default is None
    ]
    assert not bare, (
        "These columns are stamped only by the database's now() (real time, not the pinned clock): add "
        "`default=_utcnow` (datetime.now(UTC)) next to the server_default:\n  " + "\n  ".join(bare)
    )
