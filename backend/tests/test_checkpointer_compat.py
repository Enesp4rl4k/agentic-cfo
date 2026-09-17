"""The checkpointer writes and reads through whichever langgraph saver is installed.

A pipeline run with LANGGRAPH_CHECKPOINT=memory died with
`MemorySaver.aput() takes 4 positional arguments but 5 were given` on a clean
install of the pinned versions: the wrapper passed `new_versions`, which that
saver does not take. The development machine had `langgraph-checkpoint`
installed on top of langgraph, shadowing it with a signature that does — so
nothing local could see it. These tests call the saver the environment
actually has.
"""
from __future__ import annotations

import pytest

from app.agents.checkpointer import get_checkpointer


@pytest.fixture
def saver(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "memory")
    import app.agents.checkpointer as cp

    monkeypatch.setattr(cp, "_CHECKPOINTER", None)
    return get_checkpointer()


def _checkpoint():
    from langgraph.checkpoint.base import empty_checkpoint

    return empty_checkpoint()


def _config(thread: str = "job-1"):
    return {"configurable": {"thread_id": thread}}


def test_a_checkpoint_written_comes_back(saver):
    cfg, cp = _config(), _checkpoint()
    saver.put(cfg, cp, {"source": "input", "step": 1}, {})
    got = saver.get_tuple(_config())
    assert got is not None and got.checkpoint["id"] == cp["id"]
    # The tuple carries the namespace and id the graph then asks for.
    assert got.config["configurable"]["checkpoint_ns"] == ""
    assert got.config["configurable"]["checkpoint_id"] == cp["id"]


@pytest.mark.asyncio
async def test_the_async_path_is_the_one_the_pipeline_uses(saver):
    cfg, cp = _config("job-2"), _checkpoint()
    await saver.aput(cfg, cp, {"source": "loop", "step": 2}, {})
    got = await saver.aget_tuple(_config("job-2"))
    assert got is not None and got.checkpoint["id"] == cp["id"]


@pytest.mark.asyncio
async def test_writes_are_accepted_by_either_saver_signature(saver):
    cfg, cp = _config("job-3"), _checkpoint()
    await saver.aput(cfg, cp, {"source": "loop", "step": 1}, {})
    stored = await saver.aget_tuple(_config("job-3"))
    assert stored is not None
    saver.put_writes(stored.config, [("channel", "value")], "task-1")
    await saver.aput_writes(stored.config, [("channel", "value2")], "task-2")


def test_metadata_may_be_omitted(saver):
    """The wrapper's own defaults must not become positional arguments the saver lacks."""
    saver.put(_config("job-4"), _checkpoint())
    assert saver.get_tuple(_config("job-4")) is not None


@pytest.mark.asyncio
async def test_a_saver_that_does_not_take_new_versions(monkeypatch):
    """CI's signature, reproduced here: the wrapper must not pass a fourth argument."""
    from langgraph.checkpoint.memory import MemorySaver

    import app.agents.checkpointer as cp

    seen: list[tuple] = []

    async def aput(self, config, checkpoint, metadata):      # noqa: ANN001 — the older saver's signature
        seen.append((config, checkpoint, metadata))
        return config

    def put(self, config, checkpoint, metadata):             # noqa: ANN001
        seen.append((config, checkpoint, metadata))
        return config

    monkeypatch.setattr(MemorySaver, "aput", aput)
    monkeypatch.setattr(MemorySaver, "put", put)
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "memory")
    monkeypatch.setattr(cp, "_CHECKPOINTER", None)
    saver = cp.get_checkpointer()

    saver.put(_config("job-5"), _checkpoint(), {"source": "input", "step": 1}, {})
    await saver.aput(_config("job-5"), _checkpoint(), {"source": "loop", "step": 2}, {})
    assert len(seen) == 2
