"""Erase one organisation (KVKK Md. 7 / GDPR Art. 17) — derived from the schema.

What counts as "the organisation's data" is *computed from the SQLAlchemy
metadata*, not listed by hand:

* a table with an ``org_id`` column belongs to the organisation directly;
* a table with a foreign key to a table that does belongs to it transitively
  (``transactions -> analysis_jobs``, ``journal_lines -> journal_entries``);
* ``SOFT_LINKS`` names the few links the schema does not declare as foreign keys;
* ``SPECIAL_TABLES`` are handled by dedicated code (users, audit log, ...).

A table added tomorrow with an ``org_id`` is therefore erased without anyone
remembering to list it. A table that fits none of the above must be classified in
this module or ``tests/test_org_erasure.py`` fails, naming it.

Two modes, because the documents do not decide the legal question
-----------------------------------------------------------------
Accounting records and audit logs may have to be kept for a statutory period
(``RETENTION_POLICY`` in ``app/api/compliance_gdpr.py`` cites TTK 82, VUK 253 and a
SOC2 audit log, but nothing in CLAUDE.md or PLAN_V10.md — gap G19 — settles what
KVKK erasure may override). So:

``anonymise`` (default)
    Everything is deleted *except* the tables in ``RETAINED``: the books
    (transactions, journal, open items, approvals) and the audit log. Their rows
    stay with amounts, dates and account codes, but every personal-data column
    named in ``RETAINED[...].scrub`` is overwritten irreversibly, uploaded files
    are deleted, users are deleted and the organisation row is anonymised.
``hard_delete`` (opt-in)
    Every row of every org-scoped table is deleted. Use only when the lawyer
    (G19) confirms no retention duty applies.

Anything not in ``RETAINED`` is deleted in *both* modes: retention is opt-in per
table, never the default, so a new table cannot silently outlive an erasure.

The whole operation is one transaction. Files are removed inside it, before the
commit, so a failure rolls the database back and a retry finds the same work.
A hash-chained ``OrgErasureRecord`` (no personal data) is written as proof.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, ColumnElement, MetaData, Table, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.models.erasure_record import OrgErasureRecord

ANONYMISE = "anonymise"
HARD_DELETE = "hard_delete"
MODES = (ANONYMISE, HARD_DELETE)
ERASED = "[erased]"
GENESIS_HASH = "0" * 64

# Evidence of erasure must survive erasure, so it carries no org_id and is skipped.
BOOKKEEPING_TABLES = frozenset({"org_erasure_requests", "org_erasure_records"})

# Tables whose link to an organisation is not an `org_id` column or a declared FK
# chain, each handled by dedicated code below.
SPECIAL_TABLES: dict[str, str] = {
    "organizations": "the organisation itself: anonymised or deleted last",
    "users": "members; deleted unless they belong to another organisation too",
    "audit_logs": "no org column; linked through the erased users' ids",
    "pilot_invites": "global table; linked through the erased users' ids / emails",
    "smmm_muhasebeci": "an accountant's profile; linked through the erased users' ids",
    "smmm_musteri_kayit": "an accountant's client list; linked through client_org_id",
}

# Links the schema does not declare as ForeignKey: table -> (column, parent table).
SOFT_LINKS: dict[str, tuple[str, str]] = {
    "data_sources": ("job_id", "analysis_jobs"),
}


@dataclass(frozen=True)
class Retained:
    """A table kept in `anonymise` mode, and what happens to its columns.

    `scrub` columns are overwritten (NULL where nullable, else a marker);
    `keep` columns are business data the books need. Every text/JSON column that
    is neither must be classified: the test fails on an unclassified one.
    """

    reason: str
    scrub: tuple[str, ...]
    keep: tuple[str, ...]


RETAINED: dict[str, Retained] = {
    "analysis_jobs": Retained(
        "parent of the retained ledger rows",
        scrub=("filename", "file_path", "locked_by", "user_id", "smmm_client_id", "logs",
               "error_message", "result_metadata"),
        keep=("status", "file_type"),
    ),
    "transactions": Retained(
        "accounting record (TTK 82 / VUK 253; period undecided, G19)",
        scrub=("description", "vendor", "raw_text", "payment_note", "counterparty"),
        keep=("currency", "type", "category", "category_source", "account_code"),
    ),
    "canonical_transactions": Retained(
        "accounting record (TTK 82 / VUK 253; period undecided, G19)",
        scrub=("counterparty", "description"),
        keep=("source_type", "source_record_id", "currency", "direction", "category",
              "account_code", "ledger_status", "duplicate_of", "basis"),
    ),
    "journal_entries": Retained(
        "journal (TTK 82 / VUK 253; period undecided, G19)",
        scrub=("aciklama", "onay_neden"),
        keep=("kayit_id", "tarih_kaynagi", "kaynak_islem_id", "thp_hesap_kodu", "kdv_durumu",
              "guven", "authority"),
    ),
    "journal_lines": Retained(
        "journal (TTK 82 / VUK 253; period undecided, G19)",
        scrub=("aciklama",),
        keep=("hesap_kodu", "hesap_adi"),
    ),
    "open_items": Retained(
        "receivables / payables (TTK 82 / VUK 253; period undecided, G19)",
        scrub=("counterparty", "description", "payment_note"),
        keep=("direction", "instrument", "currency", "status", "document_id"),
    ),
    "open_item_matches": Retained(
        "reconciliation evidence for the retained open items",
        scrub=("decided_by",),
        keep=("method", "status"),
    ),
    "smmm_onay_kayitlari": Retained(
        "accountant approvals (VUK 253, 10 years per RETENTION_POLICY)",
        scrub=("created_by_user_id", "onaylayan_user_id", "orijinal_kayit", "onay_notu",
               "duzeltme_aciklama", "onay_neden", "tx_description"),
        keep=("durum", "duzeltilmis_hesap_kodu", "duzeltilmis_hesap_adi", "otomatik_hesap_kodu",
              "otomatik_yontem"),
    ),
    "audit_logs": Retained(
        "security audit log (RETENTION_POLICY: 5 years; 'never deleted' in its model)",
        scrub=("user_id", "user_email", "request_body", "ip_address", "user_agent", "reason"),
        keep=("action", "resource", "user_role"),
    ),
    "organizations": Retained(
        "anchor for the retained rows' org_id",
        scrub=("name", "slug", "logo_url", "description", "vkn", "legal_title",
               "stripe_customer_id", "stripe_subscription_id"),
        keep=("country_code", "base_currency", "locale", "regional_packs", "plan",
              "subscription_plan", "subscription_status"),
    ),
}

_IN_CHUNK = 400  # stays under SQLite's bound-variable limit


# ── Schema derivation ────────────────────────────────────────────────────────

def hash_id(kind: str, value: str) -> str:
    """Stable, non-reversible handle for an id (ids are random UUIDs)."""
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()


def _tables(metadata: MetaData) -> dict[str, Table]:
    return dict(metadata.tables)


def _parents(table: Table, scoped: set[str]) -> list[tuple[str, str, str]]:
    """(column, parent table, parent column) links of `table` into `scoped`."""
    out = []
    for col in table.columns:
        for fk in col.foreign_keys:
            if fk.column.table.name in scoped:
                out.append((col.name, fk.column.table.name, fk.column.name))
    link = SOFT_LINKS.get(table.name)
    if link and link[1] in scoped:
        parent_pk = next(iter(table.metadata.tables[link[1]].primary_key.columns)).name
        out.append((link[0], link[1], parent_pk))
    return out


Link = tuple[str, str, str]  # (column, parent table, parent column)


def derive_scope(metadata: MetaData | None = None) -> dict[str, tuple[bool, list[Link]]]:
    """Org-scoped table -> (has its own `org_id`, links into scoped parents).

    A row belongs to the organisation if its `org_id` matches *or* a link leads
    to a parent row that does: several `org_id` columns are nullable, and a row
    with no `org_id` whose job belongs to the organisation is still its data.
    """
    tables = _tables(metadata or Base.metadata)
    skip = SPECIAL_TABLES.keys() | BOOKKEEPING_TABLES
    scoped = {n for n, t in tables.items() if "org_id" in t.c and n not in skip}
    changed = True
    while changed:
        changed = False
        for name, table in tables.items():
            if name not in scoped and name not in skip and _parents(table, scoped):
                scoped.add(name)
                changed = True
    return {
        n: ("org_id" in tables[n].c, [lk for lk in _parents(tables[n], scoped) if lk[1] != n])
        for n in scoped
    }


def unclassified_tables(metadata: MetaData | None = None) -> list[str]:
    """Tables the erasure neither derives nor handles specially. Must be empty."""
    tables = _tables(metadata or Base.metadata)
    known = derive_scope(metadata).keys() | SPECIAL_TABLES.keys() | BOOKKEEPING_TABLES
    return sorted(set(tables) - known)


def _depth(name: str, scope: dict[str, tuple[bool, list[Link]]]) -> int:
    links = scope[name][1]
    return 0 if not links else 1 + max(_depth(p, scope) for _, p, _ in links)


def _clause(
    table: Table, org_id: str, scope: dict[str, tuple[bool, list[Link]]], tables: dict[str, Table]
) -> ColumnElement[bool]:
    direct, links = scope[table.name]
    parts: list[ColumnElement[bool]] = [table.c.org_id == org_id] if direct else []
    for col, parent, parent_col in links:
        ptable = tables[parent]
        sub = select(ptable.c[parent_col]).where(_clause(ptable, org_id, scope, tables))
        parts.append(table.c[col].in_(sub))
    return or_(*parts)


def _erased_value(column: Any, org_hash: str) -> Any:
    if column.nullable:
        return None
    if isinstance(column.type, JSON):
        return {}
    if column.unique:
        return f"erased-{org_hash[:16]}"
    length = getattr(column.type, "length", None)
    return ERASED if not length or length >= len(ERASED) else ERASED[:length]


def _chunks(items: Sequence[str]) -> Iterator[list[str]]:
    for i in range(0, len(items), _IN_CHUNK):
        yield list(items[i:i + _IN_CHUNK])


# ── Files ────────────────────────────────────────────────────────────────────

def remove_org_files(root: Path, job_ids: Iterable[str], recorded_paths: Iterable[str]) -> int:
    """Delete the organisation's files under the local storage root; return how many.

    The storage layout is `<root>/uploads/<job>/`, `<root>/reports/<job>/`,
    `<root>/board_decks/<job>.pdf` and `<root>/<job>_<name>` (demo upload), plus
    whatever path the rows recorded. Nothing outside `root` is ever touched.
    There is no storage abstraction in the codebase (`storage_backend` is read
    nowhere); an object-store backend must add its own deletion here.
    """
    root = root.resolve()
    candidates: list[Path] = []
    for jid in job_ids:
        candidates += [root / "uploads" / jid, root / "reports" / jid,
                       root / "board_decks" / f"{jid}.pdf"]
        if root.is_dir():
            candidates += list(root.glob(f"{jid}_*"))
    for raw in recorded_paths:
        if raw:
            candidates.append(Path(raw) if Path(raw).is_absolute() else Path.cwd() / raw)
    removed = 0
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue  # outside the storage root: not ours to delete
        if resolved == root or not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        removed += 1
    return removed


# ── The operation ────────────────────────────────────────────────────────────

@dataclass
class ErasureResult:
    record: OrgErasureRecord
    already_erased: bool = False
    counts: dict[str, Any] = field(default_factory=dict)


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def record_payload(rec: OrgErasureRecord) -> dict[str, Any]:
    return {
        "seq": rec.seq, "org_hash": rec.org_hash, "mode": rec.mode,
        "requested_by_hash": rec.requested_by_hash, "confirmed_by_hash": rec.confirmed_by_hash,
        "executed_at": rec.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "counts": rec.counts,
    }


def _chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode()).hexdigest()


async def verify_chain(db: AsyncSession) -> list[int]:
    """Sequence numbers of records that no longer match their hash (empty = intact)."""
    rows = (await db.execute(select(OrgErasureRecord).order_by(OrgErasureRecord.seq))).scalars().all()
    bad, prev = [], GENESIS_HASH
    for rec in rows:
        if rec.prev_hash != prev or rec.record_hash != _chain_hash(prev, record_payload(rec)):
            bad.append(rec.seq)
        prev = rec.record_hash
    return bad


async def _user_ids(db: AsyncSession, org_id: str, tables: dict[str, Table]) -> tuple[list[str], list[str], list[str]]:
    """(users to erase, their emails, users kept because they belong elsewhere)."""
    users, members = tables["users"], tables["org_memberships"]
    member_ids = select(members.c.user_id).where(members.c.org_id == org_id)
    rows = (await db.execute(
        select(users.c.id, users.c.email).where((users.c.org_id == org_id) | users.c.id.in_(member_ids))
    )).all()
    other = set((await db.execute(
        select(members.c.user_id).where(members.c.org_id != org_id)
    )).scalars().all())
    erase = [r.id for r in rows if r.id not in other]
    emails = [r.email for r in rows if r.id not in other]
    keep = [r.id for r in rows if r.id in other]
    return erase, emails, keep


async def erase_org(
    db: AsyncSession, org_id: str, *, mode: str = ANONYMISE, storage_root: Path | None = None,
    requested_by_hash: str | None = None, confirmed_by_hash: str | None = None,
) -> ErasureResult:
    """Erase `org_id` in one transaction and commit. Idempotent per mode.

    Rolls back and re-raises on any failure, files included (see module docstring).
    """
    if mode not in MODES:
        raise ValueError(f"unknown erasure mode: {mode!r}")
    org_hash = hash_id("org", org_id)

    prior = (await db.execute(
        select(OrgErasureRecord).where(OrgErasureRecord.org_hash == org_hash)
        .order_by(OrgErasureRecord.seq.desc())
    )).scalars().all()
    if any(r.mode == HARD_DELETE or r.mode == mode for r in prior):
        return ErasureResult(record=prior[0], already_erased=True, counts=prior[0].counts)

    try:
        counts = await _erase(db, org_id, org_hash, mode, storage_root)
        record = await _write_record(db, org_hash, mode, counts, requested_by_hash, confirmed_by_hash)
        await db.commit()
        await db.refresh(record)
    except BaseException:
        await db.rollback()
        raise
    return ErasureResult(record=record, counts=counts)


async def _erase(
    db: AsyncSession, org_id: str, org_hash: str, mode: str, storage_root: Path | None
) -> dict[str, Any]:
    tables = _tables(Base.metadata)
    scope = derive_scope()
    keep_rows = mode == ANONYMISE
    counts: dict[str, Any] = {}

    def tally(name: str, kind: str, result: Any) -> None:
        if result.rowcount:
            counts.setdefault(name, {}).setdefault(kind, 0)
            counts[name][kind] += result.rowcount

    async def drop(name: str, where: ColumnElement[bool]) -> None:
        tally(name, "deleted", await db.execute(delete(tables[name]).where(where)))

    async def scrub(name: str, where: ColumnElement[bool]) -> None:
        table, rule = tables[name], RETAINED[name]
        values = {c: _erased_value(table.c[c], org_hash) for c in rule.scrub}
        tally(name, "anonymised", await db.execute(update(table).where(where).values(**values)))

    erase_users, erase_emails, kept_users = await _user_ids(db, org_id, tables)

    # Files first (rows still name them); removed before commit so a failure rolls back.
    jobs, reports, sources = tables["analysis_jobs"], tables["reports"], tables["data_sources"]
    job_rows = (await db.execute(
        select(jobs.c.id, jobs.c.file_path).where(_clause(jobs, org_id, scope, tables))
    )).all()
    paths = [r.file_path for r in job_rows]
    for t in (reports, sources):
        paths += (await db.execute(
            select(t.c.file_path).where(_clause(t, org_id, scope, tables))
        )).scalars().all()
    root = storage_root
    if root is None:
        from app.config import get_settings

        root = Path(get_settings().storage_local_path)
    removed = remove_org_files(root, [r.id for r in job_rows], paths)

    # Members who also belong to another organisation keep their account; they
    # lose only this membership, and are moved off it if it was their active one.
    users, members = tables["users"], tables["org_memberships"]
    for uid in kept_users:
        row = (await db.execute(
            select(users.c.org_id).where(users.c.id == uid)
        )).one()
        if row.org_id == org_id:
            fallback = (await db.execute(
                select(members.c.org_id).where(members.c.user_id == uid, members.c.org_id != org_id)
                .order_by(members.c.created_at).limit(1)
            )).scalar_one_or_none()
            await db.execute(update(users).where(users.c.id == uid).values(org_id=fallback))

    # Org-scoped tables, children before parents.
    for name in sorted(scope, key=lambda n: -_depth(n, scope)):
        where = _clause(tables[name], org_id, scope, tables)
        if keep_rows and name in RETAINED:
            await scrub(name, where)
        else:
            await drop(name, where)

    # Rows linked through the erased users.
    muh, client = tables["smmm_muhasebeci"], tables["smmm_musteri_kayit"]
    muh_ids = [m for chunk in _chunks(erase_users) for m in (await db.execute(
        select(muh.c.id).where(muh.c.user_id.in_(chunk)))).scalars().all()]
    await drop("smmm_musteri_kayit", client.c.client_org_id == org_id)
    for chunk in _chunks(muh_ids):
        await drop("smmm_musteri_kayit", client.c.muhasebeci_id.in_(chunk))
    for chunk in _chunks(erase_users):
        await drop("smmm_muhasebeci", muh.c.user_id.in_(chunk))
        invites = tables["pilot_invites"]
        await drop("pilot_invites", invites.c.used_by_user_id.in_(chunk))
        audit = tables["audit_logs"]
        if keep_rows:
            await scrub("audit_logs", audit.c.user_id.in_(chunk))
        else:
            await drop("audit_logs", audit.c.user_id.in_(chunk))
    for chunk in _chunks(erase_emails):
        await drop("pilot_invites", func.lower(tables["pilot_invites"].c.email).in_([e.lower() for e in chunk]))
    for chunk in _chunks(erase_users):
        await drop("users", users.c.id.in_(chunk))

    # The organisation itself, last.
    orgs = tables["organizations"]
    if keep_rows:
        values = {c: _erased_value(orgs.c[c], org_hash) for c in RETAINED["organizations"].scrub}
        values["is_active"] = False
        tally("organizations", "anonymised",
              await db.execute(update(orgs).where(orgs.c.id == org_id).values(**values)))
    else:
        await drop("organizations", orgs.c.id == org_id)

    # Requests for this org lose their raw ids (the hashes stay).
    reqs = tables["org_erasure_requests"]
    await db.execute(
        update(reqs).where(reqs.c.target_org_id == org_id)
        .values(target_org_id=None, requested_by_user_id=None)
    )
    counts["_files"] = {"deleted": removed}
    return counts


async def _write_record(
    db: AsyncSession, org_hash: str, mode: str, counts: dict[str, Any],
    requested_by_hash: str | None, confirmed_by_hash: str | None,
) -> OrgErasureRecord:
    last = (await db.execute(
        select(OrgErasureRecord).order_by(OrgErasureRecord.seq.desc()).limit(1)
    )).scalar_one_or_none()
    rec = OrgErasureRecord(
        seq=(last.seq + 1) if last else 1, org_hash=org_hash, mode=mode,
        requested_by_hash=requested_by_hash, confirmed_by_hash=confirmed_by_hash,
        executed_at=datetime.now(UTC).replace(microsecond=0), counts=counts,
        prev_hash=last.record_hash if last else GENESIS_HASH, record_hash="",
    )
    rec.record_hash = _chain_hash(rec.prev_hash, record_payload(rec))
    db.add(rec)
    await db.flush()
    return rec


__all__ = [
    "ANONYMISE", "BOOKKEEPING_TABLES", "ERASED", "HARD_DELETE", "MODES", "RETAINED",
    "SOFT_LINKS", "SPECIAL_TABLES", "ErasureResult",
    "derive_scope", "erase_org", "hash_id", "remove_org_files", "unclassified_tables",
    "verify_chain",
]
