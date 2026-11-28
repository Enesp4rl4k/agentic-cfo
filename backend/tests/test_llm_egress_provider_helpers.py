"""Architecture fitness: the provider-facing helpers of the two gateways never leave their gateway.

`test_llm_egress_choke_point.py` stops a module from building its OWN client. It did not stop a module from
borrowing the gateway's: the final review of PR #159 added

    async def _bypass(prompt, texts):
        await model_gateway._build_client(cfg, None, None).ainvoke(prompt)
        embedding_gateway._client_embed(texts)

to `agents/anomaly_agent.py`, and both architecture suites still passed. Such a call reaches the provider with the
text as written, skipping the egress session (mode, masking, fail-closed refusal, audit row).

So every symbol of a gateway that yields a client or performs a provider call is DERIVED from the gateway's own
AST (not listed by hand, so a helper added tomorrow is covered the day it is written), and:

* a private one (today `_build_client`, `_raw_chat`, `_build_embeddings`, `_client_embed`) may not appear outside
  its own gateway at all: not imported (absolute, relative, under another name), not reached as an attribute
  (through any alias of the module or the dotted path), not named in a string (getattr / importlib /
  operator.attrgetter / sys.modules), not re-exported by another module;
* a gateway module may not be reached reflectively: getattr / vars / setattr on it with a computed or private name,
  `alias._anything` (including `__dict__`), a star import, its dotted name as a string (importlib, sys.modules);
* a gateway may not export one: a public provider-facing name must be a documented entry point (those open the
  egress session first), and `__all__` may not list a private one;
* the ONE documented exception: `services/llm_router.py` imports `_raw_chat` inside `LLMTaskRouter._call_llm`
  (the router is a thin compatibility layer; `_raw_chat` opens the egress session itself).

Scanned: every module of `app/` and `scripts/` (AST: a comment or a docstring never counts). The mutations at the
bottom write a modified copy of a real module to a temporary file, parse it in place of the original, and
require a violation; the current tree must have none.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from tests.test_llm_egress_choke_point import CLIENT_CLASSES, _modules

_APP = Path(__file__).resolve().parent.parent / "app"
_SCRIPTS = _APP.parent / "scripts"

GATEWAY_MODULES: dict[str, str] = {
    "platform/model_gateway.py": "app.platform.model_gateway",
    "platform/embedding_gateway.py": "app.platform.embedding_gateway",
}
PUBLIC_ENTRY_POINTS: dict[str, frozenset[str]] = {
    "platform/model_gateway.py": frozenset({"complete", "complete_text", "complete_json", "stream"}),
    "platform/embedding_gateway.py": frozenset({"embed_texts"}),
}
# Methods that make a request on a model / embeddings client (LangChain and the OpenAI SDK).
PROVIDER_METHODS = frozenset({
    "invoke", "ainvoke", "astream", "batch", "abatch", "astream_events", "embed_documents", "aembed_documents",
    "embed_query", "aembed_query", "with_structured_output", "generate", "agenerate", "predict", "apredict",
})
# (module, symbol, enclosing function): the single sanctioned use of a private helper outside its gateway.
SANCTIONED_PRIVATE_USE = frozenset({("services/llm_router.py", "_raw_chat", "_call_llm")})
_REFLECTION = frozenset({"getattr", "setattr", "delattr", "hasattr", "vars", "attrgetter", "methodcaller"})


@functools.cache
def _all_scanned_modules() -> dict[str, ast.Module]:
    out = dict(_modules())
    for path in sorted(_SCRIPTS.rglob("*.py")) if _SCRIPTS.is_dir() else []:
        out["<scripts>/" + path.relative_to(_SCRIPTS).as_posix()] = ast.parse(
            path.read_text(encoding="utf-8", errors="replace"))
    return out


# ── derivation ───────────────────────────────────────────────────────────────

def _top_level_bodies(tree: ast.Module) -> dict[str, list[ast.AST]]:
    """name -> what defines it at module level: a function or class, or an assignment (an alias, a partial)."""
    bodies: dict[str, list[ast.AST]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bodies.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for n in ast.walk(target):
                    if isinstance(n, ast.Name):
                        bodies.setdefault(n.id, []).append(node.value)
    return bodies


def provider_facing(tree: ast.Module) -> set[str]:
    """Module-level names of a gateway that yield a provider client or make a provider call: they name a client
    class, or call a client's request method, or use another such name (transitively; aliases included)."""
    referenced: dict[str, set[str]] = {}
    found: set[str] = set()
    for name, nodes in _top_level_bodies(tree).items():
        refs: set[str] = set()
        for body in nodes:
            for n in ast.walk(body):
                if isinstance(n, ast.Name):
                    refs.add(n.id)
                    if n.id in CLIENT_CLASSES:
                        found.add(name)
                elif isinstance(n, ast.Attribute):
                    refs.add(n.attr)
                    if n.attr in CLIENT_CLASSES or n.attr in PROVIDER_METHODS:
                        found.add(name)
        referenced[name] = refs
    changed = True
    while changed:
        changed = False
        for name, refs in referenced.items():
            if name not in found and refs & found:
                found.add(name)
                changed = True
    return found


# ── the rule ─────────────────────────────────────────────────────────────────

def _resolve_from(rel: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = ["scripts"] if rel.startswith("<scripts>/") else ["app", *rel.split("/")[:-1]]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _enclosing_function(tree: ast.AST) -> dict[int, str]:
    """id(node) -> the innermost function that contains it ("" at module level)."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else fn
            owner[id(child)] = inner
            visit(child, inner)

    visit(tree, "")
    return owner


def _identifiers(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.alias):
        return [node.name.rsplit(".", 1)[-1], *([node.asname] if node.asname else [])]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.keyword) and node.arg:
        return [node.arg]
    if isinstance(node, ast.Global | ast.Nonlocal):
        return list(node.names)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value.strip()]  # the WHOLE string: a docstring that mentions a name is never equal to it
    return []


def provider_helper_violations(trees: dict[str, ast.Module]) -> list[str]:
    """Every use of a gateway's provider-facing helper outside that gateway, and every gateway that exports one."""
    issues: list[str] = []
    private: dict[str, str] = {}  # symbol -> its gateway
    for rel in GATEWAY_MODULES:
        tree = trees[rel]
        facing = provider_facing(tree)
        for name in sorted(facing):
            if name.startswith("_"):
                private[name] = rel
            elif name not in PUBLIC_ENTRY_POINTS[rel]:
                issues.append(f"{rel}: public `{name}` yields a provider client or call; only the documented entry "
                              f"points {sorted(PUBLIC_ENTRY_POINTS[rel])} may (they open the egress session)")
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                for c in ast.walk(node.value):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("_") \
                            and c.value in facing:
                        issues.append(f"{rel}: __all__ exports the private provider helper `{c.value}`")
    frozen = tuple(sorted(private.items()))
    for rel, tree in trees.items():
        issues += _module_issues(rel, tree, frozen)
    return issues


# One module's scan, cached per (module, tree object, private set): the mutation tests replace one or two trees and
# re-scan the rest unchanged. The cached value holds the tree itself, so an id reused after garbage collection is
# never mistaken for it.
_SCAN_CACHE: dict[tuple[str, int, tuple[tuple[str, str], ...]], tuple[ast.Module, list[str]]] = {}


def _module_issues(rel: str, tree: ast.Module, frozen: tuple[tuple[str, str], ...]) -> list[str]:
    key = (rel, id(tree), frozen)
    hit = _SCAN_CACHE.get(key)
    if hit is not None and hit[0] is tree:
        return hit[1]
    found = _scan_module(rel, tree, dict(frozen))
    _SCAN_CACHE[key] = (tree, found)
    return found


def _scan_module(rel: str, tree: ast.Module, private: dict[str, str]) -> list[str]:
    issues: list[str] = []
    gateway_dotted = set(GATEWAY_MODULES.values())
    gateway_leaf = {d.rsplit(".", 1)[-1] for d in gateway_dotted}
    owner = _enclosing_function(tree)
    aliases: set[str] = set()  # local names bound to a gateway module
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolve_from(rel, node)
            for a in node.names:
                if module in gateway_dotted and a.name == "*":
                    issues.append(f"{rel}:{node.lineno}: star import from {module}")
                if module == "app.platform" and a.name in gateway_leaf:
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            aliases.update(a.asname for a in node.names if a.name in gateway_dotted and a.asname)
    for node in ast.walk(tree):
        line = f"{rel}:{getattr(node, 'lineno', '?')}"
        for ident in _identifiers(node):
            home = private.get(ident)
            if home is None or home == rel or (rel, ident, owner.get(id(node), "")) in SANCTIONED_PRIVATE_USE:
                continue
            issues.append(f"{line}: `{ident}` is a provider-facing helper of {home}: call its public entry point")
        if rel in GATEWAY_MODULES:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip() in gateway_dotted:
            issues.append(f"{line}: names the gateway module {node.value!r} in a string (dynamic import, "
                          "sys.modules): import it and call an entry point")
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases
                and node.attr.startswith("_")):
            issues.append(f"{line}: private attribute `{node.value.id}.{node.attr}` of a gateway module")
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Name) \
                and node.args[0].id in aliases:
            fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if fn in _REFLECTION:
                name_arg = node.args[1] if len(node.args) > 1 else None
                fixed = isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)
                if not fixed or str(name_arg.value).startswith("_"):  # type: ignore[union-attr]
                    issues.append(f"{line}: `{fn}` on a gateway module with a computed or private name")
    return issues


# ── the current tree ─────────────────────────────────────────────────────────

def test_provider_facing_helpers_are_derived_and_include_the_known_ones() -> None:
    mods = _modules()
    mg = provider_facing(mods["platform/model_gateway.py"])
    eg = provider_facing(mods["platform/embedding_gateway.py"])
    assert {"_build_client", "_raw_chat", "complete", "complete_text", "complete_json", "stream"} <= mg, mg
    assert {"_build_embeddings", "_client_embed", "embed_texts"} <= eg, eg
    # and it does not over-reach (a false positive would make every caller of a harmless helper fail)
    assert not ({"_build_messages", "llm_config_status", "_open_egress", "_resolve_model"} & mg), mg
    assert not ({"embedding_tag", "has_embedding_support", "_has_embedding_support"} & eg), eg


def test_provider_facing_helpers_are_used_only_inside_their_gateway() -> None:
    issues = provider_helper_violations(_all_scanned_modules())
    assert issues == [], "a provider-facing helper is reachable outside its gateway:\n  " + "\n  ".join(issues)


def test_the_router_exception_is_the_single_documented_one() -> None:
    importers = [
        rel for rel, tree in _all_scanned_modules().items() for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and any(a.name == "_raw_chat" for a in node.names)
    ]
    assert importers == ["services/llm_router.py"], importers


# ── mutations: each must be caught ───────────────────────────────────────────

REVIEWER_MUTATION = '''

async def _review_bypass(prompt, texts):
    from app.platform import embedding_gateway, model_gateway
    from app.platform.model_catalog import Tier, config_for_tier

    await model_gateway._build_client(config_for_tier(Tier.CHEAP), None, None).ainvoke(prompt)
    return embedding_gateway._client_embed(texts)
'''

AGENT_MUTATIONS: dict[str, str] = {
    "reviewer's exact mutation": REVIEWER_MUTATION,
    "from-import of the private helper":
        "\nfrom app.platform.model_gateway import _build_client\n",
    "from-import under another name":
        "\nfrom app.platform.embedding_gateway import _client_embed as embed_now\n",
    "relative import (from a sibling package)":
        "\nfrom ..platform.model_gateway import _raw_chat\n",
    "module alias + attribute":
        "\nimport app.platform.model_gateway as gw\nclient = gw._build_client(None, None, None)\n",
    "dotted path attribute":
        "\nimport app.platform.embedding_gateway\nv = app.platform.embedding_gateway._build_embeddings(None)\n",
    "getattr with the name as a string":
        "\nfrom app.platform import model_gateway\nf = getattr(model_gateway, '_build_client')\n",
    "getattr with a computed name":
        "\nfrom app.platform import model_gateway as mg\nf = getattr(mg, '_build' + '_client')\n",
    "vars() of the gateway":
        "\nfrom app.platform import embedding_gateway as eg\nf = vars(eg)['_client' + '_embed']\n",
    "__dict__ of the gateway":
        "\nfrom app.platform import embedding_gateway as eg\nf = eg.__dict__['_client' + '_embed']\n",
    "importlib by module name":
        "\nimport importlib\nm = importlib.import_module('app.platform.model_gateway')\n",
    "sys.modules by module name":
        "\nimport sys\nm = sys.modules['app.platform.embedding_gateway']\n",
    "operator.attrgetter by name":
        "\nimport operator\nf = operator.attrgetter('_raw_chat')\n",
    "star import":
        "\nfrom app.platform.model_gateway import *\n",
    "router-style import outside the sanctioned function":
        "\ndef helper():\n    from app.platform.model_gateway import _raw_chat\n    return _raw_chat\n",
}


def _with(trees: dict[str, ast.Module], rel: str, source: str, tmp_path: Path) -> dict[str, ast.Module]:
    """The real tree with `rel` replaced by `source`, written to and parsed from a temporary file."""
    path = tmp_path / rel.replace("/", "__")
    path.write_text(source, encoding="utf-8")
    return {**trees, rel: ast.parse(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("label", sorted(AGENT_MUTATIONS))
def test_mutation_in_an_agent_is_caught(label: str, tmp_path: Path) -> None:
    rel = "agents/anomaly_agent.py"
    original = (_APP / rel).read_text(encoding="utf-8")
    issues = provider_helper_violations(_with(_all_scanned_modules(), rel, original + AGENT_MUTATIONS[label], tmp_path))
    assert any(issue.startswith(rel) for issue in issues), f"{label}: not caught"


def test_reviewer_mutation_is_caught_by_name(tmp_path: Path) -> None:
    rel = "agents/anomaly_agent.py"
    original = (_APP / rel).read_text(encoding="utf-8")
    issues = provider_helper_violations(_with(_all_scanned_modules(), rel, original + REVIEWER_MUTATION, tmp_path))
    joined = "\n".join(issues)
    assert "`_build_client`" in joined and "`_client_embed`" in joined, joined


def test_re_export_through_another_module_is_caught(tmp_path: Path) -> None:
    trees = _all_scanned_modules()
    helper = "services/llm_structured.py"
    src = (_APP / helper).read_text(encoding="utf-8") + "\nfrom app.platform.model_gateway import _build_client  # noqa\n"
    user = (_APP / "agents/anomaly_agent.py").read_text(encoding="utf-8") + (
        "\nfrom app.services.llm_structured import _build_client as make\n")
    issues = provider_helper_violations(_with(_with(trees, helper, src, tmp_path), "agents/anomaly_agent.py", user, tmp_path))
    assert any(i.startswith(helper) for i in issues) and any(i.startswith("agents/anomaly_agent.py") for i in issues)


GATEWAY_MUTATIONS: dict[str, tuple[str, str]] = {
    "a new public accessor for the client": (
        "platform/model_gateway.py", "\ndef get_client(cfg):\n    return _build_client(cfg, None, None)\n"),
    "a public alias of a private helper": (
        "platform/embedding_gateway.py", "\nembed_now = _client_embed\n"),
    "a new public function that builds a client itself": (
        "platform/embedding_gateway.py",
        "\ndef raw_embeddings():\n    from langchain_openai import OpenAIEmbeddings\n    return OpenAIEmbeddings()\n"),
    "__all__ exporting a private helper": (
        "platform/model_gateway.py", "\n__all__ = ['complete', '_raw_chat']\n"),
}


@pytest.mark.parametrize("label", sorted(GATEWAY_MUTATIONS))
def test_mutation_in_a_gateway_is_caught(label: str, tmp_path: Path) -> None:
    rel, extra = GATEWAY_MUTATIONS[label]
    original = (_APP / rel).read_text(encoding="utf-8")
    issues = provider_helper_violations(_with(_all_scanned_modules(), rel, original + extra, tmp_path))
    assert any(issue.startswith(rel) for issue in issues), f"{label}: not caught"


def test_a_new_private_helper_is_covered_the_day_it_is_written(tmp_path: Path) -> None:
    """Not on any list: derived because it calls a client's request method, then caught in an agent."""
    gw = "platform/model_gateway.py"
    src = (_APP / gw).read_text(encoding="utf-8") + (
        "\nasync def _send_plain(cfg, text):\n    return await _build_client(cfg, None, None).ainvoke(text)\n")
    trees = _with(_all_scanned_modules(), gw, src, tmp_path)
    assert "_send_plain" in provider_facing(trees[gw])
    agent = "agents/anomaly_agent.py"
    user = (_APP / agent).read_text(encoding="utf-8") + (
        "\nasync def f(cfg, t):\n    from app.platform import model_gateway\n    return await model_gateway._send_plain(cfg, t)\n")
    issues = provider_helper_violations(_with(trees, agent, user, tmp_path))
    assert any("`_send_plain`" in i for i in issues), issues
