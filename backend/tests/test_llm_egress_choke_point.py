"""Architecture fitness: nothing reaches a language-model or embedding API except through the two gateways.

Minimisation (`app.platform.llm_egress`: off / masked / raw, pseudonymised identifiers and known names)
is applied INSIDE `model_gateway._raw_chat` / `model_gateway.stream` and `embedding_gateway.embed_texts`.
That only protects anything if no other code can build a client, read the provider's URL, or call a
provider host. This file proves it by walking every module of `app/` (AST, not grep, so a comment or a
docstring never counts and an import inside a function does):

* the model libraries are imported only by the two gateways;
* the client classes (ChatOpenAI, OpenAIEmbeddings, AsyncOpenAI, ...) are named only there;
* the provider's base URL is read only by the modules that must know it (listed, with the reason);
* no module outside `config.py` contains a literal provider host;
* tool calling is not used anywhere (its arguments would not be masked): adding it is a decision
  to make here, not an accident;
* the gateways really open an egress session before they build a payload.

Every allow-list entry says why. The lists may only shrink: a stale entry fails.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"

# The two sanctioned places. Everything else must call model_gateway.complete / complete_text / stream
# or embedding_gateway.embed_texts.
GATEWAYS = {
    "platform/model_gateway.py": "chat and structured completions, streaming",
    "platform/embedding_gateway.py": "embeddings",
}

MODEL_LIBRARIES = (
    "langchain_openai", "openai", "anthropic", "langchain_anthropic", "langchain_google_genai", "langchain_ollama",
    "langchain_mistralai", "langchain_cohere", "langchain_groq", "litellm", "cohere", "mistralai", "ollama",
    "google.generativeai", "google.genai", "vertexai",
)
CLIENT_CLASSES = frozenset({
    "ChatOpenAI", "OpenAIEmbeddings", "AsyncOpenAI", "OpenAI", "AzureChatOpenAI", "AzureOpenAIEmbeddings",
    "ChatAnthropic", "ChatGoogleGenerativeAI", "ChatOllama", "ChatMistralAI", "ChatCohere", "ChatGroq",
})
PROVIDER_HOSTS = (
    "api.deepseek.com", "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
    "api.mistral.ai", "api.cohere", "api.groq.com", "openrouter.ai", "api.together",
)
TOOL_CALLING = frozenset({"bind_tools", "tool_calls", "with_structured_output_tools"})

# Modules that read the provider's base URL, and why. A module not here that reads it fails.
BASE_URL_READERS: dict[str, str] = {
    "core/preflight.py": "warns when `raw` is combined with a non-local provider (reads the host, sends nothing)",
    "platform/embedding_gateway.py": "the embedding gateway builds its client from it",
    "platform/model_gateway.py": "the model gateway builds its client from it",
    "platform/model_catalog.py": "reports the configured host to ops, no network call",
    "platform/llm_egress/policy.py": "shows the host to the owner and decides whether the provider is local",
}
# Modules that read the API key only to know whether a call is possible (placeholder or not), never to
# authenticate a request of their own. A module not here that reads it fails.
API_KEY_READERS: dict[str, str] = {
    "core/preflight.py": "warns about a placeholder key",
    "platform/embedding_gateway.py": "builds the embeddings client",
    "platform/model_gateway.py": "builds the chat client and refuses a placeholder",
    "services/privacy/ai_egress.py": "tells the owner whether embeddings are on (key is not a placeholder), never the key",
    "services/sentry_monitoring.py": "scrubs the key out of error events",
    "api/chat.py": "refuses a question early when the key is a placeholder",
    "api/ws_stream.py": "answers 'not configured' when the key is a placeholder",
    "services/llm_structured.py": "falls back to the deterministic path when the key is a placeholder",
    "services/negotiation/boardroom.py": "falls back to the scripted debate when the key is a placeholder",
    "agents/chro/compensation_agent.py": "chooses the template narrative when there is no key",
    "agents/chro/headcount_agent.py": "chooses the template narrative when there is no key",
    "agents/compliance/policies_agent.py": "chooses the template narrative when there is no key",
    "agents/coo/process_agent.py": "chooses the template narrative when there is no key",
    "agents/coo/sla_agent.py": "chooses the template narrative when there is no key",
}
# Literal provider hosts: only the setting's default.
HOST_LITERALS: dict[str, str] = {
    "config.py": "the default of LLM_BASE_URL (provider choice is the owner's, unchanged here)",
    "core/preflight.py": "the OpenAI default host when LLM_BASE_URL is empty, for the warning text only",
}


@functools.cache
def _modules() -> dict[str, ast.Module]:
    out: dict[str, ast.Module] = {}
    for path in _APP.rglob("*.py"):
        out[path.relative_to(_APP).as_posix()] = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    return out


def _imported(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _uses_library(tree: ast.AST) -> set[str]:
    hit: set[str] = set()
    for name in _imported(tree):
        for lib in MODEL_LIBRARIES:
            if name == lib or name.startswith(lib + "."):
                hit.add(lib)
    return hit


def _class_names(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in CLIENT_CLASSES:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in CLIENT_CLASSES:
            found.add(node.attr)
        elif isinstance(node, ast.alias) and node.name in CLIENT_CLASSES:
            found.add(node.name)
    return found


def _reads(tree: ast.AST, *names: str) -> bool:
    """`x.<name>` or a string constant exactly `<name>` (getattr(settings, "llm_base_url"))."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in names:
            return True
        if isinstance(node, ast.Constant) and node.value in names:
            return True
    return False


def _host_literals(tree: ast.AST) -> set[str]:
    return {
        host for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for host in PROVIDER_HOSTS if host in node.value.lower()
    }


def _offenders(rule, allowed: dict[str, str] | set[str]) -> dict[str, set[str]]:
    return {rel: found for rel, tree in _modules().items() if (found := rule(tree)) and rel not in allowed}


def test_model_libraries_are_imported_only_by_the_gateways() -> None:
    assert _offenders(_uses_library, GATEWAYS) == {}, "a model client library is imported outside the gateways"


def test_client_classes_are_named_only_by_the_gateways() -> None:
    assert _offenders(_class_names, GATEWAYS) == {}, "a model client class is used outside the gateways"


def test_only_listed_modules_read_the_provider_base_url() -> None:
    off = _offenders(lambda t: {"llm_base_url"} if _reads(t, "llm_base_url") else set(), BASE_URL_READERS)
    assert off == {}, f"reads LLM_BASE_URL without being on the allow-list (and so without masking): {sorted(off)}"


def test_only_listed_modules_read_the_api_key() -> None:
    off = _offenders(lambda t: {"key"} if _reads(t, "openai_api_key", "openai_key") else set(), API_KEY_READERS)
    assert off == {}, f"reads the LLM API key without being on the allow-list: {sorted(off)}"


def test_no_literal_provider_host_outside_the_setting() -> None:
    assert _offenders(_host_literals, HOST_LITERALS) == {}, "a provider host is hard-coded outside config.py"


def test_tool_calling_is_not_used_anywhere() -> None:
    def rule(tree: ast.AST) -> set[str]:
        return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in TOOL_CALLING}

    assert _offenders(rule, set()) == {}, (
        "tool calling arrived: its arguments leave unmasked unless EgressSession.mask_obj is applied; "
        "extend this test with the new site once that is done"
    )


def test_allow_lists_have_no_dead_entries() -> None:
    trees = _modules()
    for name, table, rule in (
        ("BASE_URL_READERS", BASE_URL_READERS, lambda t: _reads(t, "llm_base_url")),
        ("API_KEY_READERS", API_KEY_READERS, lambda t: _reads(t, "openai_api_key", "openai_key")),
        ("HOST_LITERALS", HOST_LITERALS, lambda t: bool(_host_literals(t))),
    ):
        dead = sorted(rel for rel in table if rel not in trees or not rule(trees[rel]))
        assert not dead, f"{name} lists modules that no longer do this: {dead}"
    assert all((_APP / rel).is_file() for rel in GATEWAYS)


def _calls(tree: ast.AST, function: str) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == function:
            return {
                (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
                for c in ast.walk(node) if isinstance(c, ast.Call)
            }
    raise AssertionError(f"{function} not found")


def test_the_gateways_open_an_egress_session_before_they_send() -> None:
    mods = _modules()
    assert "_open_egress" in _calls(mods["platform/model_gateway.py"], "_raw_chat")
    assert "_open_egress" in _calls(mods["platform/model_gateway.py"], "stream")
    assert "open_session" in _calls(mods["platform/embedding_gateway.py"], "embed_texts")
    assert "open_session" in _calls(mods["platform/model_gateway.py"], "_open_egress")
    # and the payload is masked by the session, not by the caller
    assert "outbound" in _calls(mods["platform/model_gateway.py"], "_raw_chat")
    assert "outbound_texts" in _calls(mods["platform/embedding_gateway.py"], "embed_texts")


def test_the_private_send_function_has_one_caller_outside_the_gateway() -> None:
    importers = {
        rel for rel, tree in _modules().items()
        if rel != "platform/model_gateway.py" and any(
            n.endswith("._raw_chat") for n in _imported(tree)
        )
    }
    assert importers == {"services/llm_router.py"}, "_raw_chat is the choke point; only the router may call it"


def test_the_rules_see_a_violation(tmp_path: Path) -> None:
    src = (
        "def f():\n    from langchain_openai import ChatOpenAI\n"
        "    return ChatOpenAI(base_url=settings.llm_base_url, api_key=settings.openai_api_key)\n"
        "URL = 'https://api.deepseek.com/chat'\nllm.bind_tools([])\n"
    )
    tree = ast.parse(src)
    assert _uses_library(tree) == {"langchain_openai"}
    assert _class_names(tree) == {"ChatOpenAI"}
    assert _reads(tree, "llm_base_url") and _reads(tree, "openai_api_key")
    assert _host_literals(tree) == {"api.deepseek.com"}
    assert any(isinstance(n, ast.Attribute) and n.attr == "bind_tools" for n in ast.walk(tree))
