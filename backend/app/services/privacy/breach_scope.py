"""Scope a breach from the registry: which companies, which categories of personal data, which kinds of people.

`python -m app.services.privacy.breach_scope uploads outbox_messages audit_logs` (from `backend/`, with the
production DATABASE_URL in the environment) prints, for each compromised table or store, the categories of data it
holds, whose data it is, and per company how many rows are in it. Counts only: no row content is read or printed.
The company ids are random UUIDs, not personal data. The output answers the questions a breach record needs
(`POST /compliance/gdpr/breach-notification`): which data, whose, and an estimate of how many; the person who
decides what to tell the authority and the companies is the owner (runbook `docs/ops/runbooks/data-breach.md`).
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.services.org_erasure import derive_scope
from app.services.privacy.registry_stores import STORES
from app.services.privacy.registry_tables import TABLES


def _describe_table(name: str) -> dict[str, Any]:
    meta = TABLES[name]
    return {"kind": "table", "subject": meta.subject.value, "categories": sorted({c.value for c in meta.columns.values()}),
            "columns": sorted(meta.columns), "third_parties": [f.value for f in meta.flows]}


def _describe_store(key: str) -> dict[str, Any]:
    store = next(s for s in STORES if s.key == key)
    return {"kind": "store", "subject": store.subject.value, "holds": store.holds, "where": store.where,
            "third_parties": [f.value for f in store.flows]}


async def _per_org(db: AsyncSession, table: str) -> dict[str, int] | None:
    """Rows per organisation for an org-scoped table; None when the table has no organisation link."""
    t = Base.metadata.tables[table]
    if "org_id" in t.c:
        rows = (await db.execute(select(t.c.org_id, func.count()).group_by(t.c.org_id))).all()
        return {str(o): int(n) for o, n in rows if o is not None}
    if table == "users":
        m = Base.metadata.tables["org_memberships"]
        rows = (await db.execute(select(m.c.org_id, func.count()).group_by(m.c.org_id))).all()
        return {str(o): int(n) for o, n in rows}
    if table in derive_scope():  # reached through a parent (transactions -> analysis_jobs)
        parent = next((p for _, p, _ in derive_scope()[table][1]), None)
        if parent and parent != table:
            return await _per_org(db, parent)
    return None


async def scope(db: AsyncSession, keys: list[str]) -> dict[str, Any]:
    """The breach scope for the named registry tables and stores."""
    unknown = [k for k in keys if k not in TABLES and k not in {s.key for s in STORES}]
    if unknown:
        raise ValueError(f"not in the registry: {unknown}")
    out: dict[str, Any] = {}
    for key in keys:
        info = _describe_table(key) if key in TABLES else _describe_store(key)
        if key in TABLES:
            info["rows_per_organisation"] = await _per_org(db, key)
        elif key in ("uploads", "report_files", "board_decks"):
            info["rows_per_organisation"] = await _per_org(db, "analysis_jobs")
            info["note"] = "one file set per upload job; the job count per organisation, not the file count"
        out[key] = info
    organisations = sorted({o for v in out.values() for o in (v.get("rows_per_organisation") or {})})
    return {"keys": out, "organisations": organisations, "organisation_count": len(organisations),
            "categories": sorted({c for v in out.values() for c in v.get("categories", [])}),
            "subjects": sorted({v["subject"] for v in out.values()})}


async def _main(keys: list[str]) -> int:  # pragma: no cover - a CLI over the production database
    from app.database import engine, get_session_factory

    async with get_session_factory(engine())() as db:
        sys.stdout.write(json.dumps(await scope(db, keys), indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import app.models  # noqa: F401

    sys.exit(asyncio.run(_main(sys.argv[1:])))
