"""A template LLM key is never sent to a provider (app/core/llm_key.py)."""
from __future__ import annotations

import pytest

from app.core.llm_key import is_placeholder_key

TEMPLATES = ["", "   ", None, "llm-placeholder-dev", "LLM-PLACEHOLDER-ci", "your-llm-api-key-here", "Your-Key",
             "change-me", "changeme-please", "change_me_now", "change-this-key", "xxx", "xxxxxxxx", "sk-xxxxxxxxxxxx",
             "<api key>", " <your key> "]
REAL = ["sk-proj-abc123def456", "ds-1a2b3c4d5e6f", "sk-live-9f8e7d"]


@pytest.mark.parametrize("key", TEMPLATES)
def test_template_forms_are_placeholders(key):
    assert is_placeholder_key(key) is True


@pytest.mark.parametrize("key", REAL)
def test_real_looking_keys_are_not(key):
    assert is_placeholder_key(key) is False


@pytest.mark.parametrize("key", [k for k in TEMPLATES if k is not None])
def test_a_template_key_builds_no_client_and_embeds_nothing(monkeypatch, key):
    """Recording fake: constructing the provider client (the only way a request leaves) is counted; it must be zero."""
    import langchain_openai

    from app.config import get_settings
    from app.platform import model_gateway as mg
    from app.platform.model_catalog import ModelConfig
    from app.services import rag_service

    built: list[object] = []
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: built.append(kw))
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", key)
    with pytest.raises(mg.LLMUnavailable):
        mg._build_client(ModelConfig(model_id="m", tier="cheap"), None, None)
    assert built == []
    assert rag_service._has_embedding_support() is False
