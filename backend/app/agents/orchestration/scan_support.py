"""Small helpers of the hourly KRI scan, kept out of `proactive_alerts.py` (file-size ceiling)."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def kri_key(kri: dict[str, Any], siblings: list[dict[str, Any]]) -> str:
    """The part of a deterministic alert id that names one KRI.

    The KRI's own stable id when it carries one; otherwise its name plus its position among the
    same-named KRIs of the list, so two same-named KRIs of one kind do not collapse into one alert. The
    list order is the scan's own (stable across the retry of a slot), so a retry derives the same key."""
    for field in ("id", "kri_id"):
        if kri.get(field) not in (None, ""):
            return f"id:{kri[field]}"
    name = str(kri.get("name", ""))
    same = [k for k in siblings if str(k.get("name", "")) == name]
    position = next((i for i, k in enumerate(same) if k is kri), 0)
    return name if position == 0 else f"{name}#{position}"


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
