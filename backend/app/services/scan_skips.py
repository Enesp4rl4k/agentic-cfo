"""A proactive scan that could not run for lack of inputs is recorded, never sent as an alert."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def record_skipped(db: Any, org_id: str, name: str, missing: list[str]) -> None:
    """One `scan_skipped` row per KRI, input set and day (the hourly repeat adds none)."""
    from app.models.proactive_alert import ProactiveAlert

    key = f"{org_id}|{name}|{','.join(sorted(missing))}|{time.strftime('%Y-%m-%d')}"
    alert_id = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
    try:
        if await db.get(ProactiveAlert, alert_id) is not None:
            return
        db.add(ProactiveAlert(
            alert_id=alert_id, org_id=org_id, trigger="scan_skipped", severity="info",
            title=f"Atlandı: {name}"[:300],
            body="Zincirleme risk simülasyonu atlandı, eksik girdi: " + ", ".join(missing),
            metadata_json=json.dumps({"kri": name, "missing": missing}),
            channels="[]", created_at=time.time(), dispatched=False,
        ))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("Skipped scan not recorded (org=%s): %s", org_id, exc)
