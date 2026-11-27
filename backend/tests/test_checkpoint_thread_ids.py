"""A checkpoint thread id is built in exactly one place, and that place refuses a run without an organisation.

Organisation erasure finds checkpoints by the organisation prefix of the thread id. A thread id built anywhere else
(a bare job id, `-:<job>`) is a row no erasure can find: that is how the CEO path wrote the parsed statement of an
organisation under `<job>-ceo-cfo` (PR #157 review, B1). This test reads the source of `backend/app` and fails on any
other construction, on any other checkpointed graph, or on a config handed to that graph that was not built by
`checkpointer.checkpoint_config`.
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
BUILDER = APP / "agents" / "checkpointer.py"  # checkpoint_config: the only caller of thread_key
DATA = APP / "services" / "checkpoint_data.py"  # thread_key itself, and the tables' thread_id column
CFO = APP / "agents" / "orchestrator.py"  # the only graph compiled with a checkpointer


def _sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8", errors="ignore") for p in APP.rglob("*.py")}


def _hits(pattern: str) -> set[Path]:
    rx = re.compile(pattern)
    return {p for p, text in _sources().items() if rx.search(text)}


def test_thread_ids_are_built_only_by_checkpoint_config() -> None:
    assert _hits(r"\bthread_key\s*\(") == {BUILDER, DATA}
    assert len(re.findall(r"\bthread_key\s*\(", BUILDER.read_text(encoding="utf-8"))) == 1
    # A literal "thread_id" key anywhere else would be a thread id built by hand.
    assert _hits(r"""["']thread_id["']""") <= {BUILDER, DATA}
    assert _hits(r"\bthread_id\s*=") <= {DATA}  # SQL comparisons on the column only


def test_only_the_cfo_graph_is_checkpointed_and_only_with_built_configs() -> None:
    assert _hits(r"checkpointer\s*=") == {CFO}
    src = CFO.read_text(encoding="utf-8")
    # The durable graph is invoked with checkpoint_config (org-namespaced, fresh run id) or not at all; a run without
    # an organisation goes to the graph compiled without a checkpointer.
    assert re.search(r"graph,\s*config\s*=\s*cfo_graph,\s*checkpoint_config\(", src)
    assert re.search(r"graph,\s*config\s*=\s*cfo_graph_ephemeral,\s*ephemeral_config\(", src)
    assert "if persists(org_id):" in src
    assert re.search(r"run_id=uuid\.uuid4\(\)", src), "every run must get its own thread"
    assert not re.search(r"cfo_graph\.a?invoke\(", src)


def test_thread_key_refuses_a_missing_organisation() -> None:
    import pytest

    from app.services.checkpoint_data import thread_key
    from app.services.privacy.erasure_cleanup import InvalidTargetError

    for org in (None, "", "-", "not-a-uuid"):
        with pytest.raises(InvalidTargetError):
            thread_key(org, "job", "run")  # type: ignore[arg-type]
