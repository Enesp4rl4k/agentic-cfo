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
from datetime import datetime, timezone, timedelta
from enum import StrEnum
from typing import Any

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


class SyncSourceType(StrEnum):
    ERP_LOGO_TIGER = "erp_logo_tiger"
    ERP_PARASUT    = "erp_parasut"
    ERP_NETSIS     = "erp_netsis"
    OPEN_BANKING   = "open_banking"
    GIB_EFATURA    = "gib_efatura"
    MANUAL_CSV     = "manual_csv"


# ── Dataclasses ───────────────────────────────────────────────────────────────

class SyncScheduleConfig:
    """
    In-memory config for a sync schedule.
    In production this is backed by the sync_schedules DB table.
    """
    __slots__ = (
        "schedule_id", "org_id", "source_type", "frequency",
        "hour_utc", "enabled", "last_run_at", "last_status",
        "source_config", "auto_analyze", "notify_on_completion",
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
    ) -> None:
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

        now = now or datetime.now(timezone.utc)

        # Hour check
        if now.hour != self.hour_utc:
            return False

        if self.last_run_at is None:
            return True

        delta = now - self.last_run_at

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
        "schedule_id", "org_id", "source_type",
        "status", "job_id", "row_count", "health_score",
        "error", "duration_ms", "ran_at",
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
    ) -> None:
        self.schedule_id = schedule_id
        self.org_id = org_id
        self.source_type = source_type
        self.status = status
        self.job_id = job_id
        self.row_count = row_count
        self.health_score = health_score
        self.error = error
        self.duration_ms = duration_ms
        self.ran_at = ran_at or datetime.now(timezone.utc)

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
            csv_bytes, filename = await self._pull_data(schedule, settings, db=db)
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

            canonical_rows = normalize_csv_transactions(
                csv_bytes=csv_bytes,
                column_mapping=validation.column_mapping,
            )
            quality = score_sync_quality(
                validator_health_score=validation.health_score,
                canonical_row_count=len(canonical_rows),
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

            for row in canonical_rows:
                row_data = to_insert_dict(
                    org_id=schedule.org_id,
                    source_type=schedule.source_type,
                    sync_run_id=sync_run_id,
                    row=row,
                )
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

            # Create analysis job (idempotent when fingerprint unchanged)
            job_id: str | None = None
            if schedule.auto_analyze:
                fingerprint = _canonical_fingerprint(canonical_rows)
                reused = await self._find_reusable_job(
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
                    job_id = await self._create_job(
                        csv_bytes=csv_bytes,
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
                    status=SyncStatus.SUCCESS,
                    row_count_canonical=len(canonical_rows),
                    quality_score=quality.quality_score,
                    triggered_job_id=job_id,
                )

            # Send notification
            if schedule.notify_on_completion:
                await self._notify(schedule, job_id, validation.row_count, db)

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
                status=SyncStatus.SUCCESS,
                job_id=job_id,
                row_count=validation.row_count,
                health_score=validation.health_score,
                duration_ms=duration,
            )

        except Exception as exc:
            logger.error("ScheduledSync: error in %s: %s", schedule.schedule_id, exc)
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
        sr.completed_at = datetime.now(timezone.utc)
        sr.updated_at = datetime.now(timezone.utc)

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
    ) -> tuple[bytes, str]:
        """Pull data from the configured source."""
        source = schedule.source_type
        cfg = schedule.source_config

        if source == SyncSourceType.ERP_LOGO_TIGER:
            return await self._pull_logo_tiger(cfg, settings)
        elif source == SyncSourceType.ERP_PARASUT:
            return await self._pull_parasut(cfg, settings, db=db)
        elif source == SyncSourceType.OPEN_BANKING:
            return await self._pull_open_banking(cfg, settings)
        elif source == SyncSourceType.GIB_EFATURA:
            return await self._pull_efatura(cfg, settings)
        else:
            raise ValueError(f"Desteklenmeyen kaynak tipi: {source}")

    async def _pull_logo_tiger(self, cfg: dict, settings: Any) -> tuple[bytes, str]:
        try:
            from app.services.erp.logo_tiger_connector import LogoTigerConnector
            connector = LogoTigerConnector(settings=settings)
            transactions = await connector.get_transactions(
                from_date=cfg.get("from_date"),
                to_date=cfg.get("to_date"),
            )
            csv_bytes = _transactions_to_csv(transactions)
            return csv_bytes, f"logo_tiger_sync_{_today_str()}.csv"
        except ImportError:
            logger.warning("LogoTigerConnector not available")
            return b"", ""

    async def _pull_parasut(
        self,
        cfg: dict,
        settings: Any,
        db: Any = None,
    ) -> tuple[bytes, str]:
        """
        Pull via ParasutConnector.sync(integration_id).

        source_config must include integration_id (ERPIntegration row).
        Staging without credentials returns empty bytes (caller marks SKIPPED).
        """
        integration_id = cfg.get("integration_id")
        if not integration_id or db is None:
            logger.warning(
                "Parasut pull skipped: missing integration_id or db "
                "(sandbox checklist: connect ERP → set schedule.source_config)"
            )
            return b"", ""
        try:
            from app.services.erp.parasut_connector import ParasutConnector

            connector = ParasutConnector(db)
            result = await connector.sync(str(integration_id))
            raw_txs = result.get("transactions") or []
            transactions: list[dict[str, Any]] = []
            for tx in raw_txs:
                if not isinstance(tx, dict):
                    continue
                amount = tx.get("amount_cents") or tx.get("amount") or 0
                tx_type = str(tx.get("tx_type") or tx.get("type") or "expense").lower()
                try:
                    amount_num = float(amount)
                except (TypeError, ValueError):
                    amount_num = 0.0
                # SyncTransaction stores positive cents; sign via type.
                if abs(amount_num) > 1000 and amount_num == int(amount_num):
                    signed = int(amount_num) / 100.0
                else:
                    signed = float(amount_num)
                if "expense" in tx_type or tx_type == "purchase":
                    signed = -abs(signed)
                else:
                    signed = abs(signed)
                date_val = tx.get("date") or tx.get("transaction_date") or ""
                if hasattr(date_val, "isoformat"):
                    date_val = date_val.isoformat()
                transactions.append(
                    {
                        "date": str(date_val)[:10],
                        "amount": signed,
                        "description": tx.get("description") or "",
                        "category": tx.get("category") or "",
                        "reference": tx.get("reference")
                        or tx.get("source_id")
                        or tx.get("id")
                        or "",
                    }
                )
            csv_bytes = _transactions_to_csv(transactions)
            return csv_bytes, f"parasut_sync_{_today_str()}.csv"
        except ImportError:
            logger.warning("ParasutConnector not available")
            return b"", ""
        except Exception as e:
            logger.warning("Parasut pull failed: %s", e)
            return b"", ""

    async def _pull_open_banking(self, cfg: dict, settings: Any) -> tuple[bytes, str]:
        try:
            from app.services.integrations import TurkiyeOpenBankingClient
            bank_name = cfg.get("bank", "akbank")
            client = TurkiyeOpenBankingClient(bank_name=bank_name, settings=settings)
            transactions = await client.get_transactions(
                account_id=cfg.get("account_id", ""),
                from_date=cfg.get("from_date"),
                to_date=cfg.get("to_date"),
            )
            csv_bytes = _transactions_to_csv(transactions)
            return csv_bytes, f"open_banking_{bank_name}_{_today_str()}.csv"
        except Exception as e:
            logger.warning("OpenBanking pull failed: %s", e)
            return b"", ""

    async def _pull_efatura(self, cfg: dict, settings: Any) -> tuple[bytes, str]:
        try:
            from app.services.gib_efatura import get_efatura_client
            client = get_efatura_client(sandbox=getattr(settings, "gib_efatura_sandbox", True))
            if not client:
                return b"", ""
            transactions = await client.get_all_transactions()
            csv_bytes = _transactions_to_csv(transactions)
            return csv_bytes, f"efatura_sync_{_today_str()}.csv"
        except Exception as e:
            logger.warning("eFatura pull failed: %s", e)
            return b"", ""

    async def _create_job(
        self,
        csv_bytes: bytes,
        filename: str,
        org_id: str,
        column_mapping: dict[str, str],
        quality_meta: dict[str, Any] | None,
        db: Any,
        settings: Any,
    ) -> str | None:
        """Create an AnalysisJob from the pulled CSV data."""
        import io
        from fastapi import UploadFile
        from app.services.upload_service import (
            stream_to_disk, create_analysis_job, FileValidationError
        )
        from app.models.user import User
        from sqlalchemy import select

        try:
            fake_file = UploadFile(filename=filename, file=io.BytesIO(csv_bytes))
            upload_result = await stream_to_disk(fake_file, "csv", settings.max_upload_size_mb)

            # Get a system user for the org (owner)
            result = await db.execute(
                select(User).where(User.org_id == org_id).limit(1)
            )
            user = result.scalar_one_or_none()
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
                message += f" Analiz başlatıldı."
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

def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


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

    all_keys = list({k for tx in transactions for k in tx.keys()})
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

    now = datetime.now(timezone.utc)
    for schedule in schedules:
        if schedule.is_due(now):
            result = await runner.run(schedule, db, settings)
            results.append(result)

    return results


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
                    source_config=source_config if isinstance(source_config, dict) else {},
                    auto_analyze=bool(row.auto_analyze),
                    notify_on_completion=bool(row.notify_on_completion),
                )
            )
        return schedules
    except Exception as e:
        logger.debug("sync_schedules table not available: %s", e)
        return []
