"""
ERP Sync Runner

ERP sync sonuclarini dogrudan CFO pipeline'a besler.
Islemler normalize edildikten sonra CFO analizi otomatik baslatilir.

Akis:
  ERP sync (Parasut/LogoTiger) -> normalize transactions
  -> CFO pipeline (pnl + cashflow + forecast)
  -> CompanyContext'e kaydet
  -> Kullaniciya CFO job_id don
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


async def run_erp_sync_and_analyze(
    org_id:       str,
    transactions: list[dict[str, Any]],
    source:       str,
    db:           Any,
    trigger_full_pipeline: bool = True,
) -> dict[str, Any]:
    """
    ERP'den gelen normalize edilmis islemleri CFO pipeline'a besle.

    Args:
        org_id:        Organizasyon ID
        transactions:  Normalize edilmis islem listesi
        source:        "parasut" | "logo_tiger" | "mikro"
        db:            AsyncSession
        trigger_full_pipeline: True ise tam CFO pipeline calistir

    Returns:
        {job_id, ok, transaction_count, source}
    """
    if not transactions:
        return {"ok": False, "reason": "Islem bulunamadi", "job_id": None}

    job_id = f"erp-{source}-{uuid.uuid4().hex[:8]}"

    try:
        if trigger_full_pipeline:
            result = await _run_cfo_pipeline(
                job_id=job_id,
                org_id=org_id,
                transactions=transactions,
                source=source,
            )
            # CompanyContext'e kaydet
            await _update_company_context(org_id=org_id, job_id=job_id, cfo_result=result)
            return {
                "ok":               True,
                "job_id":           job_id,
                "transaction_count": len(transactions),
                "source":           source,
                "cfo_summary":      _extract_summary(result),
            }
        else:
            # Sadece islemleri kaydet, pipeline calistirma
            return {
                "ok":               True,
                "job_id":           job_id,
                "transaction_count": len(transactions),
                "source":           source,
            }

    except Exception as exc:
        logger.error("ERP sync -> CFO pipeline hatasi: org=%s source=%s err=%s", org_id, source, exc)
        return {
            "ok":               False,
            "job_id":           job_id,
            "transaction_count": len(transactions),
            "source":           source,
            "error":            str(exc),
        }


async def _run_cfo_pipeline(
    job_id:       str,
    org_id:       str,
    transactions: list[dict[str, Any]],
    source:       str,
) -> dict[str, Any]:
    """
    Normalize edilmis islemleri CFO pipeline'a besle.
    CEO orchestrator'in _run_cfo_from_transactions metodunu kullanir.
    """
    from app.agents.ceo.orchestrator import _run_cfo_from_transactions

    # Tip normalizasyonu: ERP kaynaklari farkli tip ismi kullanabilir
    normalized = []
    for tx in transactions:
        t = dict(tx)
        tx_type = t.get("type", "expense").lower()
        if tx_type in ("gelir", "income", "revenue", "alacak", "credit"):
            t["type"] = "income"
        else:
            t["type"] = "expense"
        # amount_cents kontrolu
        if "amount_cents" not in t and "amount" in t:
            t["amount_cents"] = int(float(t["amount"]) * 100)
        normalized.append(t)

    result = await _run_cfo_from_transactions(
        job_id=job_id,
        transactions=normalized,
    )
    return dict(result) if result else {}


async def _update_company_context(
    org_id:     str,
    job_id:     str,
    cfo_result: dict[str, Any],
) -> None:
    """CFO sonuclarini CompanyContext'e kaydet."""
    try:
        from app.services.company_context import get_company_context, update_company_context
        ctx = await get_company_context(org_id) or {}
        agent_results = ctx.get("agent_results", {}) or {}
        agent_results["cfo"] = {
            "pnl":      cfo_result.get("pnl_summary") or cfo_result.get("pnl"),
            "cashflow": cfo_result.get("cashflow_summary") or cfo_result.get("cashflow"),
            "forecast": cfo_result.get("forecast"),
        }
        await update_company_context(org_id, {
            "active_cfo_job_id": job_id,
            "agent_results":     agent_results,
            "updated_at":        datetime.now(UTC).isoformat(),
        })
        logger.info("CompanyContext guncellendi: org=%s job=%s", org_id, job_id)
    except Exception as exc:
        logger.debug("CompanyContext guncelleme hatasi (non-fatal): %s", exc)


def _extract_summary(cfo_result: dict[str, Any]) -> dict[str, Any]:
    """CFO sonucundan ozet metrikleri cikart."""
    pnl = cfo_result.get("pnl_summary") or cfo_result.get("pnl") or {}
    cashflow = cfo_result.get("cashflow_summary") or cfo_result.get("cashflow") or {}
    return {
        "revenue_cents":   pnl.get("revenue", 0),
        "net_margin":      pnl.get("net_margin", 0),
        "net_change_cents": cashflow.get("net_change", 0),
    }


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

    results = []
    for integration in integrations:
        try:
            if integration.provider == "parasut":
                from app.services.erp.parasut_connector import ParasutConnector
                connector   = ParasutConnector(db)
                sync_result = await connector.sync(integration.id)
            elif integration.provider in ("logo_tiger", "mikro"):
                # CSV-based: scheduled sync desteklenmez
                continue
            else:
                continue

            if sync_result.get("transactions"):
                cfo_job = await run_erp_sync_and_analyze(
                    org_id=integration.org_id,
                    transactions=sync_result["transactions"],
                    source=integration.provider,
                    db=db,
                )
                results.append({
                    "org_id":   integration.org_id,
                    "provider": integration.provider,
                    "ok":       True,
                    "job_id":   cfo_job.get("job_id"),
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
