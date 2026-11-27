"""The HTTP request bodies the gateway and the embeddings client put on the wire, for a DeepSeek-style base URL.

langchain-openai 1.x changed defaults (structured output became `response_format=json_schema`; `max_tokens` became
`max_completion_tokens`; embeddings send token-id arrays plus `dimensions`). A DeepSeek-compatible endpoint may reject
or silently ignore each. These tests inject an httpx MockTransport under the real OpenAI SDK client and assert the
JSON that would be sent. No network. Behaviour against a real provider is NOT proven by this file.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import langchain_openai
import openai
import pytest
from pydantic import BaseModel

from app.config import get_settings
from app.platform import embedding_gateway
from app.platform import model_gateway as mg

BASE = "https://api.deepseek.com"
MAX_TOKENS = 777


class _Out(BaseModel):
    answer: str


def _completion(message: dict[str, Any], finish: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "deepseek-chat",
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _sse(*chunks: dict[str, Any]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Real settings for a DeepSeek-style provider; the SDK clients of every ChatOpenAI built by the gateway talk
    to a MockTransport. Yields the list the transport records requests into."""
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(s, "llm_base_url", BASE)
    monkeypatch.setattr(s, "llm_model", "deepseek-chat")
    monkeypatch.setattr(s, "llm_model_cheap", None)
    monkeypatch.setattr(s, "llm_model_strong", None)
    monkeypatch.setattr(s, "llm_model_prices", {})
    monkeypatch.setattr(s, "llm_max_tokens", MAX_TOKENS)
    # the wire shape, not data minimisation: `raw` needs no company context (masked mode fails closed without one;
    # the masked payloads are proven by tests/test_llm_egress_matrix.py)
    monkeypatch.setattr(s, "llm_data_mode", "raw")
    monkeypatch.setattr(mg, "_persist_call_log", lambda **_: None)

    async def _spend(_org: Any) -> float:
        return 0.0

    monkeypatch.setattr(mg, "_org_month_spend_usd", _spend)
    mg.reset_ledger()

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if body.get("stream"):
            chunk = {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "m",
                     "choices": [{"index": 0, "delta": {"content": "merhaba"}, "finish_reason": None}]}
            return httpx.Response(200, content=_sse(chunk), headers={"content-type": "text/event-stream"})
        if body.get("tools"):
            call = {"id": "call_1", "type": "function",
                    "function": {"name": body["tools"][0]["function"]["name"], "arguments": '{"answer": "evet"}'}}
            return httpx.Response(200, json=_completion({"role": "assistant", "content": None, "tool_calls": [call]},
                                                        "tool_calls"))
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "tamam"}))

    original = mg._build_client

    def build(*args: Any, **kwargs: Any) -> Any:
        llm = original(*args, **kwargs)
        sync_http = httpx.Client(transport=httpx.MockTransport(handler))
        async_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        params = {"api_key": "sk-test-not-real", "base_url": BASE}
        llm.client = openai.OpenAI(http_client=sync_http, **params).chat.completions
        llm.async_client = openai.AsyncOpenAI(http_client=async_http, **params).chat.completions
        return llm

    monkeypatch.setattr(mg, "_build_client", build)
    yield seen
    mg.reset_ledger()


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def _assert_deepseek_shape(request: httpx.Request) -> dict[str, Any]:
    body = _body(request)
    assert str(request.url) == f"{BASE}/chat/completions"
    assert body["model"] == "deepseek-chat"
    assert body["max_tokens"] == MAX_TOKENS
    assert "max_completion_tokens" not in body
    assert "response_format" not in body
    assert body["messages"][-1] == {"role": "user", "content": "merhaba"}
    return body


async def test_plain_chat_request_body(wire: list[httpx.Request]) -> None:
    res = await mg.complete(task="deep_analysis", prompt="merhaba")
    assert res.text == "tamam"
    body = _assert_deepseek_shape(wire[-1])
    assert "tools" not in body and "tool_choice" not in body
    assert not body.get("stream")


async def test_structured_chat_request_body_is_a_forced_tool_call(wire: list[httpx.Request]) -> None:
    res = await mg.complete(task="deep_analysis", prompt="merhaba", schema=_Out)
    assert res.parsed == _Out(answer="evet")
    body = _assert_deepseek_shape(wire[-1])
    assert [t["function"]["name"] for t in body["tools"]] == ["_Out"]
    assert body["tool_choice"] == {"type": "function", "function": {"name": "_Out"}}


async def test_streaming_chat_request_body(wire: list[httpx.Request]) -> None:
    pieces = [p async for p in mg.stream(task="deep_analysis", prompt="merhaba")]
    assert pieces == ["merhaba"]
    body = _assert_deepseek_shape(wire[-1])
    assert body["stream"] is True
    assert "tools" not in body


def test_embeddings_send_strings_without_dimensions_to_a_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(s, "llm_base_url", BASE)
    monkeypatch.setattr(s, "rag_embedding_model", "embed-model")
    monkeypatch.setattr(s, "rag_embedding_dimensions", 1536)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        inputs = _body(request)["input"]
        data = [{"object": "embedding", "index": i, "embedding": [0.1, 0.2]} for i, _ in enumerate(inputs)]
        return httpx.Response(200, json={"object": "list", "data": data, "model": "embed-model",
                                         "usage": {"prompt_tokens": 1, "total_tokens": 1}})

    client = embedding_gateway._build_embeddings(s)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client.client = openai.OpenAI(api_key="sk-test-not-real", base_url=BASE, http_client=http).embeddings
    assert client.embed_documents(["alacak raporu", "borc raporu"]) == [[0.1, 0.2], [0.1, 0.2]]

    body = _body(seen[-1])
    assert str(seen[-1].url) == f"{BASE}/embeddings"
    assert body["input"] == ["alacak raporu", "borc raporu"]  # strings, not token-id arrays

    # ... and the same request through the gateway's own entry point (raw mode: no company context needed here)
    import asyncio

    monkeypatch.setattr(s, "llm_data_mode", "raw")
    monkeypatch.setattr(s, "rag_embedding_enabled", True)
    monkeypatch.setattr(embedding_gateway.audit, "persist_call_log", lambda **_: None)
    monkeypatch.setattr(embedding_gateway, "_build_embeddings", lambda _s: client)
    out = asyncio.run(embedding_gateway.embed_texts(["kira gideri"], org_id=None))
    assert out is not None and out.vectors == [[0.1, 0.2]] and _body(seen[-1])["input"] == ["kira gideri"]
    body = _body(seen[-2])
    assert body["model"] == "embed-model"
    assert "dimensions" not in body
    assert body["encoding_format"] == "float"


def test_embeddings_to_openai_itself_keep_dimensions_and_client_side_tokenising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(s, "llm_base_url", "")
    monkeypatch.setattr(s, "rag_embedding_dimensions", 1536)
    client = embedding_gateway._build_embeddings(s)
    assert isinstance(client, langchain_openai.OpenAIEmbeddings)
    assert client.check_embedding_ctx_length is True
    assert client.dimensions == 1536
