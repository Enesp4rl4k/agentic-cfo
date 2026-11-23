"""Build the company's data-portability bundle (KVKK Md. 11/b-c, GDPR Art. 15 and 20): a ZIP of documented JSON.

    manifest.json     format, scope, time, per dataset: file, row count, columns, whether it was cut by the size bound;
                      the uploaded files included and those omitted; what is never exported
    README.txt        the same, for a person (Turkish and English)
    ledger.jsonl, open_items.jsonl, journal_entries.jsonl, journal_lines.jsonl, decisions.jsonl, members.json, settings.json, uploads.json
    files/<job id>/<file name>   the uploaded files, in upload order, until the size bound is reached

One JSON object per line (`.jsonl`) so a large ledger is written and read as a stream: rows are fetched in chunks and
written straight into the archive, never held in memory together. Money stays integer kurus as stored (CLAUDE.md).

Never exported, whatever the table: password hashes, API keys, tokens and their hashes, encrypted credentials,
webhook URLs, billing identifiers, embeddings (`SECRET_COLUMN`). A test plants a marker in each and reads the bundle.
"""
from __future__ import annotations

import json
import re
import zipfile
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

FORMAT = "tiphys-export/1"
CHUNK = 500
SECRET_COLUMN = re.compile(r"password|api_key|token|secret|_enc$|webhook|stripe_|embedding|signature", re.I)
NEVER = ("password hashes", "API keys", "tokens", "encrypted integration credentials", "webhook URLs",
         "billing identifiers", "text embeddings")


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return None
    return value


def exportable(table: Table) -> list[str]:
    return [c.name for c in table.columns if not SECRET_COLUMN.search(c.name)]


@dataclass
class Budget:
    """Bytes the bundle may still take (uncompressed rows plus file sizes). Exhausted: datasets are cut and flagged."""

    left: int
    cut: bool = False

    def take(self, n: int) -> bool:
        if n > self.left:
            self.cut = True
            return False
        self.left -= n
        return True


@dataclass
class Dataset:
    file: str
    rows: int = 0
    truncated: bool = False
    columns: list[str] = field(default_factory=list)


async def _stream(db: AsyncSession, table: Table, where: ColumnElement[bool], order: str = "id") -> AsyncIterator[dict[str, Any]]:
    cols = exportable(table)
    stmt = select(*[table.c[c] for c in cols]).where(where).order_by(table.c[order]).execution_options(yield_per=CHUNK)
    result = await db.stream(stmt)
    async for row in result:
        yield {c: _plain(v) for c, v in zip(cols, row, strict=True)}


async def _collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row async for row in stream]


async def _dataset(
    db: AsyncSession, zf: zipfile.ZipFile, budget: Budget, name: str, table: Table, where: ColumnElement[bool], order: str = "id"
) -> Dataset:
    """Stream one table into one `.jsonl` entry: a chunk is pulled, serialised, written, dropped."""
    ds = Dataset(file=name, columns=exportable(table))
    with zf.open(name, "w", force_zip64=True) as out:
        async for row in _stream(db, table, where, order):
            data = (json.dumps(row, ensure_ascii=False, default=str) + "\n").encode()
            if not budget.take(len(data)):
                ds.truncated = True
                break
            out.write(data)
            ds.rows += 1
    return ds


async def build(db: AsyncSession, org_id: str, dest: Path, storage_root: Path, max_bytes: int) -> dict[str, Any]:
    """Write the bundle for `org_id` to `dest` (a temp path the caller renames); return the manifest."""
    T = Base.metadata.tables
    budget = Budget(left=max_bytes)
    datasets: dict[str, Dataset] = {}
    members = T["org_memberships"]
    users = T["users"]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        ct, oi, je, jl, dc = (T[n] for n in ("canonical_transactions", "open_items", "journal_entries", "journal_lines", "decisions"))
        datasets["ledger"] = await _dataset(db, zf, budget, "ledger.jsonl", ct, ct.c.org_id == org_id)
        datasets["open_items"] = await _dataset(db, zf, budget, "open_items.jsonl", oi, oi.c.org_id == org_id)
        datasets["journal_entries"] = await _dataset(db, zf, budget, "journal_entries.jsonl", je, je.c.org_id == org_id)
        datasets["journal_lines"] = await _dataset(
            db, zf, budget, "journal_lines.jsonl", jl, jl.c.entry_id.in_(select(je.c.id).where(je.c.org_id == org_id)))
        datasets["decisions"] = await _dataset(db, zf, budget, "decisions.jsonl", dc, dc.c.org_id == org_id, "decided_at")
        # members: a view, not a table dump (the account row holds a password hash and keys)
        member_rows = (await db.execute(
            select(users.c.id, users.c.email, users.c.full_name, members.c.role, members.c.created_at)
            .join(members, members.c.user_id == users.c.id).where(members.c.org_id == org_id).order_by(users.c.id)
        )).all()
        _put(zf, "members.json", [{"user_id": r.id, "email": r.email, "full_name": r.full_name, "role": r.role,
                                   "member_since": _plain(r.created_at)} for r in member_rows])
        datasets["members"] = Dataset("members.json", rows=len(member_rows), columns=["user_id", "email", "full_name", "role", "member_since"])
        settings: dict[str, Any] = {}
        for tname in ("organizations", "authority_policies", "alert_preferences", "category_rules", "counterparty_aliases",
                      "direction_mappings", "related_parties"):
            t = T[tname]
            where = t.c.id == org_id if tname == "organizations" else t.c.org_id == org_id
            settings[tname] = await _collect(_stream(db, t, where))
        _put(zf, "settings.json", settings)
        datasets["settings"] = Dataset("settings.json", rows=sum(len(v) for v in settings.values()),
                                       columns=[f"{t}.{c}" for t in settings for c in exportable(T[t])])
        jobs = T["analysis_jobs"]
        job_rows = (await db.execute(
            select(jobs.c.id, jobs.c.filename, jobs.c.file_type, jobs.c.status, jobs.c.created_at, jobs.c.file_path)
            .where(jobs.c.org_id == org_id).order_by(jobs.c.created_at, jobs.c.id)
        )).all()
        included, omitted = _add_files(zf, budget, storage_root, job_rows)
        _put(zf, "uploads.json", [{"job_id": r.id, "filename": r.filename, "file_type": r.file_type, "status": r.status,
                                   "uploaded_at": _plain(r.created_at), "file": f"files/{r.id}/" if r.id in included else None}
                                  for r in job_rows])
        datasets["uploads"] = Dataset("uploads.json", rows=len(job_rows), columns=["job_id", "filename", "file_type", "status", "uploaded_at", "file"])
        manifest = {
            "format": FORMAT, "scope": "organisation", "generated_at": datetime.now(UTC).isoformat(),
            "datasets": {k: {"file": d.file, "rows": d.rows, "truncated": d.truncated, "columns": d.columns} for k, d in datasets.items()},
            "files": {"included": len(included), "omitted": omitted},
            "size_bound_reached": budget.cut,
            "never_exported": list(NEVER),
            "money": "integer kurus as stored; divide by 100 for lira",
        }
        _put(zf, "manifest.json", manifest)
        zf.writestr("README.txt", README)
    return manifest


def _put(zf: zipfile.ZipFile, name: str, obj: Any) -> None:
    zf.writestr(name, json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _add_files(zf: zipfile.ZipFile, budget: Budget, root: Path, jobs: Iterable[Any]) -> tuple[set[str], list[dict[str, str]]]:
    included: set[str] = set()
    omitted: list[dict[str, str]] = []
    base = root.resolve()
    for job in jobs:
        path = Path(job.file_path) if job.file_path else None
        if path is None or not job.file_path:
            omitted.append({"job_id": job.id, "reason": "no_file"})
            continue
        try:
            resolved = (path if path.is_absolute() else Path.cwd() / path).resolve()
            resolved.relative_to(base)  # only files under the storage root, never an arbitrary path
        except (ValueError, OSError):
            omitted.append({"job_id": job.id, "reason": "outside_storage"})
            continue
        if not resolved.is_file():
            omitted.append({"job_id": job.id, "reason": "file_missing"})
            continue
        size = resolved.stat().st_size
        if not budget.take(size):
            omitted.append({"job_id": job.id, "reason": "size_limit"})
            continue
        safe = re.sub(r"[^\w.\- ]", "_", job.filename or resolved.name).lstrip(".")[:120] or "file"
        zf.write(resolved, f"files/{job.id}/{safe}")
        included.add(job.id)
    return included, omitted


README = """TIPHYS veri aktarimi / data export (tiphys-export/1)

TR: Bu paket sirketinizin verisidir. manifest.json her veri setinin dosyasini, satir sayisini ve sutunlarini, boyut
siniri nedeniyle kesilip kesilmedigini ve eklenen / eklenemeyen yuklenmis dosyalari soyler. *.jsonl dosyalarinda her satir
bir kayittir. Tutarlar kurus cinsinden tam sayidir (100'e bolun). Parola ozeti, API anahtari, token, sifreli entegrasyon
bilgisi, webhook adresi, faturalama kimligi ve metin gomme vektorleri hicbir zaman pakete konmaz.

EN: This bundle is your company's data. manifest.json names each dataset's file, row count and columns, whether the size
bound cut it, and the uploaded files included or omitted. In *.jsonl files each line is one record. Amounts are integer
kurus (divide by 100). Password hashes, API keys, tokens, encrypted integration credentials, webhook URLs, billing
identifiers and text embeddings are never included.
"""
