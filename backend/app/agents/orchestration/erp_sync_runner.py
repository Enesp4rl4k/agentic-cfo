"""
Scheduled ERP sync: pull each connected Paraşüt account on its interval and
open an ordinary analysis of what came in.

The runner used to push transactions through the CFO pipeline under a job id
it made up ("erp-parasut-1a2b"), with no AnalysisJob row, then write the
result into CompanyContext through a dict API the dataclass does not have —
so a sync ran and nothing any page reads ever changed. Pulled transactions now
take the same path as a dropped file (app/services/ingest/ekle.py).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ── Scheduled sync runner (scheduler.py'den cagirilir) ────────────────────────

async def run_scheduled_erp_sync(db: Any) -> dict[str, Any]:
    """
    Otomatik sync aktif olan tum ERP entegrasyonlarini sync et.
    Scheduler tarafindan gunluk cagirilir.
    """
    from sqlalchemy import select

    from app.models.erp_integration import ERPIntegration

    stmt = (
        select(ERPIntegration)
        .where(
            ERPIntegration.status == "active",
            ERPIntegration.auto_sync_enabled.is_(True),
        )
    )
    integrations = (await db.execute(stmt)).scalars().all()

    from app.services.erp.parasut_connector import ParasutConnector
    from app.services.ingest.ekle import Sahip, islemleri_ekle

    results = []
    simdi = datetime.now(UTC)
    for integration in integrations:
        try:
            # CSV-based connectors have nothing to pull on a timer.
            if integration.provider != "parasut":
                continue
            son = integration.last_sync_at
            if son is not None and son.tzinfo is None:
                son = son.replace(tzinfo=UTC)
            if son is not None and simdi - son < timedelta(hours=integration.sync_interval_hours or 24):
                continue
            islemler = await ParasutConnector(db).islemleri_cek(integration)
            # An ordinary analysis the pages show — not a pipeline run under a
            # made-up job id that nothing reads.
            job_id = None
            if islemler:
                out = await islemleri_ekle(db, Sahip(integration.org_id, None), islemler, "parasut")
                job_id = out["job_id"]
            results.append({
                "org_id":   integration.org_id,
                "provider": integration.provider,
                "ok":       True,
                "job_id":   job_id,
                "sync_count": len(islemler),
            })

        except Exception as exc:
            logger.error(
                "Scheduled ERP sync hatasi: org=%s provider=%s err=%s",
                integration.org_id, integration.provider, exc,
            )
            results.append({
                "org_id":   integration.org_id,
                "provider": integration.provider,
                "ok":       False,
                "error":    str(exc),
            })

    return {"synced": len(results), "results": results}
