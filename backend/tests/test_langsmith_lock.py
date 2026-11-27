"""LangSmith tracing ships every prompt (company data, KVKK) to a third party.

langchain-core depends on langsmith, so an ambient LANGSMITH_TRACING=true or
LANGCHAIN_TRACING_V2=true would export runs without the app deciding to. The
telemetry module forces every switch off and turns tracing on only for
LANGSMITH_ENABLED=true plus the written acknowledgement.
"""
from __future__ import annotations

import os

import pytest

from app.services import telemetry

SWITCHES = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*SWITCHES, "LANGSMITH_ENABLED", "LANGSMITH_API_KEY", "LANGSMITH_EXTERNAL_TRACING_ACK"):
        monkeypatch.delenv(name, raising=False)


def _all_off() -> bool:
    return all(os.environ.get(n) == "false" for n in SWITCHES)


def test_ambient_tracing_flags_are_forced_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SWITCHES:
        monkeypatch.setenv(name, "true")
    telemetry.lock_langsmith_tracing()
    assert _all_off()


def test_enabled_without_acknowledgement_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    assert telemetry.setup_langsmith() is False
    assert _all_off()


def test_ambient_flags_do_not_survive_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert telemetry.setup_langsmith() is False
    assert _all_off()


def test_wrong_acknowledgement_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_EXTERNAL_TRACING_ACK", "yes")
    assert telemetry.setup_langsmith() is False
    assert _all_off()


def test_explicit_setting_with_acknowledgement_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_EXTERNAL_TRACING_ACK", telemetry.LANGSMITH_EXPORT_ACK)
    try:
        assert telemetry.setup_langsmith() is True
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    finally:
        telemetry.lock_langsmith_tracing()
