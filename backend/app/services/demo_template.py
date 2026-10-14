"""
Golden demo şablonundan konuk org klonlama (DEMO_PLAN §D2).

`scripts/demo_prefill.py` bir kez "golden" org'u (slug=demo-golden) doldurur;
her yeni konuk org (/demo/guest) bu golden'dan kopya alır: AnalysisJob +
Report + Transaction + Anomaly + CompanyContext + semantic snapshot.

Job id yeniden üretilir ve JSON gövdelerindeki eski referanslar patch'lenir
(analiz job id + context_json içindeki org_id) — her konuk KENDİ satırlarına
sahip olur: tenant izolasyonu korunur, /dashboard/{job} sahiplik denetimi ile
/context/me aynı anda doğru org'u görür.

Golden yoksa sessizce no-op döner (konuk boş org'la başlar — D1 davranışı).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.anomaly import Anomaly
from app.models.company_context import CompanyContextSnapshot
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.organization import Organization
from app.models.report import Report
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

GOLDEN_SLUG = "demo-golden"
DEMO_FILENAME = "logo_tiger_2024_demo.csv"


@dataclass
class CloneOutcome:
    cloned: bool
    reason: str  # ok | no_golden | no_golden_job | already_cloned
    job_id: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


def _patch_str(text: str | None, pairs: list[tuple[str, str]]) -> str | None:
    """Replace id references inside a JSON string column."""
    if text is None:
        return None
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def _patch_value(value: Any, pairs: list[tuple[str, str]]) -> Any:
    """Replace id references inside a JSON-serializable structure (Report.data)."""
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False)
    for old, new in pairs:
        text = text.replace(old, new)
    return json.loads(text)


def _copy_row(model: Any, source: Any, **overrides: Any) -> Any:
    """New row of `model` with every column copied except `id` + overrides."""
    names = {c.name for c in type(source).__table__.columns}
    data = {
        name: getattr(source, name)
        for name in names
        if name != "id" and name not in overrides
    }
    return model(**data, **overrides)


async def clone_demo_workspace(db: AsyncSession, target_org_id: str) -> CloneOutcome:
    """Clone the golden demo workspace into `target_org_id`. Idempotent."""
    golden = (
        await db.execute(
            select(Organization).where(Organization.slug == GOLDEN_SLUG)
        )
    ).scalar_one_or_none()
    if golden is None:
        return CloneOutcome(cloned=False, reason="no_golden")
    golden_org_id = str(golden.id)

    # Idempotency: the target already carries a demo job (seeded or cloned).
    existing = (
        await db.execute(
            select(AnalysisJob.id)
            .where(
                AnalysisJob.org_id == target_org_id,
                AnalysisJob.filename == DEMO_FILENAME,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return CloneOutcome(
            cloned=False, reason="already_cloned", job_id=str(existing)
        )

    # The golden's latest completed demo analysis — the template to copy.
    job = (
        await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.org_id == golden_org_id,
                AnalysisJob.filename == DEMO_FILENAME,
                AnalysisJob.status == JobStatus.COMPLETED,
            )
            .order_by(desc(AnalysisJob.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return CloneOutcome(cloned=False, reason="no_golden_job")

    old_job_id = str(job.id)
    new_job_id = str(uuid.uuid4())
    pairs: list[tuple[str, str]] = [
        (old_job_id, new_job_id),
        (golden_org_id, target_org_id),
    ]
    counts: dict[str, int] = {}

    # AnalysisJob: created_at must read "now" — /demo/seed idempotency and
    # /demo/status key off recency; a clone looks freshly seeded. Status,
    # filename, file_path, result_metadata copy unchanged.
    db.add(
        _copy_row(
            AnalysisJob,
            job,
            id=new_job_id,
            org_id=target_org_id,
            user_id=None,
            created_at=datetime.now(UTC),
        )
    )

    # Reports (dashboard JSON payload carries the old job id inside data)
    reports = (
        await db.execute(select(Report).where(Report.job_id == old_job_id))
    ).scalars().all()
    for report_row in reports:
        db.add(
            _copy_row(
                Report,
                report_row,
                id=str(uuid.uuid4()),
                job_id=new_job_id,
                data=_patch_value(report_row.data, pairs),
            )
        )
    counts["reports"] = len(reports)

    # Transactions + anomalies (job-scoped rows the dashboard endpoints read)
    txs = (
        await db.execute(select(Transaction).where(Transaction.job_id == old_job_id))
    ).scalars().all()
    for tx_row in txs:
        db.add(_copy_row(Transaction, tx_row, id=str(uuid.uuid4()), job_id=new_job_id))
    counts["transactions"] = len(txs)

    anomalies = (
        await db.execute(select(Anomaly).where(Anomaly.job_id == old_job_id))
    ).scalars().all()
    for anomaly_row in anomalies:
        db.add(
            _copy_row(Anomaly, anomaly_row, id=str(uuid.uuid4()), job_id=new_job_id)
        )
    counts["anomalies"] = len(anomalies)

    # CompanyContext: one row per org; context_json embeds org_id and the
    # active_cfo_job_id / last_cfo_result.job_id references — all patched.
    ctx_row = (
        await db.execute(
            select(CompanyContextSnapshot).where(
                CompanyContextSnapshot.org_id == golden_org_id
            )
        )
    ).scalar_one_or_none()
    if ctx_row is not None:
        db.add(
            _copy_row(
                CompanyContextSnapshot,
                ctx_row,
                id=str(uuid.uuid4()),
                org_id=target_org_id,
                context_json=_patch_str(ctx_row.context_json, pairs),
            )
        )
        counts["context"] = 1

    # Semantic snapshot: latest period for the golden org, ids patched.
    snap = (
        await db.execute(
            select(CompanySemanticSnapshotRow)
            .where(CompanySemanticSnapshotRow.org_id == golden_org_id)
            .order_by(desc(CompanySemanticSnapshotRow.updated_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if snap is not None:
        db.add(
            _copy_row(
                CompanySemanticSnapshotRow,
                snap,
                id=str(uuid.uuid4()),
                org_id=target_org_id,
                metrics_json=_patch_str(snap.metrics_json, pairs),
                drivers_json=_patch_str(snap.drivers_json, pairs),
                evidence_json=_patch_str(snap.evidence_json, pairs),
                brief_json=_patch_str(snap.brief_json, pairs),
                source_job_ids=_patch_str(snap.source_job_ids, pairs),
            )
        )
        counts["semantic"] = 1

    await db.commit()
    logger.info(
        "Demo workspace cloned: golden job %s → org %s job %s (%s)",
        old_job_id[:8],
        target_org_id[:8],
        new_job_id[:8],
        counts,
    )
    return CloneOutcome(cloned=True, reason="ok", job_id=new_job_id, counts=counts)
