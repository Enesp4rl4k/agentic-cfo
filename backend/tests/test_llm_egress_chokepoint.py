"""
Architectural guard: the Model Gateway is the single LLM egress point.

``app.platform.model_gateway`` is the only module allowed to construct a model
client (``ChatOpenAI`` / ``AsyncOpenAI`` / ``openai.OpenAI``).  Everything else
must call ``model_gateway.complete`` so that routing, retry, timeout, cost
logging and tracing are applied uniformly.

There is a frozen allow-list of modules that still build clients directly —
the Phase-1 migration backlog.  This test fails if:

  * a module NOT on the allow-list starts constructing a client, or
  * the allow-list grows.

Removing an entry from ``_ALLOWLIST`` (after migrating that module to the
gateway) is always safe and expected.
"""
from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"

# Modules permitted to construct a model client directly. SHRINK ONLY.
# Ideally this is just the gateway itself.
_ALLOWLIST: frozenset[str] = frozenset(
    {
        "platform/model_gateway.py",  # the sanctioned place
    }
)

# Match actual construction / import of a client, not prose mentions in comments.
_CLIENT_RE = re.compile(
    r"(import\s+ChatOpenAI\b"
    r"|\bChatOpenAI\s*\("
    r"|\bAsyncOpenAI\s*\("
    r"|from\s+openai\s+import\b"
    r"|\bopenai\.OpenAI\s*\()"
)


def _offenders() -> set[str]:
    hits: set[str] = set()
    for path in _APP.rglob("*.py"):
        rel = path.relative_to(_APP).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if _CLIENT_RE.search(text):
            hits.add(rel)
    return hits


def test_no_new_direct_model_clients() -> None:
    new = _offenders() - _ALLOWLIST
    assert not new, (
        "Direct LLM client construction outside the Model Gateway:\n  "
        + "\n  ".join(sorted(new))
        + "\n\nCall app.platform.model_gateway.complete(...) instead."
    )


def test_allowlist_does_not_grow() -> None:
    stale = _ALLOWLIST - _offenders()
    assert not stale, (
        "These modules no longer build a client directly — remove them from "
        "_ALLOWLIST:\n  " + "\n  ".join(sorted(stale))
    )


def test_gateway_is_the_sanctioned_egress() -> None:
    gw = (_APP / "platform" / "model_gateway.py").read_text(encoding="utf-8")
    assert "ChatOpenAI(" in gw, "the gateway must be the place that builds the client"
