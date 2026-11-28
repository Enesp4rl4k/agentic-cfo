"""Every call to the model API binds to the function it calls: no keyword the callee does not take.

`ReasoningLoop` passed `max_tokens=` to `LLMTaskRouter.complete`, which has no such parameter. Each call raised
TypeError at run time, the loop's fallback swallowed it, and the model was never reached: a mismatch no test saw
because the fallback looked like "LLM unavailable". This test binds every statically resolvable call of the Model
Gateway's and the Embedding Gateway's public API, and of the router's `complete`, against the real signature.

Resolved: `model_gateway.complete(...)` through any alias of the module, names imported from it
(`from app.platform.model_gateway import complete_text as ct`), and `get_llm_router().complete(...)`.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

_APP = Path(__file__).resolve().parent.parent / "app"

API = {
    "app.platform.model_gateway": ("complete", "complete_text", "complete_json", "stream"),
    "app.platform.embedding_gateway": ("embed_texts",),
}


def _targets() -> dict[tuple[str, str], Any]:
    import importlib

    out: dict[tuple[str, str], Any] = {}
    for module, names in API.items():
        mod = importlib.import_module(module)
        for name in names:
            out[(module, name)] = inspect.signature(inspect.unwrap(getattr(mod, name)))
    from app.services.llm_router import LLMTaskRouter

    out[("app.services.llm_router", "LLMTaskRouter.complete")] = inspect.signature(LLMTaskRouter.complete)
    return out


def _calls(tree: ast.Module) -> list[tuple[ast.Call, tuple[str, str]]]:
    module_alias: dict[str, str] = {}
    name_alias: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for a in node.names:
                dotted = f"{node.module}.{a.name}"
                if dotted in API:
                    module_alias[a.asname or a.name] = dotted
                elif node.module in API and a.name in API[node.module]:
                    name_alias[a.asname or a.name] = (node.module, a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name in API and a.asname:
                    module_alias[a.asname] = a.name
    found: list[tuple[ast.Call, tuple[str, str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in name_alias:
            found.append((node, name_alias[fn.id]))
        elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in module_alias:
            module = module_alias[fn.value.id]
            if fn.attr in API[module]:
                found.append((node, (module, fn.attr)))
        elif (isinstance(fn, ast.Attribute) and fn.attr == "complete" and isinstance(fn.value, ast.Call)
              and getattr(fn.value.func, "id", getattr(fn.value.func, "attr", "")) == "get_llm_router"):
            found.append((node, ("app.services.llm_router", "LLMTaskRouter.complete")))
    return found


def _mismatch(call: ast.Call, sig: inspect.Signature, method: bool) -> str | None:
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return None  # *args / **kwargs: not statically checkable
    args = (["self"] if method else []) + [None] * len(call.args)
    try:
        sig.bind_partial(*args, **{k.arg: None for k in call.keywords if k.arg})
    except TypeError as exc:
        return str(exc)
    return None


def test_every_model_api_call_binds_to_its_signature() -> None:
    sigs = _targets()
    bad: list[str] = []
    seen = 0
    for path in sorted(_APP.rglob("*.py")):
        rel = path.relative_to(_APP).as_posix()
        for call, target in _calls(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
            seen += 1
            problem = _mismatch(call, sigs[target], method=target[1].startswith("LLMTaskRouter."))
            if problem:
                bad.append(f"{rel}:{call.lineno} {target[1]}: {problem}")
    assert seen >= 30, f"only {seen} calls resolved: the resolver broke"
    assert bad == [], "calls that raise TypeError at run time:\n  " + "\n  ".join(bad)


def test_the_resolver_sees_the_original_bug() -> None:
    src = (
        "from app.services.llm_router import get_llm_router\n"
        "async def f(prompt):\n"
        "    return await get_llm_router().complete(task='think', prompt=prompt, max_tokens=400)\n"
        "from app.platform import model_gateway as mg\n"
        "async def g(p):\n"
        "    return await mg.complete_text(task='x', prompt=p, max_token=5)\n"
    )
    sigs = _targets()
    problems = [_mismatch(c, sigs[t], method=t[1].startswith("LLMTaskRouter.")) for c, t in _calls(ast.parse(src))]
    assert len(problems) == 2 and all(problems), problems
