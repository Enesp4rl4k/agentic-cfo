"""The erasure tombstone on EVERY database write of company data, enforced by the session, not by each caller.

Listing write paths by hand missed one (review of #164: the post-analysis continuation wrote the company context,
the semantic snapshot and the brief after an erasure committed). So the check sits where every write passes:

* `before_flush` (every ORM add / change): each new or changed row of an organisation-scoped table
  (`org_erasure.derive_scope`, the erasure's own table inventory) is resolved to its organisation, directly by its
  `org_id` or through the link the erasure itself follows (`transactions.job_id -> analysis_jobs.org_id`, ...);
* `do_orm_execute` (every `session.execute` of a Core INSERT / UPDATE / upsert): the organisation is read from the
  inserted values, from the values an UPDATE sets, or from an `org_id = ...` / `org_id IN (...)` (or link column)
  condition of its WHERE clause.

For each organisation found, `tombstone.refuse_if_erased` runs before the statement: the organisation's advisory lock
SHARED for the rest of the transaction, then the tombstone; `OrgErasedError` when it is set. DELETEs are never
refused (removing data is what erasure wants). What cannot be resolved (an UPDATE by primary key alone) is not
refused here: the explicit guards of the analysis paths and the final sweep, which re-runs the erasure's own plan
(`tombstone.sweep_erased_org`), cover it.

Cost, measured by `tests/test_write_guard.py`: on PostgreSQL two short statements (the lock, the tombstone read) per
organisation per TRANSACTION, not per write: the answer is cached on the transaction (`session.info`) and dropped when
it ends. The cache cannot hide an erasure: while the transaction holds the shared lock, no erasure of that company can
commit. SQLite has no such lock, so there the read is repeated on every flush (still no false negative).

Exempt (`exempt(session)`): the erasure's own transaction and the final sweep, which write the scrubbed values of the
company they are erasing under its exclusive lock.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.sql import visitors
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

logger = logging.getLogger(__name__)

EXEMPT = "erasure_writer"
# Organisation-scoped tables whose writes are not refused, each with the reason (the structural test requires one).
# Erasure still deletes their rows, and the final sweep does again.
EXEMPT_TABLES: dict[str, str] = {
    "scheduled_job_runs": "the scheduler's idempotency ledger (a job name, a period, a short error code): no company "
                          "data, and its claim must not wait on a company's lock",
}
_CHECKED = "tombstone_checked"
_INSTALLED = {"done": False}
_SCOPE: dict[str, tuple[str | None, tuple[str, str, str] | None]] = {}


def _scope() -> dict[str, tuple[str | None, tuple[str, str, str] | None]]:
    """table -> (its own org column or None, (link column, parent table, parent column) or None). Built once from the
    erasure's derived scope, so a table the erasure covers is a table this guard covers."""
    if not _SCOPE:
        import app.models  # noqa: F401  (every table registered)
        from app.services.org_erasure import derive_scope

        for name, (direct, links) in derive_scope().items():
            if name not in EXEMPT_TABLES:
                _SCOPE[name] = ("org_id" if direct else None, links[0] if links else None)
    return _SCOPE


def covered_tables() -> dict[str, str]:
    """For the structural test and the PR: every organisation-scoped table and how a write to it is resolved."""
    out = {name: f"exempt: {why}" for name, why in EXEMPT_TABLES.items()}
    for name, (direct, link) in sorted(_scope().items()):
        out[name] = "org_id" if direct else (f"{link[0]} -> {link[1]}.{link[2]}" if link else "unresolved")
    return dict(sorted(out.items()))


@contextmanager
def exempt(session: Any) -> Iterator[None]:
    """The erasure's own writes (and the final sweep): not refused by the tombstone they are creating."""
    info = session.info
    before = info.get(EXEMPT)
    info[EXEMPT] = True
    try:
        yield
    finally:
        if before is None:
            info.pop(EXEMPT, None)
        else:
            info[EXEMPT] = before


def _check(session: Session, orgs: Iterable[str]) -> None:
    """Refuse when one of these organisations is being erased (sync: runs inside the flush / execute event)."""
    from app.services.privacy.erasure_cleanup import valid_id
    from app.services.privacy.tombstone import OrgErasedError, org_hash, tombstone_clause

    if session.info.get(EXEMPT):
        return
    wanted = {o for o in orgs if valid_id(o)}
    if not wanted:
        return
    postgres = session.get_bind().dialect.name == "postgresql"
    checked: set[str] = session.info.setdefault(_CHECKED, set()) if postgres else set()
    from sqlalchemy import func, select

    from app.services.org_erasure import org_lock_key

    for org in sorted(wanted - checked):
        with session.no_autoflush:
            if postgres:
                session.execute(select(func.pg_advisory_xact_lock_shared(org_lock_key(org))))
            erased = bool(session.execute(select(tombstone_clause(org_hash(org)))).scalar())
        if erased:
            logger.warning("write refused: the organisation is being erased or was erased")
            raise OrgErasedError()
        checked.add(org)


def _parent_org(session: Session, table: str, value: Any, depth: int = 0) -> str | None:
    """The organisation of a parent row (`transactions.job_id` -> the job's `org_id`), following the erasure's links."""
    if value is None or depth > 4:
        return None
    from sqlalchemy import select

    from app.database import Base

    direct, link = _scope().get(table, (None, None))
    t = Base.metadata.tables[table]
    cache: dict[tuple[str, str], str | None] = session.info.setdefault("tombstone_parents", {})
    key = (table, str(value))
    if key in cache:
        return cache[key]
    pk = next(iter(t.primary_key.columns))
    with session.no_autoflush:
        if direct:
            org = session.execute(select(t.c.org_id).where(pk == value)).scalar_one_or_none()
        elif link:
            parent_value = session.execute(select(t.c[link[0]]).where(pk == value)).scalar_one_or_none()
            org = _parent_org(session, link[1], parent_value, depth + 1)
        else:
            org = None
    cache[key] = None if org is None else str(org)
    return cache[key]


def _row_org(session: Session, table: str, values: dict[str, Any]) -> str | None:
    direct, link = _scope().get(table, (None, None))
    if direct and values.get("org_id") is not None:
        return str(values["org_id"])
    if link and values.get(link[0]) is not None and link[2] == "id":
        return _parent_org(session, link[1], values[link[0]])
    return None


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    if session.info.get(EXEMPT):
        return
    scope = _scope()
    orgs: set[str] = set()
    for obj in list(session.new) + list(session.dirty):
        table = getattr(getattr(obj, "__table__", None), "name", None)
        if table not in scope:
            continue
        if obj in session.dirty and not session.is_modified(obj, include_collections=False):
            continue
        direct, link = scope[table]
        values = {}
        if direct:
            values["org_id"] = getattr(obj, "org_id", None)
        if link:
            values[link[0]] = getattr(obj, link[0], None)
        org = _row_org(session, table, values)
        if org:
            orgs.add(org)
    _check(session, orgs)


def _bound(value: Any) -> list[Any]:
    """The plain values behind a bind parameter, a literal or an IN list."""
    if isinstance(value, BindParameter):
        value = value.value if value.callable is None else value.callable()
    if isinstance(value, list | tuple | set | frozenset):
        return list(value)
    return [value] if value is not None else []


def _where_values(clause: Any, column: str) -> list[Any]:
    """Values compared with `column` by `=` / `IN` in a WHERE clause."""
    found: list[Any] = []
    if clause is None:
        return found
    for node in visitors.iterate(clause):
        if isinstance(node, BinaryExpression) and getattr(node.left, "name", None) == column:
            op = getattr(node.operator, "__name__", "")
            if op in ("eq", "in_op"):
                right = node.right
                if hasattr(right, "clauses"):
                    for c in right.clauses:
                        found += _bound(c)
                else:
                    found += _bound(right)
    return found


def _statement_orgs(session: Session, stmt: Any, params: Any) -> set[str]:
    table = getattr(getattr(stmt, "table", None), "name", None)
    scope = _scope()
    if table not in scope:
        return set()
    direct, link = scope[table]
    col = "org_id" if direct else (link[0] if link else None)
    if col is None:
        return set()
    raw: list[Any] = []
    rows: list[dict[str, Any]] = []
    if isinstance(params, dict):
        rows.append(params)
    elif isinstance(params, list | tuple):
        rows += [p for p in params if isinstance(p, dict)]
    multi = getattr(stmt, "_multi_values", None) or ()
    for group in multi:
        for row in group:
            if isinstance(row, dict):
                rows.append({str(getattr(k, "key", k)): v for k, v in row.items()})
    values = getattr(stmt, "_values", None) or {}
    if values:
        rows.append({str(getattr(k, "key", k)): v for k, v in values.items()})
    for row in rows:
        raw += _bound(row.get(col))
    if isinstance(stmt, Update):
        raw += _where_values(stmt.whereclause, col)
    out: set[str] = set()
    for value in raw:
        if value is None or not isinstance(value, str | int):
            continue
        org = str(value) if direct else _parent_org(session, link[1], value) if link and link[2] == "id" else None
        if org:
            out.add(org)
    return out


def _do_orm_execute(state: Any) -> None:
    stmt = state.statement
    if not isinstance(stmt, Insert | Update):  # a DELETE is never refused
        return
    session = state.session
    if session.info.get(EXEMPT):
        return
    _check(session, _statement_orgs(session, stmt, state.parameters))


def _transaction_end(session: Session, transaction: Any) -> None:
    if transaction.parent is None:  # the root transaction: its advisory locks are gone with it
        session.info.pop(_CHECKED, None)
        session.info.pop("tombstone_parents", None)


def install() -> None:
    """Register the hooks on every ORM session of this process (idempotent). Called by the API, the workers and the
    test suite at start-up."""
    if _INSTALLED["done"]:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "do_orm_execute", _do_orm_execute)
    event.listen(Session, "after_transaction_end", _transaction_end)
    _INSTALLED["done"] = True


def installed() -> bool:
    return _INSTALLED["done"]
