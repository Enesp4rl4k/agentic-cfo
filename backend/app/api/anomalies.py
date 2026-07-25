"""
Anomalies API — GET /anomalies/{job_id}, POST /anomalies/scan/{job_id}

Kullanıcı muhasebe verisini yükleyip analiz ettikten sonra
bu endpoint'ler anomali sonuçlarını döner ve manuel tarama başlatır.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction

router = APIRouter()


# ── Response helpers ──────────────────────────────────────────────────────────

def _anomaly_dict(a: Anomaly) -> dict:
    return {
        "id": a.id,
        "job_id": a.job_id,
        "anomaly_type": a.anomaly_type,
        "severity": a.severity,
        "title": a.title,
        "description": a.description,
        "transaction_ids": a.transaction_ids,
        "evidence": a.evidence,
        "confidence": float(a.confidence) if a.confidence else None,
        "acknowledged": a.acknowledged,
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "created_at": a.created_at.isoformat(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/anomalies/{job_id}")
async def list_anomalies(
    job_id: str,
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all anomalies for a completed analysis job."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    stmt = select(Anomaly).where(Anomaly.job_id == job_id)
    if severity:
        stmt = stmt.where(Anomaly.severity == severity)
    stmt = stmt.order_by(
        Anomaly.severity,  # critical first (alphabetical happens to be wrong order)
        Anomaly.created_at.desc(),
    )

    result = await db.execute(stmt)
    anomalies = result.scalars().all()

    # severity ordering for proper sort
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_anomalies = sorted(anomalies, key=lambda a: sev_order.get(a.severity, 4))

    return {
        "data": {
            "job_id": job_id,
            "total": len(sorted_anomalies),
            "critical": sum(1 for a in sorted_anomalies if a.severity == "critical"),
            "high": sum(1 for a in sorted_anomalies if a.severity == "high"),
            "medium": sum(1 for a in sorted_anomalies if a.severity == "medium"),
            "low": sum(1 for a in sorted_anomalies if a.severity == "low"),
            "anomalies": [_anomaly_dict(a) for a in sorted_anomalies],
        },
        "error": None,
    }


@router.post("/anomalies/scan/{job_id}")
async def scan_anomalies(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger anomaly detection on an already-completed job's transactions.
    Useful for re-scanning after category corrections.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job must be completed to scan anomalies. Current status: {job.status}",
        )

    # Load transactions
    result = await db.execute(
        select(Transaction).where(Transaction.job_id == job_id)
    )
    txs = result.scalars().all()
    if not txs:
        raise HTTPException(status_code=404, detail="No transactions found for this job.")

    # Convert to dicts for the agent
    tx_dicts = [
        {
            "id": tx.id,
            "amount_cents": tx.amount_kurus,
            "currency": tx.currency,
            "type": tx.type,
            "category": tx.category,
            "description": tx.description,
            "vendor": tx.vendor,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
            "confidence": float(tx.confidence) if tx.confidence else None,
        }
        for tx in txs
    ]

    # Load existing dashboard for cashflow data
    from app.models.report import Report, ReportFormat
    from sqlalchemy import select as sa_select
    report_result = await db.execute(
        sa_select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = report_result.scalars().first()
    cashflow = {}
    if report and report.data:
        cashflow = report.data.get("cashflow", {})

    # Run anomaly detection
    from app.agents.anomaly_agent import (
        detect_duplicates,
        detect_unusual_amounts,
        detect_vendor_concentration,
        detect_expense_spikes,
        detect_round_numbers,
        detect_negative_cashflow_streak,
        _generate_anomaly_narrative,
    )
    from app.config import get_settings
    settings = get_settings()

    all_anomalies = []
    all_anomalies.extend(detect_duplicates(tx_dicts))
    all_anomalies.extend(detect_unusual_amounts(tx_dicts))
    all_anomalies.extend(detect_vendor_concentration(tx_dicts))
    all_anomalies.extend(detect_expense_spikes(tx_dicts))
    all_anomalies.extend(detect_round_numbers(tx_dicts))
    if cashflow:
        all_anomalies.extend(detect_negative_cashflow_streak(cashflow))

    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_anomalies.sort(key=lambda a: sev_order.get(a["severity"], 4))

    # Delete existing anomalies for this job and re-insert
    existing = await db.execute(select(Anomaly).where(Anomaly.job_id == job_id))
    for old in existing.scalars().all():
        await db.delete(old)

    new_rows = []
    for a in all_anomalies:
        row = Anomaly(
            job_id=job_id,
            anomaly_type=a["anomaly_type"],
            severity=a["severity"],
            title=a["title"],
            description=a["description"],
            transaction_ids=a.get("transaction_ids"),
            evidence=a.get("evidence"),
            confidence=a.get("confidence"),
        )
        db.add(row)
        new_rows.append(row)

    await db.commit()

    narrative = await _generate_anomaly_narrative(all_anomalies, settings)

    return {
        "data": {
            "job_id": job_id,
            "scanned": len(tx_dicts),
            "anomalies_found": len(all_anomalies),
            "critical": sum(1 for a in all_anomalies if a["severity"] == "critical"),
            "high": sum(1 for a in all_anomalies if a["severity"] == "high"),
            "narrative": narrative,
        },
        "error": None,
    }


class AcknowledgeRequest(BaseModel):
    acknowledged: bool = True


@router.patch("/anomalies/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(
    anomaly_id: str,
    body: AcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark an anomaly as acknowledged (dismissed by the CFO)."""
    anomaly = await db.get(Anomaly, anomaly_id)
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found.")

    anomaly.acknowledged = body.acknowledged
    anomaly.acknowledged_at = datetime.now(timezone.utc) if body.acknowledged else None
    await db.commit()

    return {"data": _anomaly_dict(anomaly), "error": None}
