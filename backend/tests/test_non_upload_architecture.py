"""A source of money rows that does not go through the counting layer fails CI.

PR #116 made the upload pipeline safe (`services/ingest/door.py` is the only caller of a parser's `parse`).
The rows that are fetched rather than uploaded (a bank's API, an ERP, a shop, a scheduled sync) used to bypass
it: a missing type code was an expense, a missing amount was 0, "1.500" was 150 cents, an outage was an empty
list. `app.services.ingest.feed` is their layer. This file keeps it the only way in:

  1. every module that fetches money over the network goes through `feed` (or is listed here with the reason
     it is not a source of money rows, or counts its rows one layer down);
  2. the places that WRITE rows into the books or hand rows to the ingest pipeline are listed, and the ones
     that take pulled rows import the layer;
  3. no source module defaults an amount, a direction or a currency (`or "expense"`, `or 0`, `or "TRY"`);
  4. there is one amount parser: no second `_to_cents` or `*parse_amount*` in a source module.

Like the other fitness tests the exemption lists are ratchets: an entry that no longer applies fails.
"""
from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"
_FEED = "app.services.ingest.feed"

_NETWORK = {"httpx", "stripe", "requests", "aiohttp"}
_MONEY_WORDS = ("amount", "total_price", "payable", "tutar", "gross", "salary", "balance")

# 1. Network modules that mention money and are NOT a direct source of money rows, with why.
_NOT_A_SOURCE: dict[str, str] = {
    "app/mcp/server.py": "the MCP server calls this API on behalf of an agent; it fetches nothing into the books",
    "app/services/benchmark.py": "peer benchmark figures (metrics of other companies), not this company's money rows",
    "app/services/connectors/crm_export.py": "emits a CSV that scheduled_sync reads through data_plane.normalization_service (counted there)",
    "app/services/connectors/hr_export.py": "emits a CSV that scheduled_sync reads through data_plane.normalization_service (counted there)",
}

# 2. Who may write to the books / hand rows to the ingest pipeline, and why that is safe.
_WRITES_TRANSACTIONS = {
    "app/models/": "the model definitions",
    "app/services/ingest/persist.py": "the one place the upload pipeline builds a Transaction (after the hold step)",
    "app/services/held_rows.py": "stores rows the hold step held; released by a person",
    "app/services/ledger_correction.py": "a person's correction of a ledger row, with its decision record",
    "app/services/scheduled_sync.py": "canonical rows of a scheduled pull: only rows normalization_service accepted",
    "app/services/ledger.py": "maps the ingest pipeline's accepted Transaction rows to canonical rows; nothing pulled enters here",
}
# Modules that call `islemleri_ekle` (rows for the ingest pipeline) and where their rows come from. Each must import the
# feed layer itself, or name the module whose rows they are (which must import the door).
_FEEDS_PIPELINE_VIA: dict[str, str] = {
    "app/api/erp_integrations.py": "app.services.erp.logo_tiger_connector",   # rows from door.connector_rows
}

# 3. Defaults that put a guessed value where the source stated none. Functions where a constant 0 / "income" is not money.
_DEFAULTED = {"expense", "income", 0, "0", "TRY", "USD", "EUR", "TRL"}
_NOT_MONEY = {
    ("app/services/scheduled_sync.py", "_run_github_overlay"): "counts commits, not money",
}
_SOURCE_PREFIXES = (
    "app/services/open_banking/", "app/services/erp/", "app/services/data_plane/", "app/services/connectors/",
    "app/services/ingest/feed.py",
)
_SOURCE_FILES = ("app/services/integrations.py", "app/services/gib_efatura.py", "app/services/scheduled_sync.py")


def _rel(path: Path) -> str:
    return path.relative_to(_BACKEND).as_posix()


def _modules() -> list[Path]:
    return sorted(_APP.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))


def _imported(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


_NOT_MONEY_FILES = {"app/services/connectors/github_activity.py": "commit and pull-request counts, not money"}


def _is_source(rel: str) -> bool:
    return (rel.startswith(_SOURCE_PREFIXES) or rel in _SOURCE_FILES) and rel not in _NOT_MONEY_FILES


# ── 1. network fetchers of money go through the feed ────────────────────────────────────────────────────────

def _fetches_money(path: Path) -> bool:
    tree = _tree(path)
    roots = {i.split(".")[0] for i in _imported(tree)}
    if not roots & _NETWORK:
        return False
    texts = [n.value.lower() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return any(word in text for text in texts for word in _MONEY_WORDS)


def test_every_module_that_fetches_money_goes_through_the_feed_layer() -> None:
    missing = []
    for path in _modules():
        rel = _rel(path)
        if _fetches_money(path) and _FEED not in _imported(_tree(path)) and rel not in _NOT_A_SOURCE:
            missing.append(rel)
    assert not missing, (
        "These modules fetch over the network and mention money, but do not use app.services.ingest.feed "
        "(count every item, hold what the source did not state, report failed/partial). Use Feed, or list the "
        f"module in _NOT_A_SOURCE with the reason: {missing}"
    )


def test_the_not_a_source_list_only_names_modules_that_still_need_it() -> None:
    stale = [rel for rel in _NOT_A_SOURCE if not (_BACKEND / rel).exists() or not _fetches_money(_BACKEND / rel)
             or _FEED in _imported(_tree(_BACKEND / rel))]
    assert not stale, f"delete from _NOT_A_SOURCE: {stale}"


# ── 2. who writes rows ──────────────────────────────────────────────────────────────────────────────────────

def _constructs(tree: ast.Module, names: set[str]) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in names:
                return True
            if isinstance(func, ast.Name) and func.id in {"pg_insert", "sqlite_insert", "insert"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id in names:
                    return True
    return False


def test_only_the_listed_modules_write_transactions_and_the_scheduled_sync_goes_through_the_feed() -> None:
    names = {"Transaction", "CanonicalTransaction", "HeldTransaction"}
    writers = []
    for path in _modules():
        rel = _rel(path)
        if _constructs(_tree(path), names) and not rel.startswith(tuple(_WRITES_TRANSACTIONS)):
            writers.append(rel)
    assert not writers, (
        "A module writes Transaction / CanonicalTransaction / HeldTransaction rows without being listed in "
        f"_WRITES_TRANSACTIONS (and so without the counting layer): {writers}"
    )
    sync = _imported(_tree(_APP / "services" / "scheduled_sync.py"))
    assert "app.services.data_plane.normalization_service" in sync, "scheduled sync must normalise through the layer"
    norm = _imported(_tree(_APP / "services" / "data_plane" / "normalization_service.py"))
    assert _FEED in norm


def test_rows_handed_to_the_ingest_pipeline_come_from_the_feed_layer_or_the_door() -> None:
    bad = []
    for path in _modules():
        rel = _rel(path)
        tree = _tree(path)
        calls = {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        if "islemleri_ekle" not in calls or rel == "app/services/ingest/ekle.py":
            continue
        imports = _imported(tree)
        if _FEED in imports or "app.services.ingest.door" in imports:
            continue
        via = _FEEDS_PIPELINE_VIA.get(rel)
        if via is None or "app.services.ingest.door" not in _imported(_tree(_APP.parent / (via.replace(".", "/") + ".py"))):
            bad.append(rel)
    assert not bad, f"these callers of islemleri_ekle do not take their rows from the feed layer or the door: {bad}"


# ── 3. no defaults on money ─────────────────────────────────────────────────────────────────────────────────

def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    owner: dict[int, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                owner[id(child)] = fn.name
    return owner


def _defaults(path: Path, rel: str | None = None) -> list[tuple[int, str]]:
    tree = _tree(path)
    owner = _enclosing_functions(tree)
    rel = rel or _rel(path)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for operand in node.values[1:]:
                if isinstance(operand, ast.Constant) and operand.value in _DEFAULTED and not isinstance(operand.value, bool) \
                        and (rel, owner.get(id(node), "")) not in _NOT_MONEY:
                    hits.append((node.lineno, f"... or {operand.value!r}"))
    return hits


def test_no_source_module_fills_in_an_amount_a_direction_or_a_currency() -> None:
    found = {}
    for path in _modules():
        if _is_source(_rel(path)) and (hits := _defaults(path)):
            found[_rel(path)] = hits
    assert not found, (
        "A source module defaults a money value (`or \"expense\"`, `or 0`, `or \"TRY\"`): a value the source did not "
        f"state is None and the row is held, never a default: {found}"
    )


def test_the_default_guard_finds_what_it_is_meant_to_find(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text('x = tx.get("TransactionType") or "expense"\ny = float(a.get("Amount") or 0)\nz = a or ""\n')
    assert [h[1] for h in _defaults(probe, "probe.py")] == ["... or 'expense'", "... or 0"]


# ── 4. one amount parser ────────────────────────────────────────────────────────────────────────────────────

def test_there_is_one_amount_parser_for_pulled_money() -> None:
    clones = []
    for path in _modules():
        rel = _rel(path)
        if not _is_source(rel):
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                word in node.name.lower() for word in ("to_cents", "parse_amount", "parse_money", "to_kurus")
            ):
                clones.append(f"{rel}:{node.name}")
    assert not clones, f"a second amount parser: use app.services.ingest.feed.read_money (parsers.direction.parse_money): {clones}"
    assert not any(
        isinstance(n, ast.FunctionDef) and n.name == "_to_cents" for p in _modules() for n in ast.walk(_tree(p))
    )


# ── 5. no file-level direction heuristic ────────────────────────────────────────────────────────────────────

def test_no_source_module_infers_a_direction_from_the_sign_mix_of_a_file() -> None:
    """"The file has a negative amount, so it is signed" turned a payroll's salaries into income. Only a row's own
    field or a source's declared contract (`feed.SOURCE_DIRECTION`) is evidence. (The upload path's
    `direction.sign_is_informative` is a reviewed rule of its own: both signs, the rarer at 3 or 15%.)"""
    offenders = []
    for path in _modules():
        rel = _rel(path)
        if not _is_source(rel):
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"any", "all"}:
                text = ast.unparse(node)
                if "negative" in text or "< 0" in text:
                    offenders.append(f"{rel}:{node.lineno}")
            if isinstance(node, ast.Name) and node.id in {"signed_file", "file_is_signed"}:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"a file-level sign heuristic: {offenders}"
