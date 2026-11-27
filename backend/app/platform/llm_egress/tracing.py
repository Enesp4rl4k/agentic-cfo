"""LangSmith / LangGraph run tracing: never a way around the choke point.

Tracing would export, for every LangGraph node and model run, its inputs and outputs: the orchestrators' raw
state (company figures, names, document text) and the messages, regardless of `LLM_DATA_MODE`. So:

* it is OFF unless the explicit, documented settings turn it on (`LANGSMITH_ENABLED=true`; with the
  langchain upgrade, PR #157, also the acknowledgement `LANGSMITH_EXTERNAL_TRACING_ACK`, and every stray
  `LANGCHAIN_TRACING_V2` / `LANGSMITH_TRACING` is forced off at start: `services.telemetry`);
* even when on, no payload leaves: this module forces `LANGSMITH_HIDE_INPUTS` and `LANGSMITH_HIDE_OUTPUTS`
  (and the LANGCHAIN_ spellings) to "true" for the whole process, at import, before any run is traced.
  A trace then carries run names, timings, token counts and errors only. Nothing masked or unmasked;
* preflight warns in production while it is on (`langsmith_tracing_on`).

`tests/test_llm_egress_tracing.py` holds both: the flags are set, and a traced run's inputs do not reach the
LangSmith client.
"""
from __future__ import annotations

import os

HIDE_FLAGS = ("LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS", "LANGCHAIN_HIDE_INPUTS", "LANGCHAIN_HIDE_OUTPUTS")


def hide_trace_payloads() -> None:
    """Force every hide flag on (whatever the environment says) and drop langsmith's cached reading of it."""
    for name in HIDE_FLAGS:
        os.environ[name] = "true"
    try:
        from langsmith import utils as ls_utils

        cache_clear = getattr(ls_utils.get_env_var, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()
    except Exception:  # langsmith absent: nothing can trace
        pass


hide_trace_payloads()
