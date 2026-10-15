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
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.anomaly import Anomaly
from app.models.company_context import CompanyContextSnapshot
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.decision_log import DecisionLog
from app.models.organization import Organization
from app.models.report import Report
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

GOLDEN_SLUG = "demo-golden"
DEMO_FILENAME = "logo_tiger_2024_demo.csv"

# D4 konuk parmak izi — /demo/guest bu ikisini birlikte yazar; bir kullanıcının
# kendi org'u (demo-<hex> slug seçse bile) bu description'ı taşımaz, TTL cron'u
# böylece gerçek org'ın workspace'ine asla dokunmaz.
GUEST_SLUG_RE = re.compile(r"^demo-[0-9a-f]{12}$")
GUEST_DESCRIPTION = "Otomatik oluşturulmuş misafir demo çalışma alanı."


def is_guest_org(org: Organization) -> bool:
    """True only for orgs minted by POST /demo/guest (slug + description pair)."""
    return bool(GUEST_SLUG_RE.match(org.slug or "")) and org.description == GUEST_DESCRIPTION


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


async def purge_demo_workspace(db: AsyncSession, org_id: str) -> dict[str, int]:
    """
    Konuk demo workspace'ini sil — `clone_demo_workspace`'ın tersi (DEMO_PLAN §D4).

    `DELETE /demo/reset` ile TTL cron'unun (`_demo_guest_ttl_purge`) ortak
    çekirdeği. Silinenler: org'un DEMO_FILENAME job'ları ve onlara sert FK ile
    bağlı satırlar (Report / Transaction / Anomaly / DecisionLog), org'un
    CompanyContextSnapshot'ı (Redis cache dahil) ve CompanySemanticSnapshotRow.

    Dosya yalnızca başka hiçbir job'la paylaşılmıyorsa disetten kalkar — clone
    dosyayı golden'dan kopyalamaz, paylaşır; golden'in dosyası asla silinmez.

    Idempotent: temizlenecek şey yoksa sıfır sayaçlarla döner.
    """
    from app.services.company_context import invalidate_company_context

    # Sabit yanıt şekli: idempotent ikinci çağrıda da tüm sayaçlar görünür.
    counts: dict[str, int] = {
        "jobs": 0,
        "reports": 0,
        "transactions": 0,
        "anomalies": 0,
        "decision_logs": 0,
        "semantic": 0,
        "context": 0,
    }

    job_rows = (
        await db.execute(
            select(AnalysisJob).where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.filename == DEMO_FILENAME,
            )
        )
    ).scalars().all()
    job_ids = [str(j.id) for j in job_rows]
    counts["jobs"] = len(job_ids)

    if job_ids:
        # Hard FK children first (NO ACTION would block the job delete).
        for label, model in (
            ("reports", Report),
            ("transactions", Transaction),
            ("anomalies", Anomaly),
            ("decision_logs", DecisionLog),
        ):
            result = await db.execute(
                delete(model)
                .where(model.job_id.in_(job_ids))
                .execution_options(synchronize_session=False)
            )
            counts[label] = int(result.rowcount or 0)

        # Unlink files no surviving job still references (shared clone path).
        for job in job_rows:
            if not job.file_path:
                continue
            try:
                others = (
                    await db.execute(
                        select(func.count())
                        .select_from(AnalysisJob)
                        .where(
                            AnalysisJob.file_path == job.file_path,
                            AnalysisJob.id != job.id,
                        )
                    )
                ).scalar_one()
                if others:
                    continue
                path = Path(job.file_path)
                if path.is_file():
                    path.unlink()
            except OSError:
                logger.warning(
                    "Demo purge: dosya silinemedi org=%s path=%s",
                    org_id,
                    job.file_path,
                )

        for job in job_rows:
            await db.delete(job)

    semantic = (
        await db.execute(
            select(CompanySemanticSnapshotRow).where(
                CompanySemanticSnapshotRow.org_id == org_id
            )
        )
    ).scalars().all()
    for row in semantic:
        await db.delete(row)
    counts["semantic"] = len(semantic)

    ctx_present = (
        await db.execute(
            select(CompanyContextSnapshot.id).where(
                CompanyContextSnapshot.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    counts["context"] = 1 if ctx_present else 0

    await db.commit()

    # DB snapshot + Redis key in one shot (same pattern as DELETE /context).
    await invalidate_company_context(org_id, db)
    logger.info("Demo workspace purged: org=%s counts=%s", org_id, counts)
    return counts
