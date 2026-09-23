"""Checkpoints that do not outlive their process are not checkpoints.

The factory used to call `_memory_saver()` from all three of its branches —
sqlite and postgres existed as dead code, so every "resume" claim rested on
memory that died with the process. These tests pin the three things that
made that survivable-to-hide and cheap-to-check:

  1. the backend actually follows the deployment (or an explicit env),
  2. a write on one instance is readable from a *new* instance on the same
     file — the closest thing to a process restart a unit test can stage,
  3. a backend that cannot build falls back LOUDLY, never silently.

Correctness without a durable checkpoint still holds — nodes are
idempotent recomputes (run_ledger) and the worker purges outputs before
rewriting — so the fallback is a performance loss, not a data loss. It
still must be visible: silent is how the previous bug survived.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

import app.agents.checkpointer as cp
from app.agents.checkpointer import (
    get_checkpointer,
    reset_checkpointer,
    resolve_checkpoint_backend,
)
from app.config import get_settings


def _checkpoint():
    from langgraph.checkpoint.base import empty_checkpoint

    return empty_checkpoint()


def _config(thread: str = "durability-1"):
    return {"configurable": {"thread_id": thread}}


# ── 1. Backend selection ──────────────────────────────────────────────────────


def test_explicit_env_always_wins(monkeypatch):
    for explicit in ("memory", "sqlite", "postgres"):
        monkeypatch.setenv("LANGGRAPH_CHECKPOINT", explicit)
        assert resolve_checkpoint_backend() == explicit


def test_without_env_the_deployment_decides(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_CHECKPOINT", raising=False)
    settings = get_settings()
    monkeypatch.setattr(settings, "use_sqlite", True)
    assert resolve_checkpoint_backend() == "sqlite"
    monkeypatch.setattr(settings, "use_sqlite", False)
    assert resolve_checkpoint_backend() == "postgres"


# ── 2. Durability across "restarts" ───────────────────────────────────────────


@pytest.fixture
def sqlite_backend(tmp_path, monkeypatch):
    path = str(tmp_path / "checkpoints.sqlite")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "sqlite")
    monkeypatch.setattr(get_settings(), "checkpoint_sqlite_path", path)
    reset_checkpointer()
    yield path
    reset_checkpointer()


def test_a_write_survives_a_process_restart(sqlite_backend):
    # First "process": write a checkpoint, then drop the singleton entirely.
    saver1 = get_checkpointer()
    cp_state = _checkpoint()
    assert saver1.put(_config(), cp_state, {"source": "input", "step": 1}, {})
    reset_checkpointer()

    # Second "process": same file, fresh instance, nothing shared but disk.
    saver2 = get_checkpointer()
    got = asyncio.run(saver2.aget_tuple(_config()))
    assert got is not None
    assert got.checkpoint["id"] == cp_state["id"]
    # The tuple carries what the graph then asks for:
    assert got.config["configurable"]["checkpoint_ns"] == ""
    assert got.config["configurable"]["checkpoint_id"] == cp_state["id"]


def test_the_async_path_the_pipeline_uses_lands_on_disk(sqlite_backend):
    # The graph writes via aput/aput_writes (the async bridge); a later
    # *sync* reader must see it — i.e. it hit the file, not a thread-local.
    saver = get_checkpointer()
    state = _checkpoint()
    asyncio.run(saver.aput(_config("durability-async"), state, {"step": 2}, {}))
    reset_checkpointer()
    fresh = get_checkpointer()
    got = fresh.get_tuple(_config("durability-async"))
    assert got is not None
    assert got.checkpoint["id"] == state["id"]


# ── 3. Loud fallback ──────────────────────────────────────────────────────────


def test_a_backend_that_cannot_build_says_so_loudly(monkeypatch, caplog):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "sqlite")
    monkeypatch.setattr(
        get_settings(),
        "checkpoint_sqlite_path",
        "\\\\nonexistent\\\\device\\\\cp.sqlite",
    )

    def _explode(path: str):
        raise RuntimeError("no disk")

    monkeypatch.setattr(cp, "_sqlite_saver", _explode)
    reset_checkpointer()
    with caplog.at_level(logging.WARNING, logger="app.agents.checkpointer"):
        saver = get_checkpointer()

    assert saver is not None  # the app still runs — recompute, not crash
    assert any("DURABILITY LOST" in rec.message for rec in caplog.records)
    assert any("idempotent" in rec.message for rec in caplog.records)
