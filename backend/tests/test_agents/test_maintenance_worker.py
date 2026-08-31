"""Tests for maintenance queue wiring — mocked Redis/ARQ, no network."""

from __future__ import annotations

import asyncio
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
        "run_semantic_rebuild",
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


# ── Inline fallback when the broker is down ───────────────────────────────────
# The upload -> analysis path must not silently drop work on a machine with no
# Redis. It degrades to an inline run, loudly, and only for connection errors.

@pytest.mark.asyncio
async def test_enqueue_analysis_runs_inline_when_broker_unreachable() -> None:
    import app.worker as worker

    mock_settings = MagicMock()
    mock_settings.arq_analysis_queue_name = "arq:queue:analysis"
    mock_settings.allow_inline_job_fallback = True

    ran: list[tuple[str, dict | None]] = []

    async def _fake_run(ctx, job_id, budget_input=None):
        ran.append((job_id, budget_input))
        return {}

    with (
        patch.object(worker, "get_settings", return_value=mock_settings),
        patch.object(
            worker, "get_arq_pool", AsyncMock(side_effect=OSError("Connection refused"))
        ),
        patch.object(worker, "run_cfo_analysis", _fake_run),
    ):
        await worker.enqueue_analysis("job-1", {"revenue": 1})
        # Fire-and-forget: the call returns before the pipeline finishes.
        assert ran == []
        await asyncio.gather(*list(worker._inline_tasks))

    assert ran == [("job-1", {"revenue": 1})]


@pytest.mark.asyncio
async def test_enqueue_analysis_inline_fallback_can_be_disabled() -> None:
    import app.worker as worker

    mock_settings = MagicMock()
    mock_settings.arq_analysis_queue_name = "arq:queue:analysis"
    mock_settings.allow_inline_job_fallback = False

    with (
        patch.object(worker, "get_settings", return_value=mock_settings),
        patch.object(
            worker, "get_arq_pool", AsyncMock(side_effect=OSError("Connection refused"))
        ),
        pytest.raises(OSError, match="Connection refused"),
    ):
        await worker.enqueue_analysis("job-1")


@pytest.mark.asyncio
async def test_enqueue_analysis_does_not_swallow_non_transient_errors() -> None:
    """A bug in the task call is not a broker outage — it must surface."""
    import app.worker as worker

    mock_settings = MagicMock()
    mock_settings.arq_analysis_queue_name = "arq:queue:analysis"
    mock_settings.allow_inline_job_fallback = True

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=TypeError("unexpected kwarg"))

    with (
        patch.object(worker, "get_settings", return_value=mock_settings),
        patch.object(worker, "get_arq_pool", AsyncMock(return_value=mock_pool)),
        pytest.raises(TypeError, match="unexpected kwarg"),
    ):
        await worker.enqueue_analysis("job-1")


def test_demo_seed_calls_enqueue_analysis_with_supported_signature() -> None:
    """Regression: demo.py passed file_path/file_type, which enqueue_analysis
    does not accept — the TypeError was swallowed and the demo never ran."""
    import inspect

    from app.worker import enqueue_analysis

    params = set(inspect.signature(enqueue_analysis).parameters)
    assert params == {"job_id", "budget_input"}

    src = inspect.getsource(__import__("app.api.demo", fromlist=["x"]))
    assert "file_type=" not in src.split("enqueue_analysis(")[1].split(")")[0]
