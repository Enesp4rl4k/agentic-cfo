"""No test reads the wall clock behind the pinned one's back (app/core/clock.py, tests/conftest.py section 1b).

Four master-red incidents in a week came from tests whose outcome depended on the day they ran. In a test,
`datetime.now()` / `date.today()` read the pinned clock and are safe; what is NOT pinned is `time.time()`,
`time.strftime()` / `localtime()` / `gmtime()` / `ctime()` without an explicit time, pandas' own `Timestamp.now()`,
the stdlib `datetime` fetched by name (`importlib.import_module("datetime")`), and the clock's own escape hatches.
A test that uses one must either be marked `@pytest.mark.real_clock(reason=...)` or be listed below with the
reason it cannot flip at a date boundary. The browser journey (Playwright) must take "today" from the journey's
simulated date (`e2e/support/fixtures.ts` `E2E_NOW`), never from `new Date()` / `Date.now()`.

The Python scan is AST-based and follows import aliases (`import time as t`, `from time import time`).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"

# Wall-clock readers, by the dotted name they resolve to once import aliases are followed.
# `time.<name>(...)` with no argument reads the wall clock (`strftime` with only a format, too).
_TIME_NOARG = {"time.time", "time.time_ns", "time.localtime", "time.gmtime", "time.ctime", "time.asctime"}
_TIME_FORMAT_ONLY = {"time.strftime"}
# pandas / numpy read the machine clock themselves, behind the pinned one's back.
_PANDAS_NOW = {"pandas.Timestamp.now", "pandas.Timestamp.today", "pandas.Timestamp.utcnow", "pandas.Period.now"}
_NOW_STRING = {"pandas.Timestamp", "pandas.to_datetime", "numpy.datetime64"}  # called with "now" / "today"
# Importing the stdlib module by name skips the scoped import hook and so returns the real `datetime`.
_IMPORT_BY_NAME = {"importlib.import_module", "builtins.__import__", "__import__"}
_ESCAPES = {"wall_now", "unpin", "real_datetime", "real_date"}

# (file, call): why it cannot flip at a date boundary. Keep each entry's reason honest.
ALLOWED = {
    # The product's own wall-clock stamps, compared with a wall-clock reading (seconds, never a date):
    ("test_agents/test_memory.py", "time.time"): "memory entries' float timestamps; ordering and TTL in seconds",
    ("test_demo_guest_flag_and_webhooks.py", "time.time"): "webhook signature timestamp checked against time.time() by the product",
    ("test_outbox_classes.py", "time.time"): "webhook signature timestamp checked against time.time() by the product",
    ("test_ops_endpoints.py", "time.time"): "worker heartbeat ages in seconds; the product reads time.time()",
    ("test_outward_effects_outbox.py", "time.time"): "alert created_at float stamp, ordering only",
    ("test_proactive_alerts_scan.py", "time.time"): "alert created_at float stamp, ordering only",
    ("test_parasut.py", "time.time"): "OAuth state age in seconds; the product signs and checks it with time.time()",
    # The clock's own tests and the session fixture.
    ("conftest.py", "_clock.unpin"): "the real_clock opt-out itself",
    ("test_clock.py", "clock.wall_now"): "proves the wall clock is reachable and tokens are stamped by it",
    ("test_clock.py", "clock.real_datetime"): "proves isinstance() still accepts stdlib datetimes",
    ("test_clock.py", "clock.real_date"): "proves isinstance() still accepts stdlib dates",
}


def _marked_real_clock(node: ast.AST) -> bool:
    return any("real_clock" in ast.unparse(deco) for deco in getattr(node, "decorator_list", []))


def _module_marked(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "real_clock" in ast.unparse(n.value)
        for n in tree.body
    )


def _aliases(tree: ast.AST) -> dict[str, str]:
    """local name -> the dotted name it was imported as (module level and inside functions alike)."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[(a.asname or a.name).split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _canonical(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """`t.time` -> `time.time`, `pd.Timestamp.now` -> `pandas.Timestamp.now`, `now` -> `time.time` (if so imported)."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([aliases.get(node.id, node.id), *reversed(parts)])


def _literal(call: ast.Call) -> object:
    arg = call.args[0] if call.args else None
    return arg.value if isinstance(arg, ast.Constant) else None


def _wall_clock_calls(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    aliases = _aliases(tree)

    def visit(node: ast.AST, exempt: bool) -> None:
        exempt = exempt or _marked_real_clock(node)
        if not exempt:
            if isinstance(node, ast.Call):
                name = _canonical(node.func, aliases)
                if (name in _TIME_NOARG and not node.args) or (name in _TIME_FORMAT_ONLY and len(node.args) <= 1) or (name in _PANDAS_NOW and not node.args):
                    out.append((node.lineno, name))
                elif name in _NOW_STRING and str(_literal(node)).lower() in {"now", "today"}:
                    out.append((node.lineno, f"{name}({_literal(node)!r})"))
                elif name in _IMPORT_BY_NAME and _literal(node) == "datetime":
                    out.append((node.lineno, f"{name}('datetime')"))
            if isinstance(node, ast.Attribute) and node.attr in _ESCAPES:
                out.append((node.lineno, f"{ast.unparse(node.value)}.{node.attr}"))
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == "clock":
                out.extend((node.lineno, f"from {node.module} import {a.name}") for a in node.names if a.name in _ESCAPES)
        for child in ast.iter_child_nodes(node):
            visit(child, exempt)

    visit(tree, False)
    return out


def test_no_python_test_reads_the_wall_clock_unannounced() -> None:
    found: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(TESTS).as_posix()
        if rel == "test_clock_guard.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _module_marked(tree):
            continue
        for line, call in _wall_clock_calls(tree):
            if (rel, call) not in ALLOWED:
                found.append(f"{rel}:{line} {call}")
    assert not found, (
        "These tests read the wall clock, not the pinned test clock: use datetime.now()/date.today() (pinned), "
        "or mark the test @pytest.mark.real_clock(reason=...), or add it to ALLOWED with why it cannot flip:\n  "
        + "\n  ".join(found)
    )


def test_every_allowance_is_still_used() -> None:
    used: set[tuple[str, str]] = set()
    for path in TESTS.rglob("*.py"):
        rel = path.relative_to(TESTS).as_posix()
        used |= {(rel, call) for _, call in _wall_clock_calls(ast.parse(path.read_text(encoding="utf-8")))}
    assert set(ALLOWED) - used == set(), f"stale allowances (remove them): {sorted(set(ALLOWED) - used)}"


def test_the_guard_sees_what_it_guards() -> None:
    sample = ast.parse(
        "import time\nfrom app.core import clock\n"
        "def test_a():\n    time.time(); time.strftime('%Y'); clock.wall_now()\n"
        "def test_b():\n    time.strftime('%Y', t); time.monotonic(); time.sleep(1)\n"
        "@pytest.mark.real_clock(reason='x')\ndef test_c():\n    time.time()\n"
    )
    assert [c for _, c in _wall_clock_calls(sample)] == ["time.time", "time.strftime", "clock.wall_now"]


# Each way round the guard that review found, written to a temp file and scanned like a real test file: the
# guard must flag it. (A guard nobody has seen fail is a guard nobody knows works.)
MUTATIONS = {
    "from time import time": ("from time import time\ndef test_x():\n    time()\n", "time.time"),
    "from time import time as now": ("from time import time as now\ndef test_x():\n    now()\n", "time.time"),
    "import time as t": ("import time as t\ndef test_x():\n    t.time()\n", "time.time"),
    "time.time_ns()": ("import time\ndef test_x():\n    time.time_ns()\n", "time.time_ns"),
    "from time import localtime": ("from time import localtime\ndef test_x():\n    localtime()\n", "time.localtime"),
    "from time import strftime": ("from time import strftime\ndef test_x():\n    strftime('%Y')\n", "time.strftime"),
    "import real_datetime": (
        "from app.core.clock import real_datetime\ndef test_x():\n    pass\n",
        "from app.core.clock import real_datetime",
    ),
    "import real_date as d": ("from app.core.clock import real_date as d\n", "from app.core.clock import real_date"),
    "importlib.import_module": (
        "import importlib\ndef test_x():\n    importlib.import_module('datetime').datetime.now()\n",
        "importlib.import_module('datetime')",
    ),
    "from importlib import import_module": (
        "from importlib import import_module\ndef test_x():\n    import_module('datetime')\n",
        "importlib.import_module('datetime')",
    ),
    "__import__": ("def test_x():\n    __import__('datetime').datetime.now()\n", "__import__('datetime')"),
    "pd.Timestamp.now()": ("import pandas as pd\ndef test_x():\n    pd.Timestamp.now()\n", "pandas.Timestamp.now"),
    "Timestamp.today()": ("from pandas import Timestamp\ndef test_x():\n    Timestamp.today()\n", "pandas.Timestamp.today"),
    "pd.Timestamp('now')": ("import pandas as pd\ndef test_x():\n    pd.Timestamp('now')\n", "pandas.Timestamp('now')"),
    "pd.to_datetime('today')": ("import pandas as pd\ndef test_x():\n    pd.to_datetime('today')\n", "pandas.to_datetime('today')"),
    "np.datetime64('now')": ("import numpy as np\ndef test_x():\n    np.datetime64('now')\n", "numpy.datetime64('now')"),
    "import inside a function": ("def test_x():\n    import time as t\n    return t.time()\n", "time.time"),
}
# What a test may do: nothing here reads the wall clock.
INNOCENT = [
    "import time\ndef test_x():\n    time.sleep(0); time.monotonic(); time.perf_counter(); time.strftime('%Y', t)\n",
    "from time import sleep, monotonic\ndef test_x():\n    sleep(0); monotonic()\n",
    "import pandas as pd\ndef test_x():\n    pd.Timestamp('2026-11-25'); pd.to_datetime('2026-11-25')\n",
    "import importlib\ndef test_x():\n    importlib.import_module('json')\n",
    "from datetime import datetime\ndef test_x():\n    datetime.now(); datetime.today()\n",
    "from app.core import clock\nfrom app.core.clock import now, TEST_INSTANT\ndef test_x():\n    clock.pin(TEST_INSTANT); now()\n",
    "import time\nimport pytest\n@pytest.mark.real_clock(reason='x')\ndef test_x():\n    time.time(); time.time_ns()\n",
    "def time():\n    return 1\ndef test_x():\n    time()\n",  # a local `time`, not the module's
]


@pytest.mark.parametrize("label", sorted(MUTATIONS))
def test_the_guard_catches_each_known_way_round_it(label: str, tmp_path: Path) -> None:
    source, expected = MUTATIONS[label]
    mutant = tmp_path / "test_mutant.py"
    mutant.write_text(source, encoding="utf-8")
    found = [c for _, c in _wall_clock_calls(ast.parse(mutant.read_text(encoding="utf-8")))]
    assert expected in found, f"{label}: the guard did not flag {expected!r} (saw {found})"


@pytest.mark.parametrize("source", INNOCENT)
def test_the_guard_leaves_alone_what_does_not_read_the_wall_clock(source: str, tmp_path: Path) -> None:
    clean = tmp_path / "test_clean.py"
    clean.write_text(source, encoding="utf-8")
    assert _wall_clock_calls(ast.parse(clean.read_text(encoding="utf-8"))) == []


# ── The browser journey ────────────────────────────────────────────────────────────────────────────────────
# `new Date()` / `Date.now()` with no argument is the Node process's wall clock. Allowed only where it is a
# unique stamp or a duration, never a date the journey asserts.
TS_ALLOWED = {
    ("e2e/pilot-flow.spec.ts", "Date.now()"): "unique e-mail stamps for the accounts the journey creates",
    ("e2e/support/api.ts", "Date.now()"): "sign-in rate-limit pacing, in milliseconds",
}
_TS_WALL = re.compile(r"new Date\(\s*\)|Date\.now\(\s*\)")


def test_the_browser_journey_dates_everything_by_its_simulated_day() -> None:
    found: list[str] = []
    used: set[tuple[str, str]] = set()
    for path in sorted((FRONTEND / "e2e").rglob("*.ts")):
        rel = path.relative_to(FRONTEND).as_posix()
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith(("//", "*")):
                continue
            for hit in _TS_WALL.findall(line):
                key = (rel, "Date.now()" if hit.startswith("Date") else "new Date()")
                used.add(key)
                if key not in TS_ALLOWED:
                    found.append(f"{rel}:{no} {hit.strip()}")
    assert not found, "The journey reads the Node wall clock; use E2E_NOW (e2e/support/fixtures.ts):\n  " + "\n  ".join(found)
    assert set(TS_ALLOWED) - used == set(), f"stale allowances: {sorted(set(TS_ALLOWED) - used)}"


def test_the_unit_tests_run_on_the_pinned_instant_too() -> None:
    setup = (FRONTEND / "src" / "__tests__" / "setup.ts").read_text(encoding="utf-8")
    assert "TEST_INSTANT" in setup and "globalThis.Date = PinnedDate" in setup
    backend = (TESTS.parent / "app" / "core" / "clock.py").read_text(encoding="utf-8")
    instant = re.search(r'TEST_INSTANT = "([^"]+)"', setup)
    assert instant and "real_datetime(2026, 11, 25, 10, 0, 0" in backend and instant.group(1) == "2026-11-25T10:00:00Z"
