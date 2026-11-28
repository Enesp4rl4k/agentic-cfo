"""The irreversible, non-transactional half of an organisation's erasure: files, caches, Redis.

Order of an erasure (see `org_erasure.erase_org` and `erasure_flow`):

1. ONE database transaction: every row delete/scrub, the Postgres agent memory, the proof record, and the hand-over
   of a durable CLEANUP PLAN to the request row (`cleanup_plan`, status `cleanup_pending`). Everything that can fail
   fails here, and a failure rolls back ALL of it: no file is touched, no row is gone.
2. After the commit: `run_cleanup(plan)` unlinks the files, drops in-process caches, deletes agent memory that is not
   transactional (SQLite / in-memory) and sweeps Redis. Every step is idempotent (deleting what is gone changes
   nothing), so a crash or a failure leaves `cleanup_pending` and the hourly executor runs the same plan again. The
   request can no longer be cancelled: the company's rows are already gone.

The plan holds UUIDs and storage-relative paths of the erased company only and is deleted when the cleanup finishes.
Nothing here accepts an id that is not a UUID (`require_ids`): a missing id must never turn into the string "None"
and a substring sweep across other tenants.
"""
from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

EXECUTING, CLEANUP_PENDING = "executing", "cleanup_pending"


class InvalidTargetError(ValueError):
    """An organisation, user, job or export id that is missing or not a UUID: nothing may run for it."""


def valid_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def require_ids(org_id: object, *groups: Iterable[str]) -> None:
    """Raise unless `org_id` and every id in every group is a UUID."""
    if not valid_id(org_id):
        raise InvalidTargetError("organisation id missing or not a UUID")
    for group in groups:
        for item in group:
            if not valid_id(item):
                raise InvalidTargetError("id is not a UUID")


def org_file_paths(root: Path, job_ids: Iterable[str], recorded_paths: Iterable[str],
                   export_ids: Iterable[str] = ()) -> list[Path]:
    """The organisation's existing files and directories under the local storage root (resolved, de-duplicated).

    The layout is `<root>/uploads/<job>/`, `<root>/reports/<job>/`, `<root>/board_decks/<job>.pdf`,
    `<root>/<job>_<name>` (demo upload), `<root>/exports/<export id>.zip[.part]`, plus whatever path the rows
    recorded. Nothing outside `root` is ever returned. There is no storage abstraction in the codebase
    (`storage_backend` is read nowhere); an object-store backend must add its own deletion here.
    """
    root = root.resolve()
    candidates: list[Path] = []
    for jid in job_ids:
        candidates += [root / "uploads" / jid, root / "reports" / jid, root / "board_decks" / f"{jid}.pdf"]
        if root.is_dir():
            candidates += list(root.glob(f"{jid}_*"))
    for eid in export_ids:  # from the stored id, whether or not a row recorded the path (a running export)
        candidates += [root / "exports" / f"{eid}.zip", root / "exports" / f"{eid}.zip.part"]
    for raw in recorded_paths:
        if raw:
            candidates.append(Path(raw) if Path(raw).is_absolute() else Path.cwd() / raw)
    found: dict[Path, None] = {}
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue  # outside the storage root: not ours to delete
        if resolved != root and resolved.exists():
            found[resolved] = None
    return list(found)


def delete_paths(root: Path, paths: Iterable[Path]) -> int:
    """Delete these paths (each re-checked to sit under `root`); a path that is already gone is skipped. Returns how many went."""
    root = root.resolve()
    removed = 0
    for path in paths:
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue
        if resolved == root or not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        removed += 1
    return removed


def build_plan(root: Path, org_id: str, user_ids: Iterable[str], job_ids: Iterable[str],
               export_ids: Iterable[str], recorded_paths: Iterable[str]) -> dict[str, Any]:
    """The durable cleanup plan, computed while the rows still name the files. `org_id` must be a UUID; a user,
    job or export id that is not one is left out of the plan (and counted) rather than used as a search needle."""
    require_ids(org_id)
    users, jobs, exports = ([i for i in dict.fromkeys(g) if valid_id(i)] for g in (user_ids, job_ids, export_ids))
    root = root.resolve()
    paths = [p.relative_to(root).as_posix() for p in org_file_paths(root, jobs, recorded_paths, exports)]
    return {"org_id": org_id, "user_ids": users, "job_ids": jobs, "export_ids": exports, "paths": paths}


async def run_cleanup(plan: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Run a plan. Idempotent. Raises `InvalidTargetError` before touching anything when an id is not a UUID."""
    from app.services.privacy.ephemeral import cleanup_ephemeral

    org_id, users, jobs = plan.get("org_id"), list(plan.get("user_ids") or []), list(plan.get("job_ids") or [])
    exports = list(plan.get("export_ids") or [])
    require_ids(org_id, users, jobs, exports)
    if root is None:
        from app.config import get_settings

        root = Path(get_settings().storage_local_path)
    deleted = delete_paths(root, [root / rel for rel in plan.get("paths") or []])
    return {"_files": {"deleted": deleted}, "_ephemeral": await cleanup_ephemeral(str(org_id), users, jobs)}


def is_incomplete(counts: dict[str, Any]) -> bool:
    """True when a best-effort step failed and the plan should run again."""
    eph = counts.get("_ephemeral") or {}
    return bool(eph.get("redis_failed") or eph.get("agent_memory_failed"))


def not_scrubbed(table: Any, values: dict[str, Any]) -> Any:
    """For `org_erasure._erase`: rows not yet holding the erased values: a second run (the final sweep re-runs this plan) changes only rows
    written after the first. A JSON column cannot be compared portably, so a table with one is scrubbed whole."""
    from sqlalchemy import JSON, or_, true
    from sqlalchemy.sql.elements import Null

    parts: list[Any] = []
    for name, value in values.items():
        col = table.c[name]
        if value is None or isinstance(value, Null):
            parts.append(col.is_not(None))
        elif isinstance(col.type, JSON):
            return true()
        else:
            parts.append(col != value)
    return or_(*parts) if parts else true()
