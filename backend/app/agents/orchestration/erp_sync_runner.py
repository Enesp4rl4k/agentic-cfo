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

    from app.models.in_app_notification import InAppNotification
    from app.services.erp.parasut_connector import parasut_al
    from app.services.ingest.ekle import Sahip

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
            onceki_durum = integration.last_sync_status
            try:
                out = await parasut_al(db, integration, Sahip(integration.org_id, None))
            except ValueError as exc:
                # Nobody is watching a timer. Say it once where they will see
                # it — not again every hour while it stays broken.
                if onceki_durum != "error":
                    db.add(InAppNotification(
                        org_id=integration.org_id, level="warning", domain="cfo", source="parasut",
                        message=f"Paraşüt faturaları otomatik alınamadı: {exc} Entegrasyonlar sayfasından "
                                "bağlantıyı kontrol edin.",
                    ))
                    await db.commit()
                raise
            results.append({
                "org_id":   integration.org_id,
                "provider": integration.provider,
                "ok":       True,
                "durum":    out["durum"],
                "job_id":   out.get("job_id"),
                "sync_count": out["sync_count"],
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
