"""LangSmith / LangGraph traces never carry a payload, whatever the environment says.

Tracing sits outside the choke point (it would export every node's state and every message), so the egress
package forces the hide-inputs / hide-outputs switches on at import, and they win over an environment that
says otherwise. Whether tracing may be switched on at all is telemetry's lock (explicit setting, PR #157's
acknowledgement); preflight warns in production while it is on (test_llm_egress_preflight.py).
"""
from __future__ import annotations

import os

from app.platform.llm_egress import tracing


def test_importing_the_gateway_hides_trace_inputs_and_outputs() -> None:
    import app.platform.model_gateway  # noqa: F401  (the gateway imports the egress package)

    for name in tracing.HIDE_FLAGS:
        assert os.environ.get(name) == "true", name


def test_an_environment_that_says_false_is_overridden(monkeypatch) -> None:
    for name in tracing.HIDE_FLAGS:
        monkeypatch.setenv(name, "false")
    tracing.hide_trace_payloads()
    assert all(os.environ[name] == "true" for name in tracing.HIDE_FLAGS)


def test_langsmith_reads_the_hidden_setting(monkeypatch) -> None:
    from langsmith import utils as ls_utils

    monkeypatch.setenv("LANGSMITH_HIDE_INPUTS", "false")
    ls_utils.get_env_var("HIDE_INPUTS")  # warm langsmith's cache with the wrong value
    tracing.hide_trace_payloads()        # ... which the guard clears
    assert ls_utils.get_env_var("HIDE_INPUTS") == "true" and ls_utils.get_env_var("HIDE_OUTPUTS") == "true"


def test_a_langsmith_client_built_now_hides_run_inputs_and_outputs() -> None:
    from langsmith import Client

    tracing.hide_trace_payloads()
    client = Client(api_key="ls-test-not-a-secret", api_url="http://127.0.0.1:9")  # never contacted
    hide_in = getattr(client, "_hide_run_inputs", None) or getattr(client, "_hide_inputs", None)
    if callable(hide_in):
        assert hide_in({"messages": ["Kanarya Yapı Malzemeleri A.Ş."]}) == {}
    else:
        assert hide_in is True
