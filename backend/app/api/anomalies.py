"""
Anomalies API — GET /anomalies/{job_id}, POST /anomalies/scan/{job_id},
                GET /anomalies/explain/{anomaly_id}

Kullanıcı muhasebe verisini yükleyip analiz ettikten sonra
bu endpoint'ler anomali sonuçlarını döner ve manuel tarama başlatır.
"""
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.anomaly import Anomaly
from app.models.transaction import Transaction
from app.models.user import User

router = APIRouter()


def _check_job_access(job: AnalysisJob, user: User) -> None:
    if user.org_id and job.org_id and job.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Access denied.")


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all anomalies for a completed analysis job."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)

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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger anomaly detection on an already-completed job's transactions.
    Useful for re-scanning after category corrections.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)
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
    from sqlalchemy import select as sa_select

    from app.models.report import Report, ReportFormat
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
        _generate_anomaly_narrative,
        detect_duplicates,
        detect_expense_spikes,
        detect_negative_cashflow_streak,
        detect_round_numbers,
        detect_unusual_amounts,
        detect_vendor_concentration,
    )

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

    narrative = await _generate_anomaly_narrative(all_anomalies, None)

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
    anomaly.acknowledged_at = datetime.now(UTC) if body.acknowledged else None
    await db.commit()

    return {"data": _anomaly_dict(anomaly), "error": None}


# ── GET /anomalies/explain/{anomaly_id} — Streaming RCA ──────────────────────

@router.get("/anomalies/explain/{anomaly_id}", response_model=None)
async def explain_anomaly(
    anomaly_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Streaming Root Cause Analysis (RCA) for a single anomaly.

    Returns SSE stream of text tokens explaining:
    1. Root cause (why this is anomalous)
    2. Contributing transactions
    3. Recommended corrective action

    Frontend should listen on EventSource and accumulate tokens.
    Final event: data: [DONE]
    """
    anomaly = await db.get(Anomaly, anomaly_id)
    if not anomaly:
        async def _not_found():
            yield "data: Anomali bulunamadı.\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_not_found(), media_type="text/event-stream")

    # Load related transactions for context
    tx_ids = anomaly.transaction_ids or []
    related_txs: list[dict[str, Any]] = []
    if tx_ids:
        tx_result = await db.execute(
            select(Transaction).where(Transaction.id.in_(tx_ids[:10]))
        )
        for tx in tx_result.scalars().all():
            related_txs.append({
                "id": str(tx.id),
                "amount": tx.amount_kurus / 100 if tx.amount_kurus else 0,
                "vendor": tx.vendor or "",
                "category": tx.category or "",
                "description": tx.description or "",
                "date": tx.transaction_date.isoformat() if tx.transaction_date else "",
            })

    evidence = anomaly.evidence or {}
    evidence_text = ", ".join(f"{k}: {v}" for k, v in evidence.items() if k not in ("detectors",))
    tx_text = "\n".join(
        f"  - {t['date']} | {t['vendor']} | {t['category']} | {t['amount']:,.2f} TL | {t['description']}"
        for t in related_txs
    ) or "  (ilgili işlem bulunamadı)"


    async def _generate():
        try:
            from app.platform.model_gateway import stream as _gw_stream

            prompt = (
                f"Anomali Başlığı: {anomaly.title}\n"
                f"Açıklama: {anomaly.description}\n"
                f"Tür: {anomaly.anomaly_type} | Önem: {anomaly.severity}\n"
                f"Kanıt: {evidence_text}\n"
                f"İlgili İşlemler:\n{tx_text}\n\n"
                "Türkçe olarak şu 3 başlıkla açıkla:\n"
                "1. 🔍 KÖK NEDEN: Bu neden anomali?\n"
                "2. 📊 ETKİ ANALİZİ: Finansal etkisi nedir?\n"
                "3. ✅ ÖNERİLEN ADIM: CFO ne yapmalı?\n"
                "Her bölüm 2-3 cümle olsun, somut rakam kullan."
            )

            async for token in _gw_stream(
                task="quick_analysis",
                system_prompt="Sen bir kıdemli CFO danışmanısın. Verilen anomali için kısa, net ve eyleme geçirilebilir bir kök neden analizi yap.",
                prompt=prompt,
                max_tokens=500,
            ):
                if token:
                    yield f"data: {token}\n\n"

        except Exception as exc:
            yield f"data: Analiz başlatılamadı: {exc}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
