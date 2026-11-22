"""
Scheduled Sync Service — DQ-5

Manages automatic periodic data synchronization from:
  - ERP systems (Logo Tiger, Parasut, Netsis)
  - Open Banking (Akbank, Garanti, İş, YapıKredi)
  - E-invoice (GİB e-Fatura)

Architecture
------------
SyncSchedule: DB-backed schedule config per org/source
SyncRunner:   executes a sync, creates AnalysisJob, triggers CFO pipeline
SyncHistory:  stores last N sync results per schedule

Sync flow
---------
1. Scheduler calls _daily_sync_runner() (added to APScheduler)
2. For each active SyncSchedule that is due:
   a. Pull data from source (ERP/OB API)
   b. Convert to unified transaction CSV format
   c. Run CSVValidator — skip if health_score < 30
   d. Create AnalysisJob
   e. Enqueue CFO pipeline via ARQ worker
   f. Update SyncSchedule.last_run, last_status
3. Send notification on completion or failure

Frequency options
-----------------
  daily    — every day at configured hour (default 06:00 Turkey time)
  weekly   — every Monday
  monthly  — first day of month
  manual   — no automatic trigger, only via API

Model stored in PostgreSQL (sync_schedules table via Alembic migration).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.services.ingest.feed import FeedFailed, pull_coverage

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class SyncFrequency(StrEnum):
    DAILY   = "daily"
    WEEKLY  = "weekly"
    MONTHLY = "monthly"
    MANUAL  = "manual"


class SyncStatus(StrEnum):
    IDLE      = "idle"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    SKIPPED   = "skipped"
    # The pull finished but rows wait for a person / the pull stopped short. Neither is "success".
    AWAITING_REVIEW = "awaiting_review"
    PARTIAL         = "partial"


class SyncSourceType(StrEnum):
    ERP_LOGO_TIGER = "erp_logo_tiger"
    ERP_PARASUT    = "erp_parasut"
    ERP_NETSIS     = "erp_netsis"
    OPEN_BANKING   = "open_banking"
    GIB_EFATURA    = "gib_efatura"
    BILLING_STRIPE = "billing_stripe"
    CRM_EXPORT     = "crm_export"
    HR_EXPORT      = "hr_export"
    GITHUB_ACTIVITY = "github_activity"
    MANUAL_CSV     = "manual_csv"


# ── Dataclasses ───────────────────────────────────────────────────────────────

class SyncScheduleConfig:
    """
    In-memory config for a sync schedule.
    In production this is backed by the sync_schedules DB table.
    """
    __slots__ = (
        "auto_analyze",
        "enabled",
        "frequency",
        "hour_utc",
        "last_error",
        "last_run_at",
        "last_status",
        "notify_on_completion",
        "org_id",
        "schedule_id",
        "source_config",
        "source_type",
    )

    def __init__(
        self,
        schedule_id: str,
        org_id: str,
        source_type: str,
        frequency: str = SyncFrequency.DAILY,
        hour_utc: int = 3,          # 06:00 Istanbul (UTC+3)
        enabled: bool = True,
        last_run_at: datetime | None = None,
        last_status: str = SyncStatus.IDLE,
        source_config: dict[str, Any] | None = None,
        auto_analyze: bool = True,
        notify_on_completion: bool = True,
        last_error: str | None = None,
    ) -> None:
        self.last_error = last_error
        self.schedule_id = schedule_id
        self.org_id = org_id
        self.source_type = source_type
        self.frequency = frequency
        self.hour_utc = hour_utc
        self.enabled = enabled
        self.last_run_at = last_run_at
        self.last_status = last_status
        self.source_config = source_config or {}
        self.auto_analyze = auto_analyze
        self.notify_on_completion = notify_on_completion

    def is_due(self, now: datetime | None = None) -> bool:
        """Return True if this schedule should run now."""
        if not self.enabled:
            return False
        if self.frequency == SyncFrequency.MANUAL:
            return False

        now = now or datetime.now(UTC)

        # Hour check
        if now.hour != self.hour_utc:
            return False

        if self.last_run_at is None:
            return True

        last = self.last_run_at if self.last_run_at.tzinfo else self.last_run_at.replace(tzinfo=UTC)
        delta = now - last

        if self.frequency == SyncFrequency.DAILY:
            return delta >= timedelta(hours=23)
        elif self.frequency == SyncFrequency.WEEKLY:
            return delta >= timedelta(days=6, hours=23) and now.weekday() == 0
        elif self.frequency == SyncFrequency.MONTHLY:
            return delta >= timedelta(days=27) and now.day == 1

        return False


class SyncResult:
    """Result of a single sync run."""
    __slots__ = (
        "counts",
        "duration_ms",
        "error",
        "health_score",
        "held_candidates",
        "job_id",
        "org_id",
        "period_covered",
        "ran_at",
        "row_count",
        "schedule_id",
        "source_type",
        "status",
    )

    def __init__(
        self,
        schedule_id: str,
        org_id: str,
        source_type: str,
        status: str = SyncStatus.SUCCESS,
        job_id: str | None = None,
        row_count: int = 0,
        health_score: int | None = None,
        error: str | None = None,
        duration_ms: int = 0,
        ran_at: datetime | None = None,
        counts: dict[str, Any] | None = None,
        held_candidates: int = 0,
        period_covered: bool = False,
    ) -> None:
        self.counts = counts
        self.held_candidates = held_candidates
        # True only for a pull that read the whole window and booked or held every row: the one thing a sync
        # may be believed about. A failed, skipped or partial run never covers its period.
        self.period_covered = period_covered
        self.schedule_id = schedule_id
        self.org_id = org_id
        self.source_type = source_type
        self.status = status
        self.job_id = job_id
        self.row_count = row_count
        self.health_score = health_score
        self.error = error
        self.duration_ms = duration_ms
        self.ran_at = ran_at or datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "org_id": self.org_id,
            "source_type": self.source_type,
            "status": self.status,
            "job_id": self.job_id,
            "row_count": self.row_count,
            "health_score": self.health_score,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "counts": self.counts,
            "held_candidates": self.held_candidates,
            "period_covered": self.period_covered,
            "ran_at": self.ran_at.isoformat(),
        }


# ── SyncRunner ────────────────────────────────────────────────────────────────

class ScheduledSyncRunner:
    """
    Executes a single sync run for a SyncScheduleConfig.

    Each source type has its own pull logic.
    Output is always a CSV bytes blob + filename that gets
    passed to CSVValidator then to AnalysisJob creation.
    """

    MIN_HEALTH_SCORE = 30   # below this, skip analysis

    async def run(
        self,
        schedule: SyncScheduleConfig,
        db: Any,
        settings: Any,
    ) -> SyncResult:
        """Execute a sync for the given schedule."""
        import time
        t0 = int(time.time() * 1000)

        logger.info(
            "ScheduledSync: starting %s for org=%s source=%s",
            schedule.schedule_id, schedule.org_id, schedule.source_type
        )
        sync_run_id: str | None = None

        try:
            if schedule.source_type == SyncSourceType.GITHUB_ACTIVITY:
                return await self._run_github_overlay(schedule, db, t0)

            csv_bytes, filename, partial = await self._pull_data(schedule, settings, db=db)
            if not csv_bytes:
                return SyncResult(
                    schedule_id=schedule.schedule_id,
                    org_id=schedule.org_id,
                    source_type=schedule.source_type,
                    status=SyncStatus.SKIPPED,
                    error="Kaynak veri boş — sync atlandı",
                    duration_ms=int(time.time() * 1000) - t0,
                )

            # Validate data quality
            from app.services.csv_validator import CSVValidator
            validation = CSVValidator.validate(csv_bytes, filename=filename)
            sync_run_id = await self._start_sync_run(
                db=db,
                org_id=schedule.org_id,
                schedule_id=schedule.schedule_id,
                provider=schedule.source_type,
                row_count_raw=validation.row_count,
            )

            if validation.health_score < self.MIN_HEALTH_SCORE:
                logger.warning(
                    "ScheduledSync: health score %d < %d for %s — skipping analysis",
                    validation.health_score, self.MIN_HEALTH_SCORE, schedule.schedule_id
                )
                if sync_run_id:
                    await self._finish_sync_run(
                        db=db,
                        sync_run_id=sync_run_id,
                        status=SyncStatus.SKIPPED,
                        row_count_canonical=0,
                        quality_score=None,
                        triggered_job_id=None,
                        error_message=f"Veri kalitesi çok düşük (skor: {validation.health_score})",
                    )
                return SyncResult(
                    schedule_id=schedule.schedule_id,
                    org_id=schedule.org_id,
                    source_type=schedule.source_type,
                    status=SyncStatus.SKIPPED,
                    row_count=validation.row_count,
                    health_score=validation.health_score,
                    error=f"Veri kalitesi çok düşük (skor: {validation.health_score})",
                    duration_ms=int(time.time() * 1000) - t0,
                )

            # Normalize into canonical contract and compute quality gate.
            from app.models.canonical_transaction import CanonicalTransaction
            from app.services.data_plane.normalization_service import (
                normalize_csv_transactions,
                to_insert_dict,
            )
            from app.services.data_plane.quality_gate_service import score_sync_quality

            normalized = normalize_csv_transactions(
                csv_bytes=csv_bytes,
                column_mapping=validation.column_mapping,
                source=str(schedule.source_type),
            )
            canonical_rows = normalized.rows
            # What the pull came to, by the one reconcile the upload pipeline runs: rows fetched = written +
            # held + skipped by a named rule. A partial pull (the source stopped short) says so.
            feed_outcome = normalized.outcome()
            if partial:
                feed_outcome = {**feed_outcome, "status": SyncStatus.PARTIAL, "reason": partial, "complete": False}
            elif normalized.held or feed_outcome["unaccounted"]:
                feed_outcome = {**feed_outcome, "status": SyncStatus.AWAITING_REVIEW}
            final_status = str(feed_outcome["status"])
            note = _outcome_note(feed_outcome)
            quality = score_sync_quality(
                validator_health_score=validation.health_score,
                canonical_row_count=len(canonical_rows) + len(normalized.held),
            )
            if quality.should_block:
                if sync_run_id:
                    await self._finish_sync_run(
                        db=db,
                        sync_run_id=sync_run_id,
                        status=SyncStatus.SKIPPED,
                        row_count_canonical=len(canonical_rows),
                        quality_score=quality.quality_score,
                        triggered_job_id=None,
                        error_message=(
                            "Data-plane quality gate blocked sync "
                            f"(score={quality.quality_score})"
                        ),
                    )
                return SyncResult(
                    schedule_id=schedule.schedule_id,
                    org_id=schedule.org_id,
                    source_type=schedule.source_type,
                    status=SyncStatus.SKIPPED,
                    row_count=validation.row_count,
                    health_score=validation.health_score,
                    error=(
                        "Data-plane quality gate blocked sync "
                        f"(score={quality.quality_score})"
                    ),
                    duration_ms=int(time.time() * 1000) - t0,
                )

            # The org's standing category corrections apply to synced rows too
            # (plan v5 §F0) — counterparty is the vendor on a canonical row.
            from app.services.classifier import apply_rules, load_rules, record_hits

            category_rules = await load_rules(schedule.org_id, db)
            rule_hits: dict[str, int] = {}

            for row in canonical_rows:
                row_data = to_insert_dict(
                    org_id=schedule.org_id,
                    source_type=schedule.source_type,
                    sync_run_id=sync_run_id,
                    row=row,
                )
                for rule_id, n in apply_rules(
                    [row_data], category_rules, vendor_key="counterparty"
                ).items():
                    rule_hits[rule_id] = rule_hits.get(rule_id, 0) + n
                # A canonical row has no category_source column (yet — F1).
                row_data.pop("category_source", None)
                # Idempotent upsert across repeated sync pulls.
                dialect = db.bind.dialect.name if db.bind else ""
                if dialect == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as pg_insert

                    stmt = pg_insert(CanonicalTransaction).values(**row_data)
                    await db.execute(
                        stmt.on_conflict_do_update(
                            constraint="uq_canonical_tx_org_source_record",
                            set_={
                                "sync_run_id": row_data["sync_run_id"],
                                "transaction_date": row_data["transaction_date"],
                                "amount_cents": row_data["amount_cents"],
                                "currency": row_data["currency"],
                                "direction": row_data["direction"],
                                "category": row_data["category"],
                                "counterparty": row_data["counterparty"],
                                "description": row_data["description"],
                                "confidence": row_data["confidence"],
                            },
                        )
                    )
                elif dialect == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                    stmt = sqlite_insert(CanonicalTransaction).values(**row_data)
                    await db.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["org_id", "source_type", "source_record_id"],
                            set_={
                                "sync_run_id": row_data["sync_run_id"],
                                "transaction_date": row_data["transaction_date"],
                                "amount_cents": row_data["amount_cents"],
                                "currency": row_data["currency"],
                                "direction": row_data["direction"],
                                "category": row_data["category"],
                                "counterparty": row_data["counterparty"],
                                "description": row_data["description"],
                                "confidence": row_data["confidence"],
                            },
                        )
                    )
                else:
                    db.add(CanonicalTransaction(**row_data))

            await record_hits(rule_hits, db)
            await db.commit()

            # Live path: partial semantic brief from canonical rows (before CFO completes)
            try:
                from app.services.data_plane.sync_complete import on_sync_canonical_persisted

                await on_sync_canonical_persisted(
                    org_id=schedule.org_id,
                    db=db,
                    source_type=schedule.source_type,
                    row_count=len(canonical_rows),
                    quality_score=quality.quality_score,
                    sync_run_id=sync_run_id,
                )
            except Exception as sync_exc:
                logger.debug("ScheduledSync: sync_complete hook failed: %s", sync_exc)

            # Create analysis job (idempotent when fingerprint unchanged)
            job_id: str | None = None
            # Held rows can only wait for a person inside a job (the review queue is per job), so a pull that holds
            # rows opens one even when the schedule does not auto-analyse.
            if schedule.auto_analyze or normalized.held:
                fingerprint = _canonical_fingerprint(canonical_rows)
                reused = None if normalized.held else await self._find_reusable_job(
                    db=db,
                    org_id=schedule.org_id,
                    fingerprint=fingerprint,
                )
                if reused:
                    job_id = reused
                    logger.info(
                        "ScheduledSync: reusing analysis job=%s (fingerprint match)",
                        job_id,
                    )
                else:
                    cfg = schedule.source_config or {}
                    window = (str(cfg["from_date"])[:10], str(cfg["to_date"])[:10]) if cfg.get("from_date") and cfg.get("to_date") else None
                    stated = pull_coverage(window, [r["date"] for r in normalized.feed.rows], partial,
                                           getattr(normalized.feed, "opened_on", None))
                    job_id = await self._create_job(
                        csv_bytes=normalized.job_csv,
                        # Out of band: what this pull received is job metadata, never a line inside the file.
                        feed_meta={"source": str(schedule.source_type), "pull_coverage": stated},
                        filename=filename,
                        org_id=schedule.org_id,
                        column_mapping=validation.column_mapping,
                        quality_meta={
                            "quality_score": quality.quality_score,
                            "quality_issues": quality.issues,
                            "quality_should_review": quality.should_review,
                            "sync_run_id": sync_run_id,
                            "sync_fingerprint": fingerprint,
                        },
                        db=db,
                        settings=settings,
                    )

            if sync_run_id:
                await self._finish_sync_run(
                    db=db,
                    sync_run_id=sync_run_id,
                    status=final_status,
                    row_count_canonical=len(canonical_rows),
                    quality_score=quality.quality_score,
                    triggered_job_id=job_id,
                    error_message=note,
                )

            # Send notification
            if schedule.notify_on_completion:
                await self._notify(schedule, job_id, validation.row_count, db, note=note)

            duration = int(time.time() * 1000) - t0
            logger.info(
                "ScheduledSync: completed %s in %dms — job=%s rows=%d score=%d",
                schedule.schedule_id, duration, job_id,
                validation.row_count, validation.health_score,
            )

            return SyncResult(
                schedule_id=schedule.schedule_id,
                org_id=schedule.org_id,
                source_type=schedule.source_type,
                status=final_status,
                job_id=job_id,
                row_count=validation.row_count,
                health_score=validation.health_score,
                error=note,
                duration_ms=duration,
                counts=feed_outcome["counts"],
                held_candidates=int(feed_outcome["held_candidates"]),
                period_covered=bool(feed_outcome["complete"]) and not feed_outcome["unaccounted"],
            )

        except Exception as exc:
            logger.error("ScheduledSync: error in %s: %s", schedule.schedule_id, type(exc).__name__)
            # State-based: a source that cannot pull (dormant, revoked, down) is reported ONCE per distinct reason, not as a
            # new failed run on every tick; the schedule's own last_status/last_error (persisted by run_due_syncs) say so.
            repeat = schedule.last_status == SyncStatus.FAILED and (schedule.last_error or "") == str(exc)[:500]
            if sync_run_id is None and not repeat:
                # The pull itself failed (before any run was opened): the failure is still a recorded run.
                try:
                    sync_run_id = await self._start_sync_run(
                        db=db, org_id=schedule.org_id, schedule_id=schedule.schedule_id,
                        provider=schedule.source_type, row_count_raw=0,
                    )
                except Exception:   # the failure itself must still be returned
                    sync_run_id = None
            if sync_run_id:
                await self._finish_sync_run(
                    db=db,
                    sync_run_id=sync_run_id,
                    status=SyncStatus.FAILED,
                    row_count_canonical=0,
                    quality_score=None,
                    triggered_job_id=None,
                    error_message=str(exc),
                )
            return SyncResult(
                schedule_id=schedule.schedule_id,
                org_id=schedule.org_id,
                source_type=schedule.source_type,
                status=SyncStatus.FAILED,
                error=str(exc),
                duration_ms=int(time.time() * 1000) - t0,
            )

    async def _start_sync_run(
        self,
        *,
        db: Any,
        org_id: str,
        schedule_id: str,
        provider: str,
        row_count_raw: int,
    ) -> str:
        from app.models.sync_run import SyncRun

        sr = SyncRun(
            org_id=org_id,
            schedule_id=schedule_id,
            provider=provider,
            status=SyncStatus.RUNNING,
            row_count_raw=row_count_raw,
        )
        db.add(sr)
        await db.flush()
        return str(sr.id)

    async def _finish_sync_run(
        self,
        *,
        db: Any,
        sync_run_id: str,
        status: str,
        row_count_canonical: int,
        quality_score: float | None,
        triggered_job_id: str | None,
        error_message: str | None = None,
    ) -> None:
        from app.models.sync_run import SyncRun

        sr = await db.get(SyncRun, sync_run_id)
        if not sr:
            return
        sr.status = status
        sr.row_count_canonical = row_count_canonical
        sr.quality_score = quality_score
        sr.triggered_job_id = triggered_job_id
        sr.error_message = error_message
        sr.completed_at = datetime.now(UTC)
        sr.updated_at = datetime.now(UTC)

    async def _find_reusable_job(
        self,
        *,
        db: Any,
        org_id: str,
        fingerprint: str,
    ) -> str | None:
        """Reuse a recent analysis job when sync fingerprint is unchanged."""
        from sqlalchemy import select

        from app.models.analysis_job import AnalysisJob

        if not fingerprint:
            return None
        result = await db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.org_id == org_id)
            .where(
                AnalysisJob.status.in_(
                    ("pending", "analyzing", "completed", "awaiting_review")
                )
            )
            .order_by(AnalysisJob.created_at.desc())
            .limit(40)
        )
        for job in result.scalars().all():
            meta = job.result_metadata if isinstance(job.result_metadata, dict) else {}
            if meta.get("sync_fingerprint") == fingerprint:
                return str(job.id)
        return None

    async def _pull_data(
        self,
        schedule: SyncScheduleConfig,
        settings: Any,
        db: Any = None,
    ) -> tuple[bytes, str, str | None]:
        """Pull data from the configured source: (csv, filename, partial reason).

        A pull that fails RAISES (`FeedFailed` with the reason): an outage is a failed sync, never an empty file.
        An empty file means the source answered and had nothing, or is not configured.
        """
        source = schedule.source_type
        cfg = schedule.source_config

        if source == SyncSourceType.ERP_LOGO_TIGER:
            return (*await self._pull_logo_tiger(cfg, settings), None)
        elif source == SyncSourceType.ERP_PARASUT:
            return await self._pull_parasut(cfg, settings, db=db, org_id=schedule.org_id)
        elif source == SyncSourceType.OPEN_BANKING:
            return (*await self._pull_open_banking(cfg, settings), None)
        elif source == SyncSourceType.GIB_EFATURA:
            return (*await self._pull_efatura(cfg, settings), None)
        elif source == SyncSourceType.BILLING_STRIPE:
            return await self._pull_billing_stripe(schedule.org_id, db=db)
        elif source == SyncSourceType.CRM_EXPORT:
            return (*await self._pull_crm_export(cfg), None)
        elif source == SyncSourceType.HR_EXPORT:
            return (*await self._pull_hr_export(cfg), None)
        elif source == SyncSourceType.GITHUB_ACTIVITY:
            return b"", "", None
        else:
            raise ValueError(f"Unsupported source type: {source}")

    async def _pull_billing_stripe(
        self,
        org_id: str,
        db: Any = None,
    ) -> tuple[bytes, str, str | None]:
        if db is None:
            return b"", "", None
        from app.services.connectors.billing_stripe import pull_stripe_revenue_csv

        return await pull_stripe_revenue_csv(org_id, db)

    async def _pull_crm_export(self, cfg: dict) -> tuple[bytes, str]:
        from app.services.connectors.crm_export import pull_crm_export_csv

        return await pull_crm_export_csv(cfg)

    async def _pull_hr_export(self, cfg: dict) -> tuple[bytes, str]:
        from app.services.connectors.hr_export import pull_hr_export_csv

        return await pull_hr_export_csv(cfg)

    async def _run_github_overlay(self, schedule: SyncScheduleConfig, db: Any, t0: int) -> SyncResult:
        """GitHub is not a ledger source — write CTO velocity onto company context."""
        from app.services.company_context import get_company_context, save_company_context
        from app.services.connectors.github_activity import pull_github_cto_overlay
        from app.services.semantic.rebuild import rebuild_semantic_snapshot

        overlay = await pull_github_cto_overlay(schedule.source_config)
        duration = int(__import__("time").time() * 1000) - t0
        if not overlay:
            return SyncResult(
                schedule_id=schedule.schedule_id,
                org_id=schedule.org_id,
                source_type=schedule.source_type,
                status=SyncStatus.SKIPPED,
                error="GitHub overlay empty — check token/owner/repo",
                duration_ms=duration,
            )
        try:
            ctx = await get_company_context(schedule.org_id, db)
            cto = dict(ctx.last_cto_result or {})
            cto.update(overlay)
            ctx.update_agent_result("cto", cto)
            await save_company_context(ctx, db)
            await rebuild_semantic_snapshot(schedule.org_id, db, include_brief=True)
        except Exception as exc:
            logger.warning("GitHub overlay persist failed: %s", exc)
            return SyncResult(
                schedule_id=schedule.schedule_id,
                org_id=schedule.org_id,
                source_type=schedule.source_type,
                status=SyncStatus.FAILED,
                error=str(exc),
                duration_ms=duration,
            )
        activity = overlay.get("github_activity") or {}
        return SyncResult(
            schedule_id=schedule.schedule_id,
            org_id=schedule.org_id,
            source_type=schedule.source_type,
            status=SyncStatus.SUCCESS,
            row_count=int(activity.get("commit_count") or 0),
            health_score=80,
            duration_ms=duration,
        )

    async def _pull_logo_tiger(self, cfg: dict, settings: Any) -> tuple[bytes, str]:
        # The connector reads an exported CSV (POST /erp/logo-tiger/sync); it has no API to call on a timer.
        raise FeedFailed(
            "Logo Tiger zamanlanmış çekimi desteklenmiyor: bağlayıcı dışa aktarılmış CSV dosyasını okur; "
            "dosyayı /erp/logo-tiger/sync ile yükleyin."
        )

    async def _pull_parasut(
        self,
        cfg: dict,
        settings: Any,
        db: Any = None,
        org_id: str | None = None,
    ) -> tuple[bytes, str, str | None]:
        """Pull the schedule's organisation's Paraşüt invoices.

        `integration_id` comes from the schedule's own config, which a user
        writes. It used to be loaded by id alone, so a schedule could pull
        another organisation's Paraşüt data into this one's analyses. And the
        amounts were guessed: an integer over 1000 was taken for kuruş, anything
        else for lira — the connector's `amount_cents` is always kuruş.

        A missing integration, a refused pull, an outage: all FAILED with the reason (they used to return an
        empty file, which the run reported as "source empty — skipped"). An invoice the connector could not
        read is a row with an empty amount / date, never dropped and never 0.
        """
        integration_id = cfg.get("integration_id")
        if not integration_id or db is None or not org_id:
            raise FeedFailed("Paraşüt çekimi için integration_id, veritabanı ya da kuruluş eksik.")
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration
        from app.services.erp.parasut_connector import ParasutConnector

        integration = (await db.execute(
            select(ERPIntegration).where(ERPIntegration.id == str(integration_id), ERPIntegration.org_id == org_id)
        )).scalar_one_or_none()
        if integration is None:
            logger.warning("Parasut pull refused: integration %s is not org %s's", integration_id, org_id)
            raise FeedFailed("Paraşüt entegrasyonu bu kuruluşa ait değil ya da yok.")
        try:
            pulled = await ParasutConnector(db).islemleri_cek(integration)
        except ValueError as e:
            raise FeedFailed(f"Paraşüt çekimi başarısız: {e}") from e
        transactions = [feed_row_for_csv(r) for r in pulled.rows]
        return _transactions_to_csv(transactions), f"parasut_sync_{_today_str()}.csv", pulled.partial

    async def _pull_open_banking(self, cfg: dict, settings: Any) -> tuple[bytes, str]:
        # The platform's own bank credentials plus an account id a user typed into the schedule would read any
        # account, with no consent of its holder: that is why POST /integrations/open-banking/sync was removed.
        # A bank is pulled only with the holder's OAuth token, through POST /open-banking/connections/{id}/sync.
        raise FeedFailed(
            "Open Banking zamanlanmış çekimi desteklenmiyor: hesap sahibinin rızası (OAuth belirteci) "
            "olmadan hesap hareketi çekilemez; /open-banking bağlantısı üzerinden eşitleyin."
        )

    async def _pull_efatura(self, cfg: dict, settings: Any) -> tuple[bytes, str]:
        # The GİB client returns invoices (gross/net/vat), not the date/amount rows this pipeline reads, and the
        # route that uses them (/efatura/sync) opens no analysis either; scheduled pulls never produced a row.
        raise FeedFailed("e-Fatura zamanlanmış çekimi desteklenmiyor; /efatura uç noktalarını kullanın.")

    async def _create_job(
        self,
        csv_bytes: bytes,
        filename: str,
        org_id: str,
        column_mapping: dict[str, str],
        quality_meta: dict[str, Any] | None,
        db: Any,
        settings: Any,
        feed_meta: dict[str, Any] | None = None,
    ) -> str | None:
        """Create an AnalysisJob from the pulled CSV data."""
        import io

        from fastapi import UploadFile

        from app.models.user import User
        from app.services.upload_service import (
            FileValidationError,
            create_analysis_job,
            stream_to_disk,
        )

        try:
            fake_file = UploadFile(filename=filename, file=io.BytesIO(csv_bytes))
            upload_result = await stream_to_disk(fake_file, "csv", settings.max_upload_size_mb)

            # Get a system user for the org (owner)
            owner_id = await job_owner_id(db, org_id)
            user = await db.get(User, owner_id) if owner_id else None
            if not user:
                logger.warning("No user found for org %s — cannot create job", org_id)
                return None

            job = await create_analysis_job(
                result=upload_result,
                user_id=user.id,
                org_id=org_id,
                db=db,
            )

            # Tam otomasyon: sync ile oluşan job doğrudan analyze kuyruğuna alınır.
            if job:
                try:
                    from app.worker import enqueue_analysis

                    await enqueue_analysis(str(job.id))
                    try:
                        from app.services.agent_bus import get_agent_bus

                        bus = get_agent_bus()
                        await bus.broadcast(
                            from_agent="system",
                            query_type="sync_analysis_enqueued",
                            payload={
                                "source_type": "scheduled_sync",
                                "job_id": str(job.id),
                            },
                            org_id=str(org_id),
                            job_id=str(job.id),
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    logger.warning(
                        "ScheduledSync: enqueue_analysis failed for job=%s: %s",
                        getattr(job, "id", None),
                        exc,
                    )

            # Save column mapping to job metadata
            if job:
                from sqlalchemy import update as sql_update

                from app.models.analysis_job import AnalysisJob
                meta = job.result_metadata or {}
                if column_mapping:
                    meta["column_mapping"] = column_mapping
                meta["sync_auto"] = True
                if feed_meta:
                    meta["feed"] = feed_meta
                if quality_meta:
                    meta.update(quality_meta)
                await db.execute(
                    sql_update(AnalysisJob)
                    .where(AnalysisJob.id == job.id)
                    .values(
                        result_metadata=meta,
                        awaiting_review=bool(quality_meta and quality_meta.get("quality_should_review")),
                    )
                )
                await db.commit()

            return str(job.id) if job else None

        except FileValidationError as e:
            logger.error("Job creation failed (validation): %s", e)
            return None
        except Exception as e:
            logger.error("Job creation failed: %s", e)
            return None

    async def _notify(
        self,
        schedule: SyncScheduleConfig,
        job_id: str | None,
        row_count: int,
        db: Any,
        note: str | None = None,
    ) -> None:
        """Send in-app notification after sync completion."""
        try:
            from app.services.notification_service import get_notification_service
            svc = get_notification_service()
            source_label = schedule.source_type.replace("_", " ").title()
            message = (
                f"{source_label} senkronizasyonu tamamlandı. "
                f"{row_count} işlem çekildi."
            )
            if job_id:
                message += " Analiz başlatıldı."
            if note:
                message += f" {note}"
            await svc.send_org_notification(
                org_id=schedule.org_id,
                title="Otomatik Sync Tamamlandı",
                message=message,
                level="info",
                link=f"/?job={job_id}" if job_id else None,
                db=db,
            )
        except Exception as e:
            logger.debug("Notification failed (non-fatal): %s", e)


# ── Helper functions ──────────────────────────────────────────────────────────

async def job_owner_id(db: Any, org_id: str) -> str | None:
    """The member a scheduled job is booked under: the organisation's owner, else its most senior member.

    Read from memberships, not `users.org_id` (the company someone is acting in right now: an owner
    working in a client's books would leave this company with nobody, and a viewer who happens to be
    acting here would own its jobs). A user with no membership rows falls back to their column.
    """
    from sqlalchemy import select

    from app.models.organization import OrgMembership
    from app.models.user import User

    order = ["owner", "admin", "cfo", "smmm", "analyst", "viewer"]
    rows = (
        await db.execute(
            select(OrgMembership.user_id, OrgMembership.role)
            .join(User, User.id == OrgMembership.user_id)
            .where(OrgMembership.org_id == str(org_id), User.is_active.is_(True))
        )
    ).all()
    if rows:
        best = min(rows, key=lambda r: (order.index(r.role) if r.role in order else len(order), str(r.user_id)))
        return str(best.user_id)
    legacy = (
        await db.execute(select(User.id).where(User.org_id == str(org_id), User.is_active.is_(True)).limit(1))
    ).scalar_one_or_none()
    return str(legacy) if legacy else None


def _outcome_note(outcome: dict[str, Any]) -> str | None:
    """One sentence for a person when the run is not a plain success (held rows, a pull that stopped short)."""
    parts: list[str] = []
    if outcome.get("reason"):
        parts.append(f"Kaynak eksik döndü: {outcome['reason']}; dönem kapsanmış sayılmaz.")
    if outcome.get("held_candidates"):
        parts.append(f"{outcome['held_candidates']} satır kararınızı bekliyor (/bekleyen-kayitlar).")
    if outcome.get("unaccounted"):
        parts.append(f"{outcome['unaccounted']} satır hesaba katılamadı.")
    return " ".join(parts) or None


def feed_row_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    """A pulled row as a CSV line the canonical normalisation reads: a value the source did not state stays EMPTY.

    The amount is the magnitude and the direction is the explicit `type` column; an unknown direction is written "?" (held), an
    unknown amount, date or currency is an empty cell (held). Nothing is filled in.
    """
    cents, kind = row.get("amount_cents"), row.get("type")
    amount: Any = "" if cents is None else cents / 100       # the magnitude: the direction is the `type` column
    return {
        "date": row.get("date") or "", "amount": amount, "description": row.get("description") or "",
        "type": kind or "?", "currency": row.get("currency") or row.get("currency_raw") or "", "reference": row.get("reference") or "",
    }


def _today_str() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _canonical_fingerprint(rows: list[Any]) -> str:
    """Stable hash of canonical rows so identical syncs reuse analysis jobs."""
    import hashlib

    parts: list[str] = []
    for row in rows:
        parts.append(
            "|".join(
                [
                    str(getattr(row, "source_record_id", "") or ""),
                    str(getattr(row, "amount_cents", "") or ""),
                    str(getattr(row, "direction", "") or ""),
                    (
                        getattr(row, "transaction_date", None).isoformat()
                        if getattr(row, "transaction_date", None) is not None
                        and hasattr(getattr(row, "transaction_date", None), "isoformat")
                        else str(getattr(row, "transaction_date", "") or "")
                    ),
                ]
            )
        )
    parts.sort()
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def _transactions_to_csv(transactions: list[dict[str, Any]]) -> bytes:
    """Convert a list of transaction dicts to CSV bytes."""
    import csv
    import io

    if not transactions:
        return b""

    all_keys = list({k for tx in transactions for k in tx})
    # Ensure date and amount come first
    priority = ["date", "amount", "description", "category", "reference"]
    ordered_keys = [k for k in priority if k in all_keys] + \
                   [k for k in all_keys if k not in priority]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ordered_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(transactions)
    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility


# ── Module-level runner singleton ─────────────────────────────────────────────

_sync_runner: ScheduledSyncRunner | None = None


def get_sync_runner() -> ScheduledSyncRunner:
    global _sync_runner
    if _sync_runner is None:
        _sync_runner = ScheduledSyncRunner()
    return _sync_runner


# ── APScheduler hook (called from scheduler.py) ───────────────────────────────

async def run_due_syncs(db: Any, settings: Any) -> list[SyncResult]:
    """
    Find and run all sync schedules that are currently due.
    Called by the APScheduler daily job in scheduler.py.

    In a full implementation, schedules are loaded from DB.
    This stub loads from settings / in-memory config for now.
    """
    results: list[SyncResult] = []
    runner = get_sync_runner()

    # Load schedules from DB (placeholder — full impl uses ORM)
    schedules = await _load_active_schedules(db)

    now = datetime.now(UTC)
    for schedule in schedules:
        if schedule.is_due(now):
            result = await runner.run(schedule, db, settings)
            results.append(result)
            await _remember_run(db, schedule, result)

    return results


async def _remember_run(db: Any, schedule: SyncScheduleConfig, result: SyncResult) -> None:
    """Persist what the run came to on its schedule row: it is what makes a repeated failure a state, not an event."""
    try:
        from app.models.sync_schedule import SyncSchedule

        row = await db.get(SyncSchedule, schedule.schedule_id)
        if row is None:
            return
        row.last_run_at, row.last_status = result.ran_at, result.status
        row.last_error, row.last_job_id = (result.error or None) and str(result.error)[:500], result.job_id
        row.last_row_count, row.last_health_score = result.row_count, result.health_score
        await db.commit()
    except Exception as exc:
        logger.warning("ScheduledSync: could not persist run state: %s", type(exc).__name__)


async def _load_active_schedules(db: Any) -> list[SyncScheduleConfig]:
    """
    Load active sync schedules from the database via ORM.
    Returns empty list if sync_schedules table doesn't exist yet.
    """
    try:
        import json

        from sqlalchemy import select

        from app.models.sync_schedule import SyncSchedule

        result = await db.execute(
            select(SyncSchedule).where(SyncSchedule.enabled.is_(True))
        )
        rows = result.scalars().all()
        schedules: list[SyncScheduleConfig] = []
        for row in rows:
            cfg_raw = row.source_config or "{}"
            try:
                source_config = json.loads(cfg_raw) if isinstance(cfg_raw, str) else (cfg_raw or {})
            except Exception:
                source_config = {}
            schedules.append(
                SyncScheduleConfig(
                    schedule_id=str(row.id),
                    org_id=str(row.org_id),
                    source_type=row.source_type or SyncSourceType.MANUAL_CSV,
                    frequency=row.frequency or SyncFrequency.DAILY,
                    hour_utc=int(row.hour_utc if row.hour_utc is not None else 3),
                    enabled=bool(row.enabled),
                    last_run_at=row.last_run_at,
                    last_status=row.last_status or SyncStatus.IDLE,
                    last_error=row.last_error,
                    source_config=source_config if isinstance(source_config, dict) else {},
                    auto_analyze=bool(row.auto_analyze),
                    notify_on_completion=bool(row.notify_on_completion),
                )
            )
        return schedules
    except Exception as e:
        logger.debug("sync_schedules table not available: %s", e)
        return []
