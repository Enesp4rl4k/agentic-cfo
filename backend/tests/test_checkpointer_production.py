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


def test_thread_ids_are_namespaced_by_organisation() -> None:
    a, b, job = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "job-1"
    ta = cp.checkpoint_config(job, org_id=a)["configurable"]["thread_id"]
    tb = cp.checkpoint_config(job, org_id=b)["configurable"]["thread_id"]
    assert ta == f"{a}:{job}" and tb == f"{b}:{job}" and ta != tb
    assert cp.thread_like(a) == f"{a}:%"
    # without an organisation the id is what it always was (callers that have none, tests)
    assert cp.checkpoint_config(job)["configurable"]["thread_id"] == job


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
