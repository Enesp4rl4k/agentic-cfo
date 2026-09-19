"""Background work is held until it ends, its failure is logged, and it never borrows a request's session."""
from __future__ import annotations

import ast
import asyncio
import gc
import logging
from pathlib import Path

import pytest

from app.core import background

_APP = Path(__file__).resolve().parent.parent / "app"


@pytest.mark.asyncio
async def test_a_spawned_task_survives_garbage_collection():
    done = asyncio.Event()

    async def work():
        await asyncio.sleep(0.01)
        done.set()

    background.spawn(work(), name="gc-probe")
    gc.collect()
    await asyncio.wait_for(done.wait(), 1)


@pytest.mark.asyncio
async def test_a_failure_is_logged_under_the_task_name(caplog):
    async def boom():
        raise RuntimeError("nope")

    with caplog.at_level(logging.ERROR, logger="app.core.background"):
        task = background.spawn(boom(), name="audit-log")
        await asyncio.wait([task])
        await asyncio.sleep(0)
    assert any("audit-log" in r.getMessage() for r in caplog.records)
    assert background.running() == 0


@pytest.mark.asyncio
async def test_with_session_opens_its_own(monkeypatch):
    opened = []

    class FakeSession:
        async def __aenter__(self):
            opened.append(self)
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("app.database.session_factory", lambda: FakeSession)
    got = await background.with_session(lambda db: asyncio.sleep(0, result=db))
    assert got is opened[0]


def test_nothing_fires_and_forgets():
    """A bare `create_task(...)` whose result is dropped is the bug this module exists for."""
    offenders = []
    for path in _APP.rglob("*.py"):
        if path.name == "background.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr in ("create_task", "ensure_future")):
                offenders.append(f"{path.relative_to(_APP.parent)}:{node.lineno}")
    assert offenders == [], "use app.core.background.spawn: " + ", ".join(offenders)
