"""
Plan v11 §8: architecture fitness functions that make the target checkable.

F1 (import direction) lives in test_architecture_boundaries.py. This file adds:

- F2  no module under app/ is longer than 600 lines;
- F3  only the delivery service talks SMTP (a future outbox sender will be the only one);
- F5  every module under app/ is imported by something in app/.

Each starts as a ratchet: today's violations are listed, a NEW violation fails,
and a listed entry that no longer violates fails too, so the list can only shrink.
When you fix one, delete its line.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"

MAX_LINES = 600

# F2: modules over the ceiling on 2026-11-14. Plan v11 C1, C6, C8, C9, C10 split them.
_OVERSIZED: frozenset[str] = frozenset(
    {
        "app/agents/ceo/synthesis_agent.py",
        "app/agents/orchestration/auto_chain.py",
        "app/api/ceo.py",
        "app/api/chat.py",
        "app/api/compliance_extended.py",
        "app/api/muhasebe.py",
        "app/api/org.py",
        "app/scheduler.py",
        "app/services/benchmark.py",
        "app/services/benchmark_utils.py",
        "app/services/cascade_simulator.py",
        "app/services/csv_validator.py",
        "app/services/llm_structured.py",
        "app/services/reasoning_loop.py",
        "app/services/scheduled_sync.py",
        "app/worker.py",
    }
)

# F3: the modules allowed to import an SMTP client.
_SMTP_ALLOWED: frozenset[str] = frozenset({"app.services.notification_service"})

# F5: modules nothing in app/ imports, on 2026-11-14. Some are reached only from
# scripts, tests, a string in importlib or a CLI; each is examined before it is
# deleted (plan v11 A0.2 removed the three that had no caller at all).
_UNIMPORTED: frozenset[str] = frozenset(
    {
        "app.core.crypto",
        "app.core.distributed_lock",
        "app.core.tenancy",
        "app.services.audit_trail",
        "app.services.benchmark_utils",
        "app.services.consolidation_engine",
        "app.services.data_sync.orchestrator",
        "app.services.data_sync.scheduler",
        "app.services.demo_seeder",
        "app.services.edefter_package",
        "app.services.erp.two_way_sync",
        "app.services.eval_harness",
        "app.services.field_encryption",
        "app.services.gib_edefter_ws",
        "app.services.inflation_accounting",
        "app.services.open_banking_reconciliation",
        "app.services.prescriptive_recommender",
        "app.services.regional.tax_calculator",
        "app.services.retry_harness",
        "app.services.smmm_adopt",
    }
)

# Entry points and modules loaded by the framework rather than imported.
_ENTRY_POINTS: frozenset[str] = frozenset(
    {"app", "app.main", "app.worker", "app.scheduler", "app.config", "app.database", "app.mcp.__main__"}
)
_LOADED_BY_FRAMEWORK = ("app.api.", "app.models.")


def _modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in _APP.rglob("*.py"):
        parts = path.relative_to(_BACKEND).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        found[name] = path
    return found


def _imports(name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                head = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join(head + ([base] if base else []))
            out.add(base)
            out.update(f"{base}.{alias.name}" for alias in node.names)
    return out


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _oversized() -> set[str]:
    return {
        path.relative_to(_BACKEND).as_posix()
        for path in _modules().values()
        if _line_count(path) > MAX_LINES
    }


def _smtp_importers() -> set[str]:
    return {
        name
        for name, path in _modules().items()
        if any(i == "aiosmtplib" or i.startswith("aiosmtplib.") for i in _imports(name, path))
    }


def _unimported() -> set[str]:
    modules = _modules()
    imported: set[str] = set()
    for name, path in modules.items():
        imported |= _imports(name, path)

    def reached(module: str) -> bool:
        return any(i == module or i.startswith(module + ".") for i in imported)

    return {
        name
        for name in modules
        if name not in _ENTRY_POINTS
        and not name.startswith(_LOADED_BY_FRAMEWORK)
        and modules[name].name != "__init__.py"
        and not reached(name)
    }


def test_f2_no_new_module_over_the_line_ceiling() -> None:
    new = sorted(_oversized() - _OVERSIZED)
    assert not new, (
        f"Over {MAX_LINES} lines: {new}. Split by responsibility (plan v11 F2); "
        "do not add to the list."
    )


def test_f2_list_shrinks_when_a_module_is_split() -> None:
    stale = sorted(_OVERSIZED - _oversized())
    assert not stale, f"No longer over {MAX_LINES} lines; delete from _OVERSIZED: {stale}"


def test_f3_only_the_delivery_service_talks_smtp() -> None:
    importers = _smtp_importers()
    assert importers <= _SMTP_ALLOWED, (
        f"SMTP used outside the delivery service: {sorted(importers - _SMTP_ALLOWED)}. "
        "Write the message to the delivery path instead (plan v11 C9, F3)."
    )


def test_f5_no_new_module_without_a_caller() -> None:
    new = sorted(_unimported() - _UNIMPORTED)
    assert not new, (
        f"Nothing in app/ imports {new}. Wire it in where it is used, or do not add it "
        "(plan v11 F5)."
    )


def test_f5_list_shrinks_when_a_module_gets_a_caller_or_goes() -> None:
    stale = sorted(_UNIMPORTED - _unimported())
    assert not stale, f"Now imported or deleted; remove from _UNIMPORTED: {stale}"
