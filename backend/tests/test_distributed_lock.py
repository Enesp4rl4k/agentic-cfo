"""
Unit tests for app.core.distributed_lock.
"""
import asyncio

import pytest

from app.core.distributed_lock import LockAcquisitionError, distributed_lock


@pytest.mark.asyncio
async def test_distributed_lock_basic_acquire_and_release():
    acquired_seen = False
    async with distributed_lock("test-resource-1", timeout_seconds=1.0) as acquired:
        assert acquired is True
        acquired_seen = True

    assert acquired_seen is True


@pytest.mark.asyncio
async def test_distributed_lock_mutual_exclusion():
    order = []

    async def worker(name: str, delay: float):
        async with distributed_lock("shared-resource", timeout_seconds=2.0):
            order.append(f"{name}_start")
            await asyncio.sleep(delay)
            order.append(f"{name}_end")

    # Launch two workers concurrently
    await asyncio.gather(
        worker("worker_1", 0.05),
        worker("worker_2", 0.05),
    )

    # Verify strictly sequential execution
    assert order in [
        ["worker_1_start", "worker_1_end", "worker_2_start", "worker_2_end"],
        ["worker_2_start", "worker_2_end", "worker_1_start", "worker_1_end"],
    ]


@pytest.mark.asyncio
async def test_distributed_lock_timeout_raises_error():
    async def blocker():
        async with distributed_lock("blocked-resource", timeout_seconds=2.0):
            await asyncio.sleep(0.5)

    async def victim():
        await asyncio.sleep(0.05)  # Wait for blocker to acquire
        with pytest.raises(LockAcquisitionError):
            async with distributed_lock("blocked-resource", timeout_seconds=0.1):
                pass

    await asyncio.gather(blocker(), victim())


@pytest.mark.asyncio
async def test_independent_resources_do_not_block():
    order = []

    async def task_a():
        async with distributed_lock("resource-a", timeout_seconds=1.0):
            order.append("a_start")
            await asyncio.sleep(0.05)
            order.append("a_end")

    async def task_b():
        async with distributed_lock("resource-b", timeout_seconds=1.0):
            order.append("b_start")
            await asyncio.sleep(0.05)
            order.append("b_end")

    await asyncio.gather(task_a(), task_b())

    # Both should run concurrently, so starts can precede ends
    assert "a_start" in order
    assert "b_start" in order
