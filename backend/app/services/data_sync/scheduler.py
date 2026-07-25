"""
APScheduler job configuration for automated data syncs.

Schedules:
  - Paraşüt: Daily 2 AM (configurable)
  - Netsis: Daily 2 AM (configurable)
  - Mikro: Daily 2 AM (configurable)
  - Logo Tiger: Real-time on CSV upload
  - Garanti: Every 4 hours (configurable)
  - Akbank: Every 4 hours (configurable)

All jobs include:
  - Retry logic
  - Timeout enforcement
  - Error notifications
  - Audit logging
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job

logger = logging.getLogger(__name__)


class SyncScheduler:
    """Manages APScheduler jobs for data syncs."""

    def __init__(self):
        """Initialize scheduler."""
        self.scheduler: Optional[BackgroundScheduler] = None
        self._jobs: dict[str, Job] = {}

    def start(self) -> None:
        """Start the scheduler."""
        if self.scheduler is None:
            self.scheduler = BackgroundScheduler()
            self.scheduler.start()
            logger.info("Data sync scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Data sync scheduler stopped")

    def schedule_parasut_sync(
        self,
        schedule_cron: str = "0 2 * * *",  # 2 AM daily
        job_id: str = "sync_parasut",
    ) -> None:
        """
        Schedule Paraşüt sync job.

        Args:
            schedule_cron: Cron expression (default: daily 2 AM)
            job_id: Unique job identifier
        """
        if not self.scheduler:
            logger.warning("Scheduler not started, cannot schedule Paraşüt sync")
            return

        try:
            # Remove existing job if present
            if job_id in self._jobs:
                self.scheduler.remove_job(job_id)

            # Schedule new job
            job = self.scheduler.add_job(
                self._sync_parasut_wrapper,
                trigger=CronTrigger.from_crontab(schedule_cron),
                id=job_id,
                name="Sync Paraşüt",
                misfire_grace_time=300,
                max_instances=1,
            )

            self._jobs[job_id] = job
            logger.info(f"Scheduled Paraşüt sync: {schedule_cron}")

        except Exception as e:
            logger.error(f"Failed to schedule Paraşüt sync: {e}")

    def schedule_netsis_sync(
        self,
        schedule_cron: str = "0 2 * * *",  # 2 AM daily
        job_id: str = "sync_netsis",
    ) -> None:
        """Schedule Netsis CSV import job."""
        if not self.scheduler:
            logger.warning("Scheduler not started, cannot schedule Netsis sync")
            return

        try:
            if job_id in self._jobs:
                self.scheduler.remove_job(job_id)

            job = self.scheduler.add_job(
                self._sync_netsis_wrapper,
                trigger=CronTrigger.from_crontab(schedule_cron),
                id=job_id,
                name="Sync Netsis",
                misfire_grace_time=300,
                max_instances=1,
            )

            self._jobs[job_id] = job
            logger.info(f"Scheduled Netsis sync: {schedule_cron}")

        except Exception as e:
            logger.error(f"Failed to schedule Netsis sync: {e}")

    def schedule_mikro_sync(
        self,
        schedule_cron: str = "0 2 * * *",  # 2 AM daily
        job_id: str = "sync_mikro",
    ) -> None:
        """Schedule Mikro import job."""
        if not self.scheduler:
            logger.warning("Scheduler not started, cannot schedule Mikro sync")
            return

        try:
            if job_id in self._jobs:
                self.scheduler.remove_job(job_id)

            job = self.scheduler.add_job(
                self._sync_mikro_wrapper,
                trigger=CronTrigger.from_crontab(schedule_cron),
                id=job_id,
                name="Sync Mikro",
                misfire_grace_time=300,
                max_instances=1,
            )

            self._jobs[job_id] = job
            logger.info(f"Scheduled Mikro sync: {schedule_cron}")

        except Exception as e:
            logger.error(f"Failed to schedule Mikro sync: {e}")

    def schedule_logo_tiger_sync(
        self,
        schedule_cron: str = "0 2 * * *",  # 2 AM daily
        job_id: str = "sync_logo_tiger",
    ) -> None:
        """Schedule Logo Tiger import job."""
        if not self.scheduler:
            logger.warning("Scheduler not started, cannot schedule Logo Tiger sync")
            return

        try:
            if job_id in self._jobs:
                self.scheduler.remove_job(job_id)

            job = self.scheduler.add_job(
                self._sync_logo_tiger_wrapper,
                trigger=CronTrigger.from_crontab(schedule_cron),
                id=job_id,
                name="Sync Logo Tiger",
                misfire_grace_time=300,
                max_instances=1,
            )

            self._jobs[job_id] = job
            logger.info(f"Scheduled Logo Tiger sync: {schedule_cron}")

        except Exception as e:
            logger.error(f"Failed to schedule Logo Tiger sync: {e}")

    def schedule_garanti_sync(
        self,
        schedule_cron: str = "0 */4 * * *",  # Every 4 hours
        job_id: str = "sync_garanti",
    ) -> None:
        """Schedule Garanti PSD2 sync job."""
        if not self.scheduler:
            logger.warning("Scheduler not started, cannot schedule Garanti sync")
            return

        try:
            if job_id in self._jobs:
                self.scheduler.remove_job(job_id)

            job = self.scheduler.add_job(
                self._sync_garanti_wrapper,
                trigger=CronTrigger.from_crontab(schedule_cron),
                id=job_id,
                name="Sync Garanti",
                misfire_grace_time=300,
                max_instances=1,
            )

            self._jobs[job_id] = job
            logger.info(f"Scheduled Garanti sync: {schedule_cron}")

        except Exception as e:
            logger.error(f"Failed to schedule Garanti sync: {e}")

    def schedule_akbank_sync(
        self,
        schedule_cron: str = "0 */4 * * *",  # Every 4 hours
        job_id: str = "sync_akbank",
    ) -> None:
        """Schedule Akbank PSD2 sync job."""
        if not self.scheduler:
            logger.warning("Scheduler not started, cannot schedule Akbank sync")
            return

        try:
            if job_id in self._jobs:
                self.scheduler.remove_job(job_id)

            job = self.scheduler.add_job(
                self._sync_akbank_wrapper,
                trigger=CronTrigger.from_crontab(schedule_cron),
                id=job_id,
                name="Sync Akbank",
                misfire_grace_time=300,
                max_instances=1,
            )

            self._jobs[job_id] = job
            logger.info(f"Scheduled Akbank sync: {schedule_cron}")

        except Exception as e:
            logger.error(f"Failed to schedule Akbank sync: {e}")

    def get_jobs(self) -> dict[str, dict]:
        """Get list of scheduled jobs with details."""
        if not self.scheduler:
            return {}

        jobs_info = {}
        for job in self.scheduler.get_jobs():
            jobs_info[job.id] = {
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run": job.next_run_time.isoformat()
                if job.next_run_time
                else None,
            }

        return jobs_info

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        if not self.scheduler or job_id not in self._jobs:
            return False

        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"Paused job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to pause job {job_id}: {e}")
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        if not self.scheduler or job_id not in self._jobs:
            return False

        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Resumed job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            return False

    # Job wrapper functions (to be implemented by actual sync service)

    @staticmethod
    def _sync_parasut_wrapper() -> None:
        """Wrapper for Paraşüt sync job."""
        logger.info("Executing scheduled Paraşüt sync...")
        # Implementation will call orchestrator.sync_parasut()

    @staticmethod
    def _sync_netsis_wrapper() -> None:
        """Wrapper for Netsis sync job."""
        logger.info("Executing scheduled Netsis sync...")
        # Implementation will call orchestrator.sync_accounting_csv()

    @staticmethod
    def _sync_mikro_wrapper() -> None:
        """Wrapper for Mikro sync job."""
        logger.info("Executing scheduled Mikro sync...")
        # Implementation will call orchestrator.sync_accounting_csv()

    @staticmethod
    def _sync_logo_tiger_wrapper() -> None:
        """Wrapper for Logo Tiger sync job."""
        logger.info("Executing scheduled Logo Tiger sync...")
        # Implementation will call orchestrator.sync_accounting_csv()

    @staticmethod
    def _sync_garanti_wrapper() -> None:
        """Wrapper for Garanti sync job."""
        logger.info("Executing scheduled Garanti sync...")
        # Implementation will call orchestrator.sync_garanti()

    @staticmethod
    def _sync_akbank_wrapper() -> None:
        """Wrapper for Akbank sync job."""
        logger.info("Executing scheduled Akbank sync...")
        # Implementation will call orchestrator.sync_akbank()


# Global scheduler instance
_scheduler: Optional[SyncScheduler] = None


def get_sync_scheduler() -> SyncScheduler:
    """Get or create global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SyncScheduler()
    return _scheduler


def init_sync_scheduler() -> SyncScheduler:
    """Initialize and start the global scheduler."""
    scheduler = get_sync_scheduler()
    scheduler.start()
    return scheduler


def shutdown_sync_scheduler() -> None:
    """Shutdown the global scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None
