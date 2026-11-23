"""Small helpers of the hourly KRI scan, kept out of `proactive_alerts.py` (file-size ceiling)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


_DEFINING = ("category", "unit", "threshold_amber", "threshold_red", "higher_is_worse", "source")
_VOLATILE = ("current_value", "evidence", "status")


def _digest(parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=True).encode("utf-8")).hexdigest()[:10]


def kri_key(kri: dict[str, Any], siblings: list[dict[str, Any]]) -> str:
    """The part of a deterministic alert id that names one KRI, independent of the order of the list.

    The KRI's own stable id when it carries one. Otherwise its name plus a short hash of what DEFINES it
    (category, unit, thresholds, direction, source), so two same-named KRIs that differ in their definition never
    share a key and neither key depends on a position. Same-named KRIs that are identical in definition (they differ
    only by value/evidence, which a new analysis can change) are told apart by their rank under a stable sort of
    that content, never by list position: a retry after the list was reordered derives the same keys."""
    for field in ("id", "kri_id"):
        if kri.get(field) not in (None, ""):
            return f"id:{kri[field]}"
    name = str(kri.get("name", ""))
    base = f"{name}~{_digest([kri.get(f) for f in _DEFINING])}"
    group = [k for k in siblings if k.get("name") == kri.get("name")
             and [k.get(f) for f in _DEFINING] == [kri.get(f) for f in _DEFINING]]
    if not any(k is kri for k in group) or len(group) == 1:
        return base
    rank = next(i for i, k in enumerate(sorted(group, key=lambda k: _digest([k.get(f) for f in _VOLATILE]))) if k is kri)
    return base if rank == 0 else f"{base}#{rank}"


def kri_alert_words(name: str, val: Any, unit: str, *, critical: bool) -> tuple[str, str]:
    """Title and opening line of a KRI alert: "kritik" only for a critical one; a capped one says DİKKAT."""
    if critical:
        return f"🚨 {name}: {val} {unit} — Kırmızı Eşik Aşıldı", f"**{name}** metrigi kritik seviyeye ulasti.\n\n"
    return f"⚠ {name}: {val} {unit} — DİKKAT", f"**{name}** metrigi dikkat gerektiriyor (dayanağı varsayıma dayanıyor).\n\n"


async def active_orgs(db: Any) -> list[str]:
    """Orgs with an analysis or an agent job in the last 24 hours (at most 100, sorted).

    This was raw SQL (CLAUDE.md law 4) in Postgres-only syntax: on SQLite it raised into an
    `except: pass` and the scan covered no organisation. It also read only `agent_jobs`, so an org that
    only ran CFO analyses was never scanned (plan v6 section S0)."""
    if not db:
        return []
    from sqlalchemy import select

    from app.models.agent_job import AgentJob
    from app.models.analysis_job import AnalysisJob

    since = datetime.now(UTC) - timedelta(hours=24)
    try:
        orgs: set[str] = set()
        for model in (AnalysisJob, AgentJob):
            rows = await db.execute(
                select(model.org_id).where(model.created_at > since, model.org_id.isnot(None)).distinct()
            )
            orgs.update(str(o) for o in rows.scalars())
        return sorted(orgs)[:100]
    except Exception as exc:
        logger.warning("Proactive scan: active-org query failed: %s", exc)
        return []
