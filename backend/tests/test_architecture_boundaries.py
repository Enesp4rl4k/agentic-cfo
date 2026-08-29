"""
Architectural guard: import direction between backend layers.

Layer order (may import downward only):

    api  →  agents  →  services  →  platform  →  models / database / config / core

A lower layer importing a higher one is an inversion that turns the codebase
back into a ball of mud. This test parses every module's imports and fails on
any upward edge.

Known, deliberate exceptions are listed per-rule; shrink them, never grow them.
"""
from __future__ import annotations

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"

# module-prefix → layers it must NOT import from
_FORBIDDEN: dict[str, set[str]] = {
    "app.models": {"app.api", "app.agents", "app.services", "app.platform", "app.connectors"},
    "app.platform": {"app.api", "app.agents", "app.services", "app.connectors"},
    "app.services": {"app.api", "app.agents"},
    # Connectors are I/O adapters: may use services/platform/models/core, never api/agents.
    "app.connectors": {"app.api", "app.agents"},
}

# (importer_prefix, forbidden_prefix) pairs tolerated as a *rule-level* carve-out.
_RULE_EXCEPTIONS: set[tuple[str, str]] = {
    # Observability is cross-cutting; the gateway emits spans through it.
    ("app.platform.model_gateway", "app.services"),
}

# Frozen inventory of pre-existing upward edges (Phase 4 debt). SHRINK ONLY:
# relayer the module (into app/agents/orchestration or wherever it belongs) and
# delete its line. The test fails if a NEW edge appears or if a listed edge
# disappears (then remove it here).
#
# Fully paid down. thp_classifier → app/services/accounting/; cross_domain_hub,
# proactive_alerts, anomaly_ml_service, risk_cascade_bridge, erp_sync_runner and
# auto_chain → app/agents/orchestration/; context_persist now receives the
# auto-chain trigger as a hook from its api-layer callers.
#
# Keep this EMPTY. If a new upward edge is genuinely unavoidable, add it here
# with a comment and a plan to remove it — never as a permanent home.
_KNOWN_UPWARD_EDGES: frozenset[str] = frozenset()


def _module_name(path: Path) -> str:
    rel = path.relative_to(_APP.parent).with_suffix("")
    return ".".join(rel.parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _violations() -> list[str]:
    out: list[str] = []
    for path in _APP.rglob("*.py"):
        mod = _module_name(path)
        rules = [(pfx, bad) for pfx, bad in _FORBIDDEN.items() if mod.startswith(pfx)]
        if not rules:
            continue
        imports = _imports(path)
        for _pfx, forbidden in rules:
            for imp in imports:
                for bad in forbidden:
                    if imp == bad or imp.startswith(bad + "."):
                        if any(
                            mod.startswith(e_imp) and imp.startswith(e_bad)
                            for e_imp, e_bad in _RULE_EXCEPTIONS
                        ):
                            continue
                        out.append(f"{mod}  →  {imp}")
    return sorted(set(out))


def test_no_new_upward_layer_imports() -> None:
    new = set(_violations()) - _KNOWN_UPWARD_EDGES
    assert not new, (
        "New upward layer imports (a lower layer importing a higher one):\n  "
        + "\n  ".join(sorted(new))
        + "\n\nMove the shared piece down a layer, or invert the dependency."
    )


def test_known_upward_edges_list_shrinks_only() -> None:
    fixed = _KNOWN_UPWARD_EDGES - set(_violations())
    assert not fixed, (
        "These upward edges are gone — delete them from _KNOWN_UPWARD_EDGES:\n  "
        + "\n  ".join(sorted(fixed))
    )
