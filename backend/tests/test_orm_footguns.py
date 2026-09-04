"""Static guards for SQLAlchemy expressions that Python evaluates too early.

Each pattern below was a live 500 found by `scripts/route_sweep.py`, and none of
them is a type error, a syntax error or something ruff flags — they read as
ordinary Python and mean the wrong thing inside a query:

  not Model.col            -> calls Column.__bool__; never reaches SQL
  Model.col is None        -> identity check on a Column; always False
  Model.metadata           -> SQLAlchemy's MetaData, present on every
                              declarative class, never the column you meant

The sweep catches these by running the route. These tests catch them in CI,
before anyone has to.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# `metadata` is a legitimate attribute on plenty of non-ORM objects: pypdf
# documents, LLM responses, our own dataclasses. Only flag it where the owner is
# an obvious declarative class — a CapWord name — or a row bound from one.
_MODEL_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _python_files() -> list[Path]:
    return [
        p
        for p in APP.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _rel(path: Path) -> str:
    return str(path.relative_to(APP.parent)).replace("\\", "/")


@pytest.mark.parametrize("path", _python_files(), ids=_rel)
def test_no_python_truthiness_on_model_columns(path: Path) -> None:
    """`not Model.col` and `Model.col is None` never become SQL."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []

    for node in ast.walk(tree):
        # not Model.col
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.Not)
            and isinstance(node.operand, ast.Attribute)
            and isinstance(node.operand.value, ast.Name)
            and _MODEL_NAME.match(node.operand.value.id)
        ):
            problems.append(
                f"line {node.lineno}: `not {node.operand.value.id}."
                f"{node.operand.attr}` — use `.is_(False)` / `~` instead"
            )

        # Model.col is None / is not None
        if isinstance(node, ast.Compare) and isinstance(
            node.ops[0], (ast.Is, ast.IsNot)
        ):
            left = node.left
            if (
                isinstance(left, ast.Attribute)
                and isinstance(left.value, ast.Name)
                and _MODEL_NAME.match(left.value.id)
                and isinstance(node.comparators[0], ast.Constant)
                and node.comparators[0].value is None
            ):
                problems.append(
                    f"line {node.lineno}: `{left.value.id}.{left.attr} is "
                    f"None` — use `.is_(None)` inside a query"
                )

    assert not problems, f"{_rel(path)}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("path", _python_files(), ids=_rel)
def test_no_model_metadata_attribute_access(path: Path) -> None:
    """`Model.metadata` is SQLAlchemy's MetaData, never a column."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "metadata"):
            continue
        owner = node.value
        if isinstance(owner, ast.Name) and _MODEL_NAME.match(owner.id):
            if owner.id in {"Base", "MetaData"}:  # legitimate: Base.metadata
                continue
            problems.append(
                f"line {node.lineno}: `{owner.id}.metadata` resolves to "
                "SQLAlchemy's MetaData — did you mean `result_metadata`?"
            )

    assert not problems, f"{_rel(path)}:\n  " + "\n  ".join(problems)


# A bare liveness ping has no ORM equivalent worth writing. Every other entry
# would be a bug, so this list may shrink and never grow.
_RAW_SQL_ALLOWED = {
    ("app/api/system.py", "SELECT 1"),
}

_SQL_VERB = re.compile(r"^\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s", re.I)


def _sql_string_args(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (line, sql) for every string literal passed to `text(...)`.

    Only literals inside a `text()` call count, so a docstring that happens to
    begin "Update org settings…" is not mistaken for a statement.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "text":
            continue
        for arg in node.args:
            parts: list[str] = []
            stack: list[ast.AST] = [arg]
            while stack:
                cur = stack.pop()
                if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                    parts.append(cur.value)
                elif isinstance(cur, ast.JoinedStr):
                    stack.extend(cur.values)
                elif isinstance(cur, ast.BinOp):
                    stack.extend([cur.left, cur.right])
            if parts:
                found.append((node.lineno, " ".join(reversed(parts))))
    return found


def test_no_raw_sql_in_api_layer() -> None:
    """CLAUDE.md law 4: ORM only.

    Raw SQL also hides its tables from `create_all`, so a dev SQLite database
    never gets them. That is how every route in compliance_extended answered
    "no such table", and how ws_alerts quietly returned an empty list forever —
    until both sets of tables were given models.
    """
    offenders: list[str] = []
    for path in sorted((APP / "api").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = _rel(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, sql in _sql_string_args(tree):
            if not _SQL_VERB.match(sql):
                continue
            if any(rel == f and sql.strip().startswith(p) for f, p in _RAW_SQL_ALLOWED):
                continue
            offenders.append(f"{rel}:{lineno}: {sql.strip()[:90]}")
    assert not offenders, "raw SQL in the API layer:\n  " + "\n  ".join(offenders)


# ── Brand identity stays in configuration ─────────────────────────────────────
# The product name and domain were typed into thirteen places, including the
# KVKK/GDPR processing record, which published a contact address at a domain the
# project does not own. Renaming meant a grep. Both now resolve through
# app/core/branding.py; this keeps them there.

_BRAND_LITERALS = ("clevelai", "C-Level AI")


def test_no_hardcoded_brand_in_backend() -> None:
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "branding.py":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for lit in _BRAND_LITERALS:
                if lit in line:
                    offenders.append(f"{_rel(path)}:{i}: {line.strip()[:80]}")
    assert not offenders, (
        "brand name hard-coded — read it from app.core.branding.get_brand():\n  "
        + "\n  ".join(offenders)
    )
