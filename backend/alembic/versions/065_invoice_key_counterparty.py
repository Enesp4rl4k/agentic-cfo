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
neither names a counterparty (a return, a bank-less list without a "cari" column, an erased
organisation) keeps `doc:<number>` and is counted, never guessed.

**Rows that cannot be rewritten** keep their old key and are counted, never deleted: a new key
that already exists (two rows that normalise to one document, or an open item already under the
new key). Nothing here can violate a unique index: every target is checked first.

**Wrongly merged rows** (two suppliers' same number, the second silently dropped) cannot be
un-merged by this migration: the dropped row was never stored in the ledger. Their source rows
still exist in `transactions`, so the migration counts them per organisation (documents whose
new key is not in the ledger) and logs the count. `ledger.backfill` writes them under the new
keys; nothing is invented here.

Idempotent: a second run finds only the rows the first one could not key and does the same.
Downgrade restores `doc:<number>` where it is free; a second row for the same number (the very
rows this fixes) keeps its `inv:` key rather than collide, and the column keeps its width.

Revision ID: 065_invoice_key_counterparty
Revises: 064_decisions_table
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "065_invoice_key_counterparty"
down_revision = "064_decisions_table"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# ── frozen copy of app/core/invoice_identity.py (tests keep the two equal) ───────────────────
_UUID_ONLY = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_GIB_ONLY = re.compile(r"^[A-Za-z0-9]{3}20\d{2}\d{9}$")
_UUID_ANY = re.compile(
    r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)
_UUID_START = _UUID_ANY  # the app matches at the start with the same pattern
_GIB_SEARCH = re.compile(r"\b([A-Za-z0-9]{3}20\d{2}\d{9})\b", re.IGNORECASE)
_SIDE = {"income": "s", "expense": "p"}
_LEGAL_FORMS: tuple[tuple[str, ...], ...] = (
    ("anonim", "sirketi"), ("limited", "sirketi"), ("kollektif", "sirketi"),
    ("komandit", "sirketi"), ("ltd", "sti"), ("a", "s"),
    ("as",), ("ltd",), ("sti",), ("limited",), ("sirketi",), ("anonim",),
)
_TURKISH = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ş": "s", "Ş": "s", "ö": "o", "Ö": "o",
    "ü": "u", "Ü": "u", "ç": "c", "Ç": "c", "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u",
    "Û": "u", "̇": "",
})
_TOKEN = re.compile(r"[a-z0-9]+")
_TAX_NUMBER = re.compile(r"(?<!\d)(\d{10}|\d{11})(?!\d)")


def _is_unique_id(document_id: str | None) -> bool:
    text = (document_id or "").strip()
    return bool(_UUID_ONLY.match(text) or _GIB_ONLY.match(text))


def _canonical_number(document_id: str) -> str:
    """`canonical_invoice_id(document_id) or document_id`: the one-argument call the ledger made."""
    text = document_id[4:] if document_id.lower().startswith("doc:") else document_id
    found = _GIB_SEARCH.search(text)
    if found:
        return found.group(1).upper()
    clean = text.strip()
    if not _UUID_START.match(clean) and len(clean) >= 2:
        return clean.upper()
    uuid_found = _UUID_ANY.search(text)
    return uuid_found.group(1).lower() if uuid_found else document_id


def _valid_vkn(digits: str) -> bool:
    if len(digits) != 10:
        return False
    total = 0
    for i in range(9):
        tmp = (int(digits[i]) + (9 - i)) % 10
        part = (tmp * 2 ** (9 - i)) % 9
        total += 9 if tmp != 0 and part == 0 else part
    return (10 - total % 10) % 10 == int(digits[9])


def _valid_tckn(digits: str) -> bool:
    if len(digits) != 11 or digits[0] == "0":
        return False
    d = [int(c) for c in digits]
    return (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


def _tax_number_in(text: str | None) -> str | None:
    for found in _TAX_NUMBER.findall(text or ""):
        if _valid_vkn(found) or _valid_tckn(found):
            return found
    return None


def _normalise_party(name: str | None) -> str | None:
    tokens = _TOKEN.findall((name or "").lower().translate(_TURKISH))
    stripped = True
    while stripped and tokens:
        stripped = False
        for form in _LEGAL_FORMS:
            if len(tokens) >= len(form) and tuple(tokens[-len(form):]) == form:
                tokens = tokens[: -len(form)]
                stripped = True
                break
    return " ".join(tokens) or None


def _party_token(org_id: str, counterparty: str | None) -> str | None:
    tax = _tax_number_in(counterparty)
    if tax:
        return "t" + hashlib.sha256(f"{org_id}|tax|{tax}".encode()).hexdigest()[:12]
    name = _normalise_party(counterparty)
    if name:
        return "n" + hashlib.sha256(f"{org_id}|name|{name}".encode()).hexdigest()[:12]
    return None


def _document_key(org_id: str, number: str, counterparty: str | None, direction: str | None) -> str:
    side, party = _SIDE.get(direction or ""), _party_token(org_id, counterparty)
    if _is_unique_id(number) or side is None or party is None:
        return f"doc:{number}"
    return f"inv:{side}:{party}:{number}"


def _open_item_key(key: str) -> str:
    return key[4:] if key.startswith("doc:") else key


# ── tables, as this migration sees them ──────────────────────────────────────────────────────
_ledger = sa.table(
    "canonical_transactions",
    sa.column("id"), sa.column("org_id"), sa.column("source_type"), sa.column("source_record_id"),
    sa.column("source_job_id"), sa.column("direction"), sa.column("corrects_id"),
    sa.column("ledger_status"), sa.column("amount_cents"), sa.column("created_at"),
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

_ITEM_DIRECTION = {"receivable": "income", "payable": "expense"}
_CHUNK = 500


def _has(conn: sa.Connection, *tables: str) -> bool:
    present = set(sa.inspect(conn).get_table_names())
    return all(t in present for t in tables)


def _chunks(values: list[Any]) -> Any:
    for i in range(0, len(values), _CHUNK):
        yield values[i:i + _CHUNK]


def _set_key(conn: sa.Connection, table: sa.TableClause, key_column: str, row_id: Any, new: str) -> None:
    conn.execute(sa.update(table).where(table.c.id == row_id).values({key_column: new}))


def rewrite_identities(conn: sa.Connection) -> dict[str, Any]:
    """Old `doc:<number>` identities to `inv:` keys, everywhere. Returns what it did and could not do."""
    out: dict[str, Any] = defaultdict(int)
    if not _has(conn, "canonical_transactions", "open_items"):
        return dict(out)

    # Counterparty by (org, number) from the open item written from the same transaction.
    item_party: dict[tuple[str, str], tuple[str, str]] = {}
    for item in conn.execute(sa.select(
        _items.c.org_id, _items.c.document_id, _items.c.counterparty, _items.c.direction,
    ).where(_items.c.counterparty.is_not(None))):
        side = _ITEM_DIRECTION.get(item.direction)
        if side and not item.document_id.startswith("inv:"):
            item_party.setdefault((item.org_id, _canonical_number(item.document_id)), (item.counterparty, side))

    legacy = [
        r for r in conn.execute(sa.select(
            _ledger.c.id, _ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id,
            _ledger.c.source_job_id, _ledger.c.direction,
        ).where(_ledger.c.source_record_id.like("doc:%"), _ledger.c.corrects_id.is_(None)))
        if not _is_unique_id(r.source_record_id[4:])
    ]
    out["legacy_rows"] = len(legacy)

    # Where the open item names nobody (a return opens none), the job's own row does.
    need_job = {
        r.source_job_id for r in legacy
        if r.source_job_id and (r.org_id, _canonical_number(r.source_record_id[4:])) not in item_party
    }
    job_party: dict[tuple[str, str, str], str] = {}
    if need_job and _has(conn, "transactions"):
        for chunk in _chunks(sorted(need_job)):
            for t in conn.execute(sa.select(
                _txs.c.job_id, _txs.c.document_id, _txs.c.counterparty, _txs.c.type,
            ).where(_txs.c.job_id.in_(chunk), _txs.c.document_id.is_not(None), _txs.c.counterparty.is_not(None))):
                job_party.setdefault((t.job_id, _canonical_number(t.document_id), t.type), t.counterparty)

    taken: dict[tuple[str, str], set[str]] = defaultdict(set)  # (org, source_type) -> ledger keys in use
    for r in conn.execute(sa.select(_ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id)
                          .where(_ledger.c.source_record_id.like("inv:%"))):
        taken[(r.org_id, r.source_type)].add(r.source_record_id)
    overrides_present = _has(conn, "category_overrides")
    override_keys = {
        (r.org_id, r.source_record_id)
        for r in conn.execute(sa.select(_overrides.c.org_id, _overrides.c.source_record_id)
                              .where(_overrides.c.source_record_id.like("inv:%")))
    } if overrides_present else set()

    for r in legacy:
        number = _canonical_number(r.source_record_id[4:])  # an old, unfolded "doc:a-1" is "A-1"
        counterparty = (item_party.get((r.org_id, number)) or (None, ""))[0] or job_party.get(
            (r.source_job_id, number, r.direction)
        )
        new = _document_key(r.org_id, number, counterparty, r.direction)
        if new.startswith("doc:"):
            out["unattributed"] += 1  # no counterparty to key by: kept, not guessed
            continue
        if new in taken[(r.org_id, r.source_type)]:
            out["kept_old_key_collision"] += 1
            continue
        taken[(r.org_id, r.source_type)].add(new)
        _set_key(conn, _ledger, "source_record_id", r.id, new)
        out["ledger_rows"] += 1
        for c in conn.execute(sa.select(_ledger.c.id, _ledger.c.source_record_id).where(
            _ledger.c.org_id == r.org_id, _ledger.c.corrects_id == r.id,
            _ledger.c.source_record_id.like(f"{r.source_record_id}~k%"),
        )):
            _set_key(conn, _ledger, "source_record_id", c.id, new + c.source_record_id[len(r.source_record_id):])
            out["correction_rows"] += 1
        for o in conn.execute(sa.select(_overrides.c.id).where(
            _overrides.c.org_id == r.org_id, _overrides.c.source_record_id == r.source_record_id,
        )) if overrides_present else []:
            if (r.org_id, new) in override_keys:
                out["kept_old_key_collision"] += 1
            else:
                override_keys.add((r.org_id, new))
                _set_key(conn, _overrides, "source_record_id", o.id, new)
                out["overrides"] += 1

    items = list(conn.execute(sa.select(
        _items.c.id, _items.c.org_id, _items.c.direction, _items.c.document_id, _items.c.counterparty,
    ).where(_items.c.counterparty.is_not(None), ~_items.c.document_id.like("inv:%"))))
    item_keys = {(i.org_id, i.document_id) for i in conn.execute(sa.select(_items.c.org_id, _items.c.document_id))}
    for i in items:
        if _is_unique_id(i.document_id):
            continue
        new = _open_item_key(_document_key(
            i.org_id, _canonical_number(i.document_id), i.counterparty, _ITEM_DIRECTION.get(i.direction)
        ))
        if not new.startswith("inv:"):
            out["items_unattributed"] += 1
        elif (i.org_id, new) in item_keys:
            out["items_kept_old_key_collision"] += 1
        else:
            item_keys.add((i.org_id, new))
            _set_key(conn, _items, "document_id", i.id, new)
            out["open_items"] += 1

    out.update(_report_merged(conn))
    if _has(conn, "decisions"):
        out["decisions_with_old_ids"] = conn.execute(
            sa.select(sa.func.count()).select_from(_decisions).where(_decisions.c.target_id.like("doc:%"))
        ).scalar_one()
    return dict(out)


def _report_merged(conn: sa.Connection) -> dict[str, Any]:
    """Documents the old key merged: identities in `transactions` that the ledger has no row for.

    Counted per organisation and logged. Only what the ledger would have written is counted: a
    completed job, a dated row, an amount.
    """
    if not _has(conn, "transactions", "analysis_jobs", "canonical_transactions"):
        return {}
    have = {
        (r.org_id, r.source_record_id)
        for r in conn.execute(sa.select(_ledger.c.org_id, _ledger.c.source_record_id)
                              .where(_ledger.c.corrects_id.is_(None)))
    }
    missing: dict[str, set[str]] = defaultdict(set)
    for t in conn.execute(
        sa.select(_jobs.c.org_id, _txs.c.document_id, _txs.c.counterparty, _txs.c.type)
        .select_from(_txs.join(_jobs, _jobs.c.id == _txs.c.job_id))
        .where(
            _jobs.c.status == "completed", _jobs.c.org_id.is_not(None), _txs.c.document_id.is_not(None),
            _txs.c.counterparty.is_not(None), _txs.c.amount_kurus != 0, _txs.c.date_is_estimated.is_(False),
        )
    ):
        key = _document_key(t.org_id, _canonical_number(t.document_id), t.counterparty, t.type)
        if key.startswith("inv:") and (t.org_id, key) not in have:
            missing[t.org_id].add(key)
    total = sum(len(v) for v in missing.values())
    for org_id, keys in sorted(missing.items()):
        log.warning(
            "G23: organisation %s has %d invoice(s) the old key had merged into another supplier's "
            "same number; run ledger.backfill to write them under their own keys", org_id, len(keys),
        )
    return {"merged_documents_missing_from_ledger": total, "orgs_with_merged_documents": len(missing)}


def restore_identities(conn: sa.Connection) -> dict[str, int]:
    """`inv:` identities back to `doc:<number>` where that key is free."""
    out: dict[str, int] = defaultdict(int)
    if not _has(conn, "canonical_transactions", "open_items"):
        return dict(out)
    taken: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in conn.execute(sa.select(_ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id)
                          .where(_ledger.c.source_record_id.like("doc:%"))):
        taken[(r.org_id, r.source_type)].add(r.source_record_id)
    keyed = list(conn.execute(sa.select(
        _ledger.c.id, _ledger.c.org_id, _ledger.c.source_type, _ledger.c.source_record_id,
    ).where(_ledger.c.source_record_id.like("inv:%"), _ledger.c.corrects_id.is_(None))
      .order_by(_ledger.c.created_at, _ledger.c.id)))
    overrides_present = _has(conn, "category_overrides")
    override_keys = {
        (r.org_id, r.source_record_id)
        for r in conn.execute(sa.select(_overrides.c.org_id, _overrides.c.source_record_id))
    } if overrides_present else set()
    for r in keyed:
        parts = r.source_record_id.split(":", 3)
        if len(parts) != 4:
            continue
        old = f"doc:{parts[3]}"
        if old in taken[(r.org_id, r.source_type)]:
            out["kept_new_key_collision"] += 1
            continue
        taken[(r.org_id, r.source_type)].add(old)
        _set_key(conn, _ledger, "source_record_id", r.id, old)
        out["ledger_rows"] += 1
        for c in conn.execute(sa.select(_ledger.c.id, _ledger.c.source_record_id).where(
            _ledger.c.org_id == r.org_id, _ledger.c.corrects_id == r.id,
            _ledger.c.source_record_id.like(f"{r.source_record_id}~k%"),
        )):
            _set_key(conn, _ledger, "source_record_id", c.id, old + c.source_record_id[len(r.source_record_id):])
            out["correction_rows"] += 1
        if overrides_present:
            for o in conn.execute(sa.select(_overrides.c.id).where(
                _overrides.c.org_id == r.org_id, _overrides.c.source_record_id == r.source_record_id,
            )):
                if (r.org_id, old) in override_keys:
                    out["kept_new_key_collision"] += 1
                else:
                    override_keys.add((r.org_id, old))
                    _set_key(conn, _overrides, "source_record_id", o.id, old)
                    out["overrides"] += 1
    item_keys = {(i.org_id, i.document_id) for i in conn.execute(sa.select(_items.c.org_id, _items.c.document_id))}
    for i in conn.execute(sa.select(_items.c.id, _items.c.org_id, _items.c.document_id)
                          .where(_items.c.document_id.like("inv:%")).order_by(_items.c.id)).fetchall():
        parts = i.document_id.split(":", 3)
        if len(parts) != 4 or (i.org_id, parts[3]) in item_keys:
            out["kept_new_key_collision"] += 1
            continue
        item_keys.add((i.org_id, parts[3]))
        _set_key(conn, _items, "document_id", i.id, parts[3])
        out["open_items"] += 1
    return dict(out)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.alter_column(
            "open_items", "document_id",
            type_=sa.String(128), existing_type=sa.String(64), existing_nullable=False,
        )
    result = rewrite_identities(conn)
    log.warning("G23 invoice identity rewrite: %s", result)


def downgrade() -> None:
    # The column keeps its width: an `inv:` key that had to stay (a second supplier's same
    # number) is longer than the old 64 characters, and truncating it would merge two documents.
    result = restore_identities(op.get_bind())
    log.warning("G23 invoice identity restore: %s", result)
