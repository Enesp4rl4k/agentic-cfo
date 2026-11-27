"""Production never runs agents on per-process memory by accident (checkpointer.py, preflight, /ready).

Before: LANGGRAPH_CHECKPOINT=postgres resolved to a Postgres saver whose package was not installed, the app logged
"DURABILITY LOST" and ran on in-memory checkpoints: no resume after a restart, none across the API and worker
processes. Now production raises (and the process does not start); development and tests still fall back, loudly.
"""
from __future__ import annotations

import logging

import pytest

from app.agents import checkpointer as cp
from app.config import get_settings
from app.core import preflight
from app.core.preflight import FATAL, check_settings


@pytest.fixture(autouse=True)
def _fresh():
    cp.reset_checkpointer()
    yield
    cp.reset_checkpointer()


def _explode(dsn: str):
    raise ImportError("langgraph.checkpoint.postgres is not installed")


def test_thread_ids_are_namespaced_by_organisation_and_run() -> None:
    a, b, job = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "job-1"
    ta = cp.checkpoint_config(job, org_id=a, run_id="r1")["configurable"]["thread_id"]
    tb = cp.checkpoint_config(job, org_id=b, run_id="r1")["configurable"]["thread_id"]
    assert ta == f"{a}:{job}:r1" and tb == f"{b}:{job}:r1" and ta != tb
    assert cp.checkpoint_config(job, org_id=a, run_id="r2")["configurable"]["thread_id"] != ta  # one thread per run
    assert cp.thread_like(a) == f"{a}:%"
    assert cp.checkpoint_config(job, org_id=a, run_id="r1")["recursion_limit"] == cp.RECURSION_LIMIT


@pytest.mark.parametrize("org", [None, "", "-", "org-1", "%", "11111111-1111-4111-8111-11111111111X"])
def test_no_organisation_no_checkpoint_thread(org) -> None:
    """Fail closed: a thread that does not start with its organisation is one no erasure can find."""
    from app.services.privacy.erasure_cleanup import InvalidTargetError

    assert cp.persists(org) is False
    with pytest.raises(InvalidTargetError):
        cp.checkpoint_config("job-1", org_id=org, run_id="r1")
    eph = cp.ephemeral_config({"x": 1})
    assert "thread_id" not in eph["configurable"] and eph["recursion_limit"] == cp.RECURSION_LIMIT


async def test_a_run_without_an_organisation_uses_the_graph_without_a_checkpointer(monkeypatch, tmp_path) -> None:
    from app.agents import orchestrator

    assert orchestrator.cfo_graph_ephemeral.checkpointer is None
    seen: dict[str, object] = {}

    class _Graph:
        def __init__(self, name: str) -> None:
            self.name = name

        async def ainvoke(self, state, config):
            seen.update(graph=self.name, config=config)
            return {**state, "halted": True}

    monkeypatch.setattr(orchestrator, "cfo_graph", _Graph("durable"))
    monkeypatch.setattr(orchestrator, "cfo_graph_ephemeral", _Graph("ephemeral"))
    await orchestrator.run_cfo_pipeline(job_id="j", file_path="", file_type="csv", org_id=None, base_currency="TRY")
    assert seen["graph"] == "ephemeral" and "thread_id" not in seen["config"]["configurable"]

    org = "11111111-1111-4111-8111-111111111111"
    await orchestrator.run_cfo_pipeline(job_id="j", file_path="", file_type="csv", org_id=org, base_currency="TRY")
    first = seen["config"]["configurable"]["thread_id"]
    assert seen["graph"] == "durable" and first.startswith(f"{org}:j:")
    await orchestrator.run_cfo_pipeline(job_id="j", file_path="", file_type="csv", org_id=org, base_currency="TRY")
    assert seen["config"]["configurable"]["thread_id"] != first, "a second run on the job reused the first run's thread"


def test_production_does_not_fall_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "postgres")
    monkeypatch.setattr(get_settings(), "use_sqlite", False)  # not SQLite: a production process
    monkeypatch.setattr(cp, "_postgres_saver", _explode)
    with pytest.raises(cp.CheckpointerUnavailable):
        cp.get_checkpointer()
    with pytest.raises(cp.CheckpointerUnavailable):
        cp.verify_checkpointer()
    status = cp.checkpointer_status()
    assert status["durable"] is False and status["backend"] == "postgres"


def test_development_falls_back_loudly(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "postgres")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(get_settings(), "use_sqlite", True)
    monkeypatch.setattr(cp, "_postgres_saver", _explode)
    with caplog.at_level(logging.WARNING):
        saver = cp.get_checkpointer()
    assert saver is not None
    assert "DURABILITY LOST" in caplog.text
    status = cp.checkpointer_status()
    assert status["backend"] == "memory(fallback)" and status["durable"] is False


def test_memory_chosen_on_purpose_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "memory")
    monkeypatch.setattr(get_settings(), "use_sqlite", False)
    cp.get_checkpointer()  # production process, explicit memory (a throw-away run): allowed, reported as such
    assert cp.checkpointer_status()["durable"] is None


def test_preflight_refuses_a_postgres_checkpointer_whose_packages_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "_missing_modules", lambda names: ["psycopg_pool"])
    settings = get_settings().model_copy(update={"use_sqlite": False})
    found = [f for f in check_settings(settings, {"APP_ENV": "production"}) if f.code == "checkpointer_unavailable"]
    assert found and found[0].severity == FATAL
    # a deliberate memory backend is not refused
    chosen = check_settings(settings, {"APP_ENV": "production", "LANGGRAPH_CHECKPOINT": "memory"})
    assert not [f for f in chosen if f.code == "checkpointer_unavailable"]
