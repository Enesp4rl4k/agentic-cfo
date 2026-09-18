#!/usr/bin/env python
"""Does the database the migrations build match the models? A ratchet, not a wish.

`alembic check` fails on any difference. Against Postgres it found 82: four
tables the models use that no migration ever created (SMMM approvals, in-app
notifications, agent jobs, alert preferences) — fixed by migration 037 — and
a long tail of legacy differences that break nothing: tables the services
reach with SQL rather than models, columns the models stopped reading, index
names from before the models declared their own.

This check fails when
  - the models need a table or column the migrations do not create (never
    acceptable: that is a feature that breaks on a migrated database), or
  - a difference appears that is not in backend/alembic/known_drift.txt, or
  - an entry in known_drift.txt no longer occurs (delete it — shrink only).

Run from backend/ with DATABASE_URL_OVERRIDE pointing at a database that
`alembic upgrade head` has just built:

    python ../scripts/schema_drift.py            # check
    python ../scripts/schema_drift.py --write    # rewrite the baseline (review the diff)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
BASELINE = BACKEND / "alembic" / "known_drift.txt"
sys.path.insert(0, str(BACKEND))
warnings.filterwarnings("ignore")

# A model needing something the database lacks is a runtime failure, not drift.
NEVER_BASELINED = ("add_table", "add_column")


def _describe(diff) -> str:
    kind = diff[0]
    if kind in ("add_table", "remove_table"):
        return f"{kind} {diff[1].name}"
    if kind in ("add_column", "remove_column"):
        return f"{kind} {diff[2]}.{diff[3].name}"
    if kind in ("add_index", "remove_index"):
        ix = diff[1]
        return f"{kind} {ix.table.name}.{ix.name} ({', '.join(c.name for c in ix.columns)}) unique={bool(ix.unique)}"
    if kind in ("add_constraint", "remove_constraint"):
        c = diff[1]
        return f"{kind} {c.table.name}.{c.name or type(c).__name__}"
    if kind in ("add_fk", "remove_fk"):
        fk = diff[1]
        cols = ", ".join(c.name for c in fk.columns)
        return f"{kind} {fk.table.name}({cols}) -> {fk.referred_table.name}"
    if kind in ("modify_type", "modify_nullable", "modify_default", "modify_comment"):
        return f"{kind} {diff[2]}.{diff[3]}: {diff[5]!r} -> {diff[6]!r}"
    return repr(diff)


def _flatten(diffs):
    for d in diffs:
        if isinstance(d, list):          # column modifications come grouped
            yield from _flatten(d)
        else:
            yield d


def main() -> int:
    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401 — register every model
    from app.config import get_settings
    from app.database import Base

    url = get_settings().database_url_sync
    engine = sa.create_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diffs = list(_flatten(compare_metadata(ctx, Base.metadata)))

    found = sorted({_describe(d) for d in diffs})
    fatal = [f for f in found if f.split(" ", 1)[0] in NEVER_BASELINED]

    if "--write" in sys.argv:
        if fatal:
            print("Refusing to baseline what the models need and the migrations lack:")
            print("\n".join(f"  {f}" for f in fatal))
            return 1
        BASELINE.write_text("\n".join(found) + "\n", encoding="utf-8")
        print(f"wrote {len(found)} entries to {BASELINE}")
        return 0

    known = {line.strip() for line in BASELINE.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")} if BASELINE.exists() else set()
    new = [f for f in found if f not in known]
    gone = sorted(known - set(found))

    ok = True
    if fatal:
        ok = False
        print("FAIL: The models use tables/columns no migration creates (write a migration):")
        print("\n".join(f"    {f}" for f in fatal))
    if new := [f for f in new if f not in fatal]:
        ok = False
        print("FAIL: New schema drift (write a migration, or fix the model):")
        print("\n".join(f"    {f}" for f in new))
    if gone:
        ok = False
        print("FAIL: Fixed drift still listed — delete these lines from alembic/known_drift.txt:")
        print("\n".join(f"    {f}" for f in gone))
    if ok:
        print(f"OK: schema matches the models, apart from {len(found)} known legacy differences")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
