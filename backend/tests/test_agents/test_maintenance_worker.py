"""Tests for maintenance queue wiring — mocked Redis/ARQ, no network."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_worker_settings_partitioned() -> None:
    from app.worker import MaintenanceWorkerSettings, WorkerSettings

    analysis_names = {f.__name__ for f in WorkerSettings.functions}
    maintenance_names = {f.__name__ for f in MaintenanceWorkerSettings.functions}

    assert analysis_names == {"run_cfo_analysis", "run_ceo_analysis"}
    assert maintenance_names == {
        "run_rag_backfill_maintenance",
        "run_usage_prune_maintenance",
    }
    assert WorkerSettings.queue_name != MaintenanceWorkerSettings.queue_name


def test_worker_settings_have_redis_settings() -> None:
    from app.worker import MaintenanceWorkerSettings, WorkerSettings

    assert hasattr(WorkerSettings, "redis_settings")
    assert hasattr(MaintenanceWorkerSettings, "redis_settings")


@pytest.mark.asyncio
async def test_enqueue_maintenance_job_uses_lock_and_queue() -> None:
    mock_pool = AsyncMock()
    mock_pool.set = AsyncMock(return_value=True)
    mock_pool.enqueue_job = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.arq_maintenance_queue_name = "arq:queue:maintenance"

    with (
        patch("app.worker.get_arq_pool", return_value=mock_pool),
        patch("app.worker.get_settings", return_value=mock_settings),
    ):
        from app.worker import enqueue_maintenance_job

        result = await enqueue_maintenance_job("run_rag_backfill_maintenance")

    assert result is True
    mock_pool.set.assert_awaited_once()
    mock_pool.enqueue_job.assert_awaited_once()
    assert (
        mock_pool.enqueue_job.await_args.kwargs["_queue_name"]
        == "arq:queue:maintenance"
    )


@pytest.mark.asyncio
async def test_enqueue_maintenance_skips_when_lock_held() -> None:
    mock_pool = AsyncMock()
    mock_pool.set = AsyncMock(return_value=False)

    with patch("app.worker.get_arq_pool", return_value=mock_pool):
        from app.worker import enqueue_maintenance_job

        result = await enqueue_maintenance_job("run_usage_prune_maintenance")

    assert result is False
    mock_pool.enqueue_job.assert_not_awaited()
