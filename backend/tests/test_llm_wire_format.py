"""The request the gateway puts on the wire, as an OpenAI-compatible provider (DeepSeek) reads it.

langchain-openai 1.x changed two defaults: structured output became `response_format=json_schema`
(was a tool call) and `max_tokens` became `max_completion_tokens`. A DeepSeek-compatible
LLM_BASE_URL answers the former only when it supports it and may silently ignore the latter, so the
gateway pins the wire format it always had. No network: only the payload is built.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.platform import model_gateway
from app.platform.model_catalog import config_for_tier


class _Out(BaseModel):
    answer: str


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.config import get_settings

    settings = get_settings().model_copy(
        update={
            "openai_api_key": "sk-real-looking-key-for-payload-test",
            "llm_temperature": 0.2,
            "llm_max_tokens": 777,
            "llm_base_url": "https://api.deepseek.com/v1",
        }
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    return model_gateway._build_client(config_for_tier("cheap"), None, None)


def test_output_cap_is_sent_as_max_tokens(client: Any) -> None:
    payload = client._get_request_payload([("user", "merhaba")])
    # extra_body is merged into the JSON body by the OpenAI client, so the provider receives max_tokens
    assert payload["extra_body"] == {"max_tokens": 777}
    assert "max_completion_tokens" not in payload
    assert "max_tokens" not in payload
    assert str(client.openai_api_base).startswith("https://api.deepseek.com")


def test_structured_output_is_a_tool_call_not_a_response_format(client: Any) -> None:
    bound = client.with_structured_output(_Out, method="function_calling")
    kwargs = bound.first.kwargs  # RunnableBinding: the arguments each call carries
    assert kwargs["tools"][0]["function"]["name"] == "_Out"
    assert "response_format" not in kwargs
