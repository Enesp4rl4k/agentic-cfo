"""Connector application service: load connection → fetch → idempotent upsert →
advance watermark → bookkeep the SyncRun. Adapters never touch the DB.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import CanonicalRow, ConnectorError, Watermark
from app.connectors.crypto import decrypt_secret
from app.connectors.registry import get_connector
from app.models.canonical_eng_signal import CanonicalEngSignal
from app.models.connector_connection import ConnectorConnection
from app.models.sync_run import SyncRun

logger = logging.getLogger(__name__)


@dataclass
class ConnectorSyncResult:
    connector: str
    org_id: str
    ok: bool
    sync_run_id: str | None
    records_fetched: int = 0
    records_written: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "org_id": self.org_id,
            "ok": self.ok,
            "sync_run_id": self.sync_run_id,
            "records_fetched": self.records_fetched,
            "records_written": self.records_written,
            "warnings": self.warnings,
            "error": self.error,
        }


async def _load_connection(
    connector_name: str, org_id: str, db: AsyncSession
) -> ConnectorConnection:
    row = (
        await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.org_id == org_id,
                ConnectorConnection.connector == connector_name,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ConnectorError(f"{connector_name}: no connection for this org")
    if row.status == "disconnected":
        raise ConnectorError(f"{connector_name}: connection is disconnected")
    return row


def _upsert_dict(org_id: str, source: str, sync_run_id: str, row: CanonicalRow) -> dict[str, Any]:
    return {
        "org_id": org_id,
        "source": source,
        "source_record_id": row.source_record_id,
        "sync_run_id": sync_run_id,
        "signal_type": row.signal_type,
        "occurred_at": row.occurred_at,
        "actor": row.actor,
        "title": row.title,
        "magnitude": row.magnitude,
        "attributes": row.attributes or {},
        "updated_at": datetime.now(UTC),
    }


async def _upsert_rows(
    db: AsyncSession, org_id: str, source: str, sync_run_id: str, rows: list[CanonicalRow]
) -> int:
    dialect = db.bind.dialect.name if db.bind else ""
    written = 0
    for row in rows:
        data = _upsert_dict(org_id, source, sync_run_id, row)
        set_ = {
            k: data[k]
            for k in ("sync_run_id", "signal_type", "occurred_at", "actor",
                      "title", "magnitude", "attributes", "updated_at")
        }
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            pg_stmt = pg_insert(CanonicalEngSignal).values(**data)
            await db.execute(
                pg_stmt.on_conflict_do_update(
                    constraint="uq_canonical_eng_org_source_record", set_=set_
                )
            )
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            lite_stmt = sqlite_insert(CanonicalEngSignal).values(**data)
            await db.execute(
                lite_stmt.on_conflict_do_update(
                    index_elements=["org_id", "source", "source_record_id"], set_=set_
                )
            )
        else:
            existing = (
                await db.execute(
                    select(CanonicalEngSignal).where(
                        CanonicalEngSignal.org_id == org_id,
                        CanonicalEngSignal.source == source,
                        CanonicalEngSignal.source_record_id == row.source_record_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                for k, v in set_.items():
                    setattr(existing, k, v)
            else:
                db.add(CanonicalEngSignal(**data))
        written += 1
    return written


async def run_connector_sync(
    *,
    connector_name: str,
    org_id: str,
    db: AsyncSession,
    triggered_job_id: str | None = None,
) -> ConnectorSyncResult:
    """Pull the connector once and persist its canonical rows. Never raises for a
    connector-level failure — the failure is recorded on the SyncRun and returned."""
    connector = get_connector(connector_name)
    result = ConnectorSyncResult(connector=connector_name, org_id=org_id, ok=False, sync_run_id=None)

    try:
        conn = await _load_connection(connector_name, org_id, db)
    except ConnectorError as exc:
        result.error = str(exc)
        return result

    sync_run = SyncRun(
        org_id=org_id,
        provider=connector_name,
        status="running",
        triggered_job_id=triggered_job_id,
    )
    db.add(sync_run)
    await db.flush()
    result.sync_run_id = sync_run.id

    config = json.loads(conn.config_json) if conn.config_json else {}
    try:
        secret = json.loads(decrypt_secret(conn.secret_enc)) if conn.secret_enc else {}
    except ValueError as exc:
        sync_run.status = "error"
        sync_run.error_message = str(exc)
        sync_run.completed_at = datetime.now(UTC)
        conn.status = "error"
        conn.last_status = "error"
        conn.last_error = str(exc)
        await db.commit()
        result.error = str(exc)
        return result

    since = Watermark(since=conn.watermark_since, cursor=conn.watermark_cursor)

    try:
        payload = await connector.fetch(
            org_id=org_id, config=config, secret=secret, since=since
        )
    except Exception as exc:
        logger.warning("connector %s sync failed for org=%s: %s", connector_name, org_id, exc)
        sync_run.status = "error"
        sync_run.error_message = str(exc)
        sync_run.completed_at = datetime.now(UTC)
        conn.status = "error"
        conn.last_status = "error"
        conn.last_error = str(exc)
        conn.last_sync_at = datetime.now(UTC)
        await db.commit()
        result.error = str(exc)
        return result

    written = await _upsert_rows(db, org_id, connector_name, sync_run.id, payload.rows)

    now = datetime.now(UTC)
    sync_run.status = "success"
    sync_run.row_count_raw = len(payload.rows)
    sync_run.row_count_canonical = written
    sync_run.completed_at = now

    conn.watermark_since = payload.next_watermark.since
    conn.watermark_cursor = payload.next_watermark.cursor
    conn.status = "active"
    conn.last_status = "success"
    conn.last_error = None
    conn.last_sync_at = now
    conn.last_record_count = written

    await db.commit()

    result.ok = True
    result.records_fetched = len(payload.rows)
    result.records_written = written
    result.warnings = payload.warnings
    return result
