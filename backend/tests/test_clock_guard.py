"""No test reads the wall clock behind the pinned one's back (app/core/clock.py, tests/conftest.py section 1b).

Four master-red incidents in a week came from tests whose outcome depended on the day they ran. In a test,
`datetime.now()` / `date.today()` read the pinned clock and are safe; what is NOT pinned is `time.time()`,
`time.strftime()` / `localtime()` / `gmtime()` / `ctime()` without an explicit time, and the clock's own escape
hatches. A test that uses one must either be marked `@pytest.mark.real_clock(reason=...)` or be listed below
with the reason it cannot flip at a date boundary. The browser journey (Playwright) must take "today" from the
journey's simulated date (`e2e/support/fixtures.ts` `E2E_NOW`), never from `new Date()` / `Date.now()`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"

# `time.<name>(...)` with no argument reads the wall clock (`strftime` with only a format, too).
_WALL = {"time", "localtime", "gmtime", "ctime", "strftime"}
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


def _wall_clock_calls(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []

    def visit(node: ast.AST, exempt: bool) -> None:
        exempt = exempt or _marked_real_clock(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not exempt:
            owner = ast.unparse(node.func.value)
            name = node.func.attr
            if owner == "time" and name in _WALL and (len(node.args) == 0 or (name == "strftime" and len(node.args) == 1)):
                out.append((node.lineno, f"time.{name}"))
        if isinstance(node, ast.Attribute) and node.attr in _ESCAPES and not exempt:
            out.append((node.lineno, f"{ast.unparse(node.value)}.{node.attr}"))
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
