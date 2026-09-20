"""
Session-wide test isolation.

Two independent hazards this file neutralises:

1. ``sys.modules`` stubbing.  Several agent test modules (``test_data_ingestion``,
   ``test_forecast_agent``, ``test_orchestrator_integration``,
   ``test_pipeline_integration``) inject *fake* ``langgraph`` / ``langchain_*``
   modules at import time so they can run in a lean environment.  Each guards
   with ``if mod not in sys.modules`` — but pytest's collection order means a
   stub-injecting module is sometimes imported before the real library is
   loaded, so the fake wins and every later test that needs the real
   ``StateGraph`` (notably ``test_cfo_pipeline`` / ``test_efatura_integration``)
   silently gets a no-op graph.  We pre-import the real libraries here (conftest
   loads before any test module) so those guards always skip, and we restore the
   real modules after every test as a backstop.

2. The database a test reaches without asking.  Code that takes an optional
   session (``app.services.company_context``) opens one of its own when none is
   passed, and that session follows ``DATABASE_URL_OVERRIDE`` — which, unset,
   is the developer's own ``aicfo_dev.db``.  A test run wrote a snapshot row
   into it before this was pinned to a throwaway file below.

3. Process-wide service singletons.  ~20 modules cache a singleton in a module
   global.  A fixture resets the ones that carry cross-test state.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# ── 0. Never the developer's database ────────────────────────────────────────
# Set before anything imports app.config, whose Settings is cached on first use.
if not os.environ.get("DATABASE_URL_OVERRIDE"):
    _TEST_DB = os.path.join(tempfile.gettempdir(), "aicfo_pytest.db")
    os.environ["DATABASE_URL_OVERRIDE"] = f"sqlite+aiosqlite:///{_TEST_DB}"
    os.environ.setdefault("USE_SQLITE", "true")

# ── 1. Pin the real langchain / langgraph modules ────────────────────────────
_REAL_MODULE_NAMES = (
    "langgraph",
    "langgraph.graph",
    "langgraph.constants",
    "langgraph.checkpoint",
    "langgraph.checkpoint.memory",
    "langchain_core",
    "langchain_core.messages",
    "langchain_core.runnables",
    "langchain_core.language_models",
    "langchain_core.language_models.chat_models",
    "langchain_openai",
)

_REAL_MODULES: dict[str, object] = {}
for _name in _REAL_MODULE_NAMES:
    try:
        _REAL_MODULES[_name] = __import__(_name, fromlist=["_"])
    except ImportError:  # pragma: no cover - lean env without the real package
        pass


@pytest.fixture(autouse=True)
def _restore_real_langchain_modules():
    """Undo any ``sys.modules`` stubbing a test (or its import) left behind."""
    yield
    for name, mod in _REAL_MODULES.items():
        if sys.modules.get(name) is not mod:
            sys.modules[name] = mod


# ── 2. Reset stateful service singletons between tests ───────────────────────
def _reset_singletons() -> None:
    resets: list[tuple[str, str]] = [
        ("app.agents.checkpointer", "_CHECKPOINTER"),
        ("app.services.llm_router", "_router_instance"),
        ("app.services.cache_service", "_cache_service_instance"),
        ("app.services.agent_bus", "_bus_instance"),
        ("app.services.agent_memory", "_default_store"),
        ("app.services.company_context", "_ctx_service"),
        ("app.services.conversation_memory", "_conversation_svc"),
        ("app.services.conversation_memory", "_memory_injector"),
        ("app.services.cascade_simulator", "_default_simulator_instance"),
        ("app.services.reasoning_loop", "_reasoning_loop"),
    ]
    for mod_name, attr in resets:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, attr):
            setattr(mod, attr, None)

    gw = sys.modules.get("app.platform.model_gateway")
    if gw is not None and hasattr(gw, "reset_ledger"):
        gw.reset_ledger()

    # In-process rate-limit buckets leak across tests → spurious 429s.
    rl = sys.modules.get("app.middleware.rate_limit")
    if rl is not None and hasattr(rl, "_counters"):
        rl._counters.clear()


@pytest.fixture(autouse=True)
def _isolate_service_singletons():
    _reset_singletons()
    yield
    _reset_singletons()
