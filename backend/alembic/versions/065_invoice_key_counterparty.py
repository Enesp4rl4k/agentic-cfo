"""An invoice's ledger identity includes its counterparty and side (plan v10 gap G23).

`doc:<number>` named an invoice by its number alone, so two suppliers that both issued "A-001"
were one document: the second was dropped and one payable left the cash radar. A free-form
number (not a UUID, not a GİB 16-character number) is now keyed `inv:<s|p>:<party>:<number>`
(app/core/invoice_identity.py). This migration rewrites the existing identities to match, in
the one transaction alembic gives it:

- `canonical_transactions.source_record_id` (the ledger row), and its correction rows
  `<id>~kN-iptal|yeni` (found through `corrects_id`, which points at the row's UUID and so is
  untouched);
- `category_overrides.source_record_id` (a person's remembered correction, same string);
- `open_items.document_id` (the unique (organisation, document) index; widened to 128).

`journal_*` and `smmm_onay_kayitlari` are keyed by a hash of the source transaction's content
(`kararli_kayit_id`), not by the ledger identity, and `decisions` is append-only: neither is
touched. `audit_logs.resource` keeps the id the row had when the correction was made.

**The counterparty of an old row** is what its own import said: the open item with the same
number (written from the same transaction), else the job's `transactions` row. A row for which
neither names a counterparty (a list without a "cari" column, an erased organisation) keeps
`doc:<number>` and is counted, never guessed.

**Rows that cannot be rewritten** keep their old key and are counted, never deleted: a new key
that already exists (two rows that normalise to one document, or an open item already under the
new key). Nothing here can violate a unique index: every target is checked first.

**Wrongly merged rows** (two suppliers' same number, the second silently dropped) cannot be
un-merged by this migration: the dropped row was never stored in the ledger. Their source rows
still exist in `transactions`, so the migration counts them per organisation (documents whose
new key is not in the ledger) and logs the count. `ledger.backfill` writes them under the new
keys; nothing is invented here.

The key function is imported from `app.core.invoice_identity`, not copied: an upgrade from an
old database re-keys rows the way the application of this revision keys new ones. A later change
to the normalisation therefore needs its own migration (the keys it changes are the rows' ids).

Idempotent: a second run finds only the rows the first one could not key and does the same.
Downgrade restores `doc:<number>` where it is free; a second row for the same number (the very
rows this fixes) keeps its `inv:` key rather than collide, and the column keeps its width.

Revision ID: 065_invoice_key_counterparty
Revises: 064_decisions_table
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

import sqlalchemy as sa

from alembic import op
from app.core.invoice_identity import (
    canonical_invoice_id,
    document_key,
    is_unique_id,
    open_item_key,
)

revision = "065_invoice_key_counterparty"
down_revision = "064_decisions_table"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_DOC, _INV = "doc:", "inv:"
_DOC_LIKE, _INV_LIKE = "doc:%", "inv:%"
_KEPT_OLD, _KEPT_NEW = "kept_old_key_collision", "kept_new_key_collision"
_CHUNK = 500
_ITEM_DIRECTION = {"receivable": "income", "payable": "expense"}

# The tables, as this migration sees them (not the models: those may change later).
_ledger = sa.table(
    "canonical_transactions",
    sa.column("id"), sa.column("org_id"), sa.column("source_type"), sa.column("source_record_id"),
    sa.column("source_job_id"), sa.column("direction"), sa.column("corrects_id"), sa.column("created_at"),
)
_overrides = sa.table(
    "category_overrides", sa.column("id"), sa.column("org_id"), sa.column("source_record_id"),
)
_items = sa.table(
    "open_items", sa.column("id"), sa.column("org_id"), sa.column("direction"),
    sa.column("document_id"), sa.column("counterparty"),
)
_txs = sa.table(
    "transactions", sa.column("job_id"), sa.column("document_id"), sa.column("counterparty"),
    sa.column("type"), sa.column("amount_kurus"), sa.column("date_is_estimated"),
)
_jobs = sa.table("analysis_jobs", sa.column("id"), sa.column("org_id"), sa.column("status"))
_decisions = sa.table("decisions", sa.column("target_id"))


def _number(document_id: str) -> str:
    """The document number the ledger keyed an invoice by (`canonical_invoice_id(x) or x`)."""
    return canonical_invoice_id(document_id) or document_id


def _has(conn: sa.Connection, *tables: str) -> bool:
    present = set(sa.inspect(conn).get_table_names())
    return all(t in present for t in tables)


def _chunks(values: list[Any]) -> Iterator[list[Any]]:
    for i in range(0, len(values), _CHUNK):
        yield values[i:i + _CHUNK]


def _set_key(conn: sa.Connection, table: sa.TableClause, key_column: str, row_id: Any, new: str) -> None:
    conn.execute(sa.update(table).where(table.c.id == row_id).values({key_column: new}))


def _ledger_keys(conn: sa.Connection, like: str) -> dict[tuple[str, str], set[str]]:
    """The ledger keys of this shape in use, by (organisation, source type): the unique index's scope."""
    taken: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in conn.execute(sa.select(_ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id)
                          .where(_ledger.c.source_record_id.like(like))):
        taken[(r.org_id, r.source_type)].add(r.source_record_id)
    return taken


def _override_keys(conn: sa.Connection) -> set[tuple[str, str]] | None:
    """Every remembered override's (organisation, key); None when the table does not exist yet."""
    if not _has(conn, "category_overrides"):
        return None
    return {(r.org_id, r.source_record_id)
            for r in conn.execute(sa.select(_overrides.c.org_id, _overrides.c.source_record_id))}


def _move_dependents(
    conn: sa.Connection, row: Any, old: str, new: str,
    overrides: set[tuple[str, str]] | None, out: dict[str, int], collision: str,
) -> None:
    """What follows a ledger row's identity: its correction rows (by `corrects_id`) and its override."""
    for c in conn.execute(sa.select(_ledger.c.id, _ledger.c.source_record_id).where(
        _ledger.c.org_id == row.org_id, _ledger.c.corrects_id == row.id,
        _ledger.c.source_record_id.like(f"{old}~k%"),
    )):
        _set_key(conn, _ledger, "source_record_id", c.id, new + c.source_record_id[len(old):])
        out["correction_rows"] += 1
    if overrides is None:
        return
    for o in conn.execute(sa.select(_overrides.c.id).where(
        _overrides.c.org_id == row.org_id, _overrides.c.source_record_id == old,
    )):
        if (row.org_id, new) in overrides:
            out[collision] += 1
            continue
        overrides.add((row.org_id, new))
        _set_key(conn, _overrides, "source_record_id", o.id, new)
        out["overrides"] += 1


# ── upgrade ──────────────────────────────────────────────────────────────────────────────────


def _counterparties(conn: sa.Connection, legacy: list[Any]) -> tuple[dict[Any, str], dict[Any, str]]:
    """Counterparty by (org, number, side) from open items, and by (job, number, side) from transactions.

    The open item was written from the same transaction as the ledger row. Where it names nobody
    (a return opens no item) the job's own row does.
    """
    by_item: dict[Any, str] = {}
    for item in conn.execute(sa.select(
        _items.c.org_id, _items.c.document_id, _items.c.counterparty, _items.c.direction,
    ).where(_items.c.counterparty.is_not(None), ~_items.c.document_id.like(_INV_LIKE))):
        by_item.setdefault(
            (item.org_id, _number(item.document_id), _ITEM_DIRECTION.get(item.direction)), item.counterparty
        )
    need_job = sorted({
        r.source_job_id for r in legacy
        if r.source_job_id and (r.org_id, _number(r.source_record_id[len(_DOC):]), r.direction) not in by_item
    })
    by_job: dict[Any, str] = {}
    if need_job and _has(conn, "transactions"):
        for chunk in _chunks(need_job):
            for t in conn.execute(sa.select(
                _txs.c.job_id, _txs.c.document_id, _txs.c.counterparty, _txs.c.type,
            ).where(_txs.c.job_id.in_(chunk), _txs.c.document_id.is_not(None), _txs.c.counterparty.is_not(None))):
                by_job.setdefault((t.job_id, _number(t.document_id), t.type), t.counterparty)
    return by_item, by_job


def _rewrite_ledger(conn: sa.Connection, out: dict[str, int]) -> None:
    legacy = [
        r for r in conn.execute(sa.select(
            _ledger.c.id, _ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id,
            _ledger.c.source_job_id, _ledger.c.direction,
        ).where(_ledger.c.source_record_id.like(_DOC_LIKE), _ledger.c.corrects_id.is_(None)))
        if not is_unique_id(r.source_record_id[len(_DOC):])
    ]
    out["legacy_rows"] = len(legacy)
    by_item, by_job = _counterparties(conn, legacy)
    taken, overrides = _ledger_keys(conn, _INV_LIKE), _override_keys(conn)
    for r in legacy:
        number = _number(r.source_record_id[len(_DOC):])  # an old, unfolded "doc:a-1" is "A-1"
        counterparty = by_item.get((r.org_id, number, r.direction)) or by_job.get(
            (r.source_job_id, number, r.direction)
        )
        new = document_key(r.org_id, number, counterparty, r.direction)
        if new.startswith(_DOC):
            out["unattributed"] += 1  # no counterparty to key by: kept, not guessed
        elif new in taken[(r.org_id, r.source_type)]:
            out[_KEPT_OLD] += 1
        else:
            taken[(r.org_id, r.source_type)].add(new)
            _set_key(conn, _ledger, "source_record_id", r.id, new)
            out["ledger_rows"] += 1
            _move_dependents(conn, r, r.source_record_id, new, overrides, out, _KEPT_OLD)


def _rewrite_items(conn: sa.Connection, out: dict[str, int]) -> None:
    taken = {(i.org_id, i.document_id) for i in conn.execute(sa.select(_items.c.org_id, _items.c.document_id))}
    for i in conn.execute(sa.select(
        _items.c.id, _items.c.org_id, _items.c.direction, _items.c.document_id, _items.c.counterparty,
    ).where(_items.c.counterparty.is_not(None), ~_items.c.document_id.like(_INV_LIKE))).fetchall():
        if is_unique_id(i.document_id):
            continue
        new = open_item_key(document_key(
            i.org_id, _number(i.document_id), i.counterparty, _ITEM_DIRECTION.get(i.direction)
        ))
        if not new.startswith(_INV):
            out["items_unattributed"] += 1
        elif (i.org_id, new) in taken:
            out["items_kept_old_key_collision"] += 1
        else:
            taken.add((i.org_id, new))
            _set_key(conn, _items, "document_id", i.id, new)
            out["open_items"] += 1


def _report_merged(conn: sa.Connection) -> dict[str, int]:
    """Documents the old key merged: identities in `transactions` that the ledger has no row for.

    Counted per organisation and logged. Only what the ledger would have written is counted: a
    completed job, a dated row, an amount.
    """
    if not _has(conn, "transactions", "analysis_jobs", "canonical_transactions"):
        return {}
    have = {(r.org_id, r.source_record_id)
            for r in conn.execute(sa.select(_ledger.c.org_id, _ledger.c.source_record_id)
                                  .where(_ledger.c.corrects_id.is_(None)))}
    missing: dict[str, set[str]] = defaultdict(set)
    for t in conn.execute(
        sa.select(_jobs.c.org_id, _txs.c.document_id, _txs.c.counterparty, _txs.c.type)
        .select_from(_txs.join(_jobs, _jobs.c.id == _txs.c.job_id))
        .where(
            _jobs.c.status == "completed", _jobs.c.org_id.is_not(None), _txs.c.document_id.is_not(None),
            _txs.c.counterparty.is_not(None), _txs.c.amount_kurus != 0, _txs.c.date_is_estimated.is_(False),
        )
    ):
        key = document_key(t.org_id, _number(t.document_id), t.counterparty, t.type)
        if key.startswith(_INV) and (t.org_id, key) not in have:
            missing[t.org_id].add(key)
    for org_id, keys in sorted(missing.items()):
        log.warning(
            "G23: organisation %s has %d invoice(s) the old key had merged into another supplier's "
            "same number; run ledger.backfill to write them under their own keys", org_id, len(keys),
        )
    return {
        "merged_documents_missing_from_ledger": sum(len(v) for v in missing.values()),
        "orgs_with_merged_documents": len(missing),
    }


def rewrite_identities(conn: sa.Connection) -> dict[str, int]:
    """Old `doc:<number>` identities to `inv:` keys, everywhere. Returns what it did and could not do."""
    out: dict[str, int] = defaultdict(int)
    if not _has(conn, "canonical_transactions", "open_items"):
        return dict(out)
    _rewrite_ledger(conn, out)
    _rewrite_items(conn, out)
    out.update(_report_merged(conn))
    if _has(conn, "decisions"):
        out["decisions_with_old_ids"] = conn.execute(
            sa.select(sa.func.count()).select_from(_decisions).where(_decisions.c.target_id.like(_DOC_LIKE))
        ).scalar_one()
    return dict(out)


# ── downgrade ────────────────────────────────────────────────────────────────────────────────


def _restore_ledger(conn: sa.Connection, out: dict[str, int]) -> None:
    taken, overrides = _ledger_keys(conn, _DOC_LIKE), _override_keys(conn)
    keyed = conn.execute(sa.select(
        _ledger.c.id, _ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id,
    ).where(_ledger.c.source_record_id.like(_INV_LIKE), _ledger.c.corrects_id.is_(None))
      .order_by(_ledger.c.created_at, _ledger.c.id)).fetchall()
    for r in keyed:
        parts = r.source_record_id.split(":", 3)
        old = _DOC + parts[3] if len(parts) == 4 else None
        if old is None or old in taken[(r.org_id, r.source_type)]:
            out[_KEPT_NEW] += 1
            continue
        taken[(r.org_id, r.source_type)].add(old)
        _set_key(conn, _ledger, "source_record_id", r.id, old)
        out["ledger_rows"] += 1
        _move_dependents(conn, r, r.source_record_id, old, overrides, out, _KEPT_NEW)


def _restore_items(conn: sa.Connection, out: dict[str, int]) -> None:
    taken = {(i.org_id, i.document_id) for i in conn.execute(sa.select(_items.c.org_id, _items.c.document_id))}
    for i in conn.execute(sa.select(_items.c.id, _items.c.org_id, _items.c.document_id)
                          .where(_items.c.document_id.like(_INV_LIKE)).order_by(_items.c.id)).fetchall():
        parts = i.document_id.split(":", 3)
        if len(parts) != 4 or (i.org_id, parts[3]) in taken:
            out[_KEPT_NEW] += 1
            continue
        taken.add((i.org_id, parts[3]))
        _set_key(conn, _items, "document_id", i.id, parts[3])
        out["open_items"] += 1


def restore_identities(conn: sa.Connection) -> dict[str, int]:
    """`inv:` identities back to `doc:<number>` where that key is free."""
    out: dict[str, int] = defaultdict(int)
    if not _has(conn, "canonical_transactions", "open_items"):
        return dict(out)
    _restore_ledger(conn, out)
    _restore_items(conn, out)
    return dict(out)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.alter_column(
            "open_items", "document_id",
            type_=sa.String(128), existing_type=sa.String(64), existing_nullable=False,
        )
    log.warning("G23 invoice identity rewrite: %s", rewrite_identities(conn))


def downgrade() -> None:
    # The column keeps its width: an `inv:` key that had to stay (a second supplier's same
    # number) is longer than the old 64 characters, and truncating it would merge two documents.
    log.warning("G23 invoice identity restore: %s", restore_identities(op.get_bind()))
