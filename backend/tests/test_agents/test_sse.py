"""
Tests for sse.py — progress tracking and event publishing helpers.
No real EventSource or network needed — tests pure functions only.
"""
import asyncio
import pytest
from app.streaming.sse import (
    SSEManager,
    _calc_progress_pct,
    _completed_steps,
    _PIPELINE_STEPS,
    publish_step_event,
    publish_agent_start_event,
    publish_job_done,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clear_job(job_id: str):
    _completed_steps.pop(job_id, None)


# ── _calc_progress_pct ────────────────────────────────────────────────────────

class TestCalcProgressPct:

    def setup_method(self):
        _clear_job("test-job")

    def test_zero_steps_returns_zero(self):
        _clear_job("empty")
        assert _calc_progress_pct("empty") == 0

    def test_all_steps_returns_100(self):
        _completed_steps["full"] = list(_PIPELINE_STEPS)
        assert _calc_progress_pct("full") == 100
        _clear_job("full")

    def test_half_steps_returns_around_50(self):
        half = list(_PIPELINE_STEPS[: len(_PIPELINE_STEPS) // 2])
        _completed_steps["half"] = half
        pct = _calc_progress_pct("half")
        assert 40 <= pct <= 60
        _clear_job("half")

    def test_current_step_adds_half_credit(self):
        _completed_steps["j1"] = [_PIPELINE_STEPS[0]]  # 1 done
        pct_without = _calc_progress_pct("j1")
        pct_with = _calc_progress_pct("j1", current_step=_PIPELINE_STEPS[1])
        assert pct_with > pct_without
        _clear_job("j1")

    def test_current_step_already_done_no_double_count(self):
        _completed_steps["j2"] = [_PIPELINE_STEPS[0]]
        pct_without = _calc_progress_pct("j2")
        # Same step as already completed → no extra credit
        pct_with = _calc_progress_pct("j2", current_step=_PIPELINE_STEPS[0])
        assert pct_with == pct_without
        _clear_job("j2")

    def test_max_capped_at_100(self):
        _completed_steps["j3"] = list(_PIPELINE_STEPS) * 3
        assert _calc_progress_pct("j3") == 100
        _clear_job("j3")

    def test_unknown_step_ignored(self):
        _completed_steps["j4"] = ["unknown_step_xyz"]
        assert _calc_progress_pct("j4") == 0
        _clear_job("j4")


# ── publish_step_event ────────────────────────────────────────────────────────

class TestPublishStepEvent:

    def setup_method(self):
        _clear_job("pub-job")

    def test_successful_step_tracked(self):
        asyncio.run(publish_step_event("pub-job", "pnl", ok=True, confidence=0.95))
        assert "pnl" in _completed_steps.get("pub-job", [])

    def test_failed_step_not_tracked(self):
        asyncio.run(publish_step_event("pub-job", "cashflow", ok=False))
        assert "cashflow" not in _completed_steps.get("pub-job", [])

    def test_progress_increases_after_step(self):
        _clear_job("prog-job")
        asyncio.run(publish_step_event("prog-job", _PIPELINE_STEPS[0], ok=True))
        asyncio.run(publish_step_event("prog-job", _PIPELINE_STEPS[1], ok=True))
        pct = _calc_progress_pct("prog-job")
        assert pct > 0
        _clear_job("prog-job")

    def test_duplicate_step_not_counted_twice(self):
        _clear_job("dup-job")
        asyncio.run(publish_step_event("dup-job", "pnl", ok=True))
        asyncio.run(publish_step_event("dup-job", "pnl", ok=True))  # duplicate
        assert _completed_steps["dup-job"].count("pnl") == 1
        _clear_job("dup-job")


# ── SSEManager ────────────────────────────────────────────────────────────────

class TestSSEManager:

    def test_publish_with_no_subscribers_does_not_raise(self):
        manager = SSEManager()
        asyncio.run(manager.publish("no-subs", {"event": "test"}))

    def test_publish_done_with_no_subscribers(self):
        manager = SSEManager()
        asyncio.run(manager.publish_done("no-subs", "completed"))

    def test_subscribe_receives_published_events(self):
        manager = SSEManager()

        async def run():
            received = []

            async def subscriber():
                async for chunk in manager.subscribe("job-x"):
                    received.append(chunk)
                    break  # take just first event

            # Publish after a tiny delay so subscriber connects first
            async def publisher():
                await asyncio.sleep(0.01)
                await manager.publish("job-x", {"event": "step", "step": "pnl"})
                await manager.publish_done("job-x", "completed")

            await asyncio.gather(subscriber(), publisher())
            return received

        received = asyncio.run(run())
        assert len(received) >= 1
        assert "pnl" in received[0]  # SSE text contains the event data

    def test_subscribe_auto_closes_on_sentinel(self):
        manager = SSEManager()

        async def run():
            chunks = []

            async def subscriber():
                async for chunk in manager.subscribe("job-y"):
                    chunks.append(chunk)

            async def publisher():
                await asyncio.sleep(0.01)
                await manager.publish_done("job-y", "completed")

            await asyncio.wait_for(
                asyncio.gather(subscriber(), publisher()),
                timeout=2.0,
            )
            return chunks

        chunks = asyncio.run(run())
        # Should have received done event and then closed
        assert any("done" in c for c in chunks)


# ── _PIPELINE_STEPS constants ─────────────────────────────────────────────────

def test_pipeline_steps_not_empty():
    assert len(_PIPELINE_STEPS) >= 5


def test_pipeline_steps_includes_core():
    for step in ("data_ingestion", "pnl", "cashflow", "forecast", "report"):
        assert step in _PIPELINE_STEPS
