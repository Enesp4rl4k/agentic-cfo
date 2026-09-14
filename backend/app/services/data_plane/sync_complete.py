"""
Post-sync hook: canonical rows persisted → semantic rebuild (+ optional brief).

Called from scheduled_sync after successful canonical upsert so live connectors
update the decision brief without waiting for full CFO analysis.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def on_sync_canonical_persisted(
    *,
    org_id: str,
    db: AsyncSession | None,
    source_type: str,
    row_count: int,
    quality_score: float | None = None,
    sync_run_id: str | None = None,
    triggered_job_id: str | None = None,
) -> None:
    """Rebuild semantic snapshot from fresh canonical txs (non-fatal)."""
    if not org_id or not db or row_count <= 0:
        return

    try:
        from app.services.semantic.rebuild import rebuild_semantic_snapshot

        snap = await rebuild_semantic_snapshot(org_id, db, include_brief=True)
        if snap is not None:
            logger.info(
                "sync_complete semantic rebuild org=%s source=%s rows=%d metrics=%d job=%s",
                org_id,
                source_type,
                row_count,
                len(snap.metrics),
                triggered_job_id,
            )
    except Exception as exc:
        logger.warning("sync_complete semantic rebuild failed org=%s: %s", org_id, exc)
