"""No fabricated company data in non-test, non-demo backend modules.

The system never shows or sends a figure, a company name or a status that is not the organisation's
own: missing data is shown as missing. This guard fails on a NEW

* hard-coded currency amount inside a string (`₺45,000`, `1.500 TL`, `$20`),
* sample company or person name (`Acme`, `TechNova`, `Örnek A.Ş.` ...),
* constant "healthy" status: a dict value, for a status-like key, that is the literal `healthy`,
  `Stabil`, `implemented`, ... (a computed or conditional status is not constant),
* `random` / `faker` import (a stochastic model seeded from real inputs is the only legitimate use).

Docstrings and comments are not scanned. Demo modules (the labelled sample company) and
`app/services/eval_harness.py` (test cases for the evaluator) are exempt by path. Like the other fitness
tests it is a ratchet: a stale allowlist entry fails, so the list can only shrink.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"

EXEMPT = {
    "app/api/demo.py", "app/services/demo_seeder.py", "app/services/demo_template.py",
    "app/services/eval_harness.py",
}

_AMOUNT = re.compile(r"[₺$€£]\s?\d|\d[\d.,]*\s?(?:₺|TL\b|TRY\b|USD\b|EUR\b)")
_NAME = re.compile(r"\bAcme\b|\bTechNova\b|Örnek (?:A\.Ş|Şirket|Ltd)|\bFoo\s?(?:Inc|Ltd|Corp)|Tedarikçi Yazılım|John Doe|Jane Doe")
_STATUS_KEYS = {"status", "health", "health_status", "state", "financial_health", "durum", "saglik"}
_CONSTANT_OK = {"healthy", "stabil", "stabil ✅", "stable", "implemented", "secure", "all good", "passed"}
_RANDOM = {"random", "faker"}

# Each entry: path -> {rule: reason}. Rules: "amount", "name", "status", "random".
ALLOWED: dict[str, dict[str, str]] = {
    "app/services/monte_carlo.py": {"random": "Monte Carlo draws from the caller's real inputs and volatility"},
    "app/agents/orchestration/anomaly_ml_service.py": {"random": "seeded bootstrap of real anomaly scores"},
    "app/agents/compliance/turkey_regulations.py": {"amount": "statutory fine ranges quoted from Turkish law, not company data"},
    "app/agents/risk/turkey_macro_risks.py": {"amount": "statutory fine range in a macro-risk catalogue entry"},
    "app/platform/authority_matrix.py": {"amount": "label of a lira approval-limit policy threshold, set by policy"},
    "app/config.py": {"name": "demo_company_name default; used only when demo mode is switched on by the environment"},
    "app/services/agent_memory.py": {"amount": "false positive: SQL text with a column list, no amount"},
    "app/services/ocr_service.py": {"amount": "regex replacement that normalises 'TL' in scanned text"},
}


def _docstrings(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _scan(path: Path) -> dict[str, list[tuple[int, str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    docs = _docstrings(tree)
    hits: dict[str, list[tuple[int, str]]] = {}

    def add(rule: str, node: ast.AST, text: str) -> None:
        hits.setdefault(rule, []).append((getattr(node, "lineno", 0), text.strip()[:60]))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            if _AMOUNT.search(node.value):
                add("amount", node, node.value)
            if _NAME.search(node.value):
                add("name", node, node.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in _STATUS_KEYS
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)
                    and value.value.lower() in _CONSTANT_OK
                ):
                    add("status", value, f"{key.value}: {value.value}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _RANDOM:
                    add("random", node, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in _RANDOM:
            add("random", node, node.module)
    return hits


def _found() -> dict[str, dict[str, list[tuple[int, str]]]]:
    out: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for path in sorted(_APP.rglob("*.py")):
        rel = path.relative_to(_BACKEND).as_posix()
        if rel in EXEMPT:
            continue
        hits = _scan(path)
        if hits:
            out[rel] = hits
    return out


def test_no_new_fabricated_amount_name_or_constant_status() -> None:
    new = {
        rel: {rule: h[:3] for rule, h in rules.items() if rule not in ALLOWED.get(rel, {})}
        for rel, rules in _found().items()
    }
    new = {rel: rules for rel, rules in new.items() if rules}
    assert not new, (
        "Fabricated company data in production code: a figure, a sample company name, a constant 'healthy' "
        "status or a random draw. Return the organisation's real value, or show it as missing "
        f"('bilinmiyor' / None). Or allowlist with a reason: {new}"
    )


def test_allowlist_has_no_stale_entries_and_every_entry_a_reason() -> None:
    found = _found()
    stale = sorted(
        f"{rel}:{rule}" for rel, rules in ALLOWED.items() for rule in rules if rule not in found.get(rel, {})
    )
    assert not stale, f"Nothing left to allow; delete from ALLOWED: {stale}"
    assert all(len(reason.split()) >= 4 for rules in ALLOWED.values() for reason in rules.values())
    assert sum(len(r) for r in ALLOWED.values()) <= 15


def test_the_guard_catches_what_the_bot_gateway_used_to_say(tmp_path: Path) -> None:
    sample = tmp_path / "bad.py"
    sample.write_text(
        'import random\n'
        'CARD = "Tedarikçi Yazılım A.Ş. (₺45,000.00)"\n'
        'REPLY = {"status": "healthy", "health": "Stabil"}\n',
        encoding="utf-8",
    )
    assert set(_scan(sample)) == {"amount", "name", "status", "random"}
