"""Find every place in `app/` that sends something to the gateway, by AST (a docstring or comment never counts).

A "site" is `<module path relative to app/>::<enclosing function qualified name>`, never a line number, so the
inventory survives edits and merges. The matrix test requires a driver for each site found here, so a new call
site cannot be added without a canary proof.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Names that send: the gateway's public entry points, the router, the structured-output helpers, the embedding path.
SENDERS = frozenset({
    "complete_text", "complete", "complete_json", "stream", "_gw_stream", "_raw_chat", "embed_texts", "_embed_texts",
    "structured_llm", "get_llm_router",
})
# Modules that ARE the choke point (they implement the senders): not call sites.
IMPLEMENTATION = frozenset({
    "platform/model_gateway.py", "platform/embedding_gateway.py", "platform/model_catalog.py",
})


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.found: set[str] = set()

    def _scope(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name in SENDERS and self.stack:
            self.found.add(".".join(self.stack))
        self.generic_visit(node)


def _imports_gateway(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            ("app.platform.model_gateway", "app.platform.embedding_gateway", "app.services.llm_router",
             "app.services.llm_structured", "app.services.rag_service")
        ):
            return True
    return False


def discover() -> dict[str, str]:
    """site id -> the function name, for every function that calls a sender in a module that imports the gateway."""
    sites: dict[str, str] = {}
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel in IMPLEMENTATION:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        if not _imports_gateway(tree):
            continue
        visitor = _Visitor()
        visitor.visit(tree)
        for qual in sorted(visitor.found):
            sites[f"{rel}::{qual}"] = qual
    return sites


if __name__ == "__main__":
    for site in discover():
        print(site)
