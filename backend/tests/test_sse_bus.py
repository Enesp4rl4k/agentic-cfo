"""SSE across processes: the bus, the dedupe, and the enforced limits.

The old manager kept process-local queues and dropped every event whose
job had no subscriber *in this process* — which, with an ARQ worker
publishing and uvicorn serving, was all of them. The bridge (Redis
pub/sub) plus an `eid` per event gives exactly-once delivery per
subscriber whichever path the event arrives by: direct (same process) or
bus echo (the listener hearing our own publish).

Tests run with USE_SQLITE=true → the broker is disabled, so they exercise
the local path and the dedupe logic directly.
"""
from __future__ import annotations

import asyncio

from app.streaming import sse as sse_mod
from app.streaming.sse import SSEManager, _Subscriber


def _subscriber(maxsize: int = 10) -> _Subscriber:
    return _Subscriber(queue=asyncio.Queue(maxsize=maxsize))


class TestDedupe:
    def test_the_bus_echo_of_a_delivered_event_is_dropped(self):
        manager = SSEManager()
        sub = _subscriber()
        manager._queues["job-1"] = [sub]

        event = {"event": "step", "step": "pnl", "eid": "abc123"}
        manager._deliver_local("job-1", event)   # direct path
        manager._deliver_local("job-1", dict(event))  # echo via the listener

        assert sub.queue.qsize() == 1  # exactly once, not twice

    def test_different_subscribers_do_not_share_seen_state(self):
        manager = SSEManager()
        a, b = _subscriber(), _subscriber()
        manager._queues["job-1"] = [a, b]
        event = {"event": "step", "eid": "shared"}
        manager._deliver_local("job-1", event)
        manager._deliver_local("job-1", dict(event))
        assert a.queue.qsize() == 1
        assert b.queue.qsize() == 1  # both got exactly one copy

    def test_events_without_eid_are_still_delivered(self):
        # Bus disabled → eid-less events keep working (legacy/local path).
        manager = SSEManager()
        sub = _subscriber()
        manager._queues["job-1"] = [sub]
        manager._deliver_local("job-1", {"event": "step"})
        manager._deliver_local("job-1", {"event": "step"})
        assert sub.queue.qsize() == 2  # no dedupe possible without an id

    def test_full_queue_drops_oldest_not_newest(self):
        manager = SSEManager()
        sub = _subscriber(maxsize=2)
        manager._queues["job-1"] = [sub]
        for i in range(4):
            manager._deliver_local("job-1", {"event": "step", "i": i, "eid": str(i)})
        assert sub.queue.qsize() == 2
        first = sub.queue.get_nowait()
        assert first["i"] == 2  # 0 and 1 were evicted — newest survive


class TestPublish:
    def test_every_publish_gets_a_unique_eid(self, monkeypatch):
        manager = SSEManager()
        captured: list[dict] = []
        monkeypatch.setattr(
            manager, "_deliver_local", lambda job_id, event: captured.append(event)
        )

        async def run():
            await manager.publish("j", {"event": "step"})
            await manager.publish("j", {"event": "step"})

        asyncio.run(run())
        eids = [e["eid"] for e in captured]
        assert len(eids) == 2
        assert len(set(eids)) == 2

    def test_publish_done_clears_the_progress_trail(self):
        # `_completed_steps` grew per job and was never trimmed — a long
        # worker process leaked one list per job forever.
        sse_mod._completed_steps["finished-job"] = ["pnl", "cashflow"]
        manager = SSEManager()
        asyncio.run(manager.publish_done("finished-job", "completed"))
        assert "finished-job" not in sse_mod._completed_steps

    def test_publish_without_a_broker_never_raises(self):
        manager = SSEManager()
        asyncio.run(manager.publish("no-subs", {"event": "step"}))
        asyncio.run(manager.publish_done("no-subs", "completed"))


class TestCapacity:
    def test_connection_count_reflects_live_subscribers(self):
        manager = SSEManager()
        assert manager.connection_count == 0
        manager._get_or_create_job("a").append(_subscriber())
        manager._get_or_create_job("a").append(_subscriber())
        manager._get_or_create_job("b").append(_subscriber())
        assert manager.connection_count == 3  # what /stream checks before 429

        manager._queues["a"].pop()
        manager._queues["b"].pop()
        assert manager.connection_count == 1
