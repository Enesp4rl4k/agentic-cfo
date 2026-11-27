"""The gateway asks the provider for the *configured* model, never a hard-coded one.

Regression: model_catalog hard-coded vendor ids ("gpt-4o"), so with the shipped
DeepSeek default every call asked the provider for a model it does not have and
the product silently ran on template fallbacks. No network, no key: the client
is a recorder around MockLLM.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from app.config import get_settings
from app.platform import model_catalog as mc
from app.platform import model_gateway as mg
from tests.fixtures.llm_mock import MockLLM

_APP = Path(__file__).resolve().parent.parent / "app"


class _Recorder(MockLLM):
    instances: list[dict] = []

    def __init__(self, **kwargs):
        super().__init__(response="tamam")
        type(self).instances.append(kwargs)


class _ProviderError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"Error code: {status_code} - model does not exist")
        self.status_code = status_code


@pytest.fixture
def cfg(monkeypatch):
    """Real-looking key + default model settings; ChatOpenAI replaced by a recorder."""
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(s, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(s, "llm_model", "deepseek-chat")
    monkeypatch.setattr(s, "llm_model_cheap", None)
    monkeypatch.setattr(s, "llm_model_strong", None)
    monkeypatch.setattr(s, "llm_model_prices", {})
    # model selection, not data minimisation: `raw` needs no company context (masked fails closed without one;
    # that is tests/test_llm_egress_fail_closed.py)
    monkeypatch.setattr(s, "llm_data_mode", "raw")
    mc._warned_unpriced.clear()
    _Recorder.instances = []
    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Recorder)
    monkeypatch.setattr(mg, "_persist_call_log", lambda **_: None)

    async def _spend(_org):
        return 0.0

    monkeypatch.setattr(mg, "_org_month_spend_usd", _spend)
    mg.reset_ledger()
    yield s
    mg.reset_ledger()


# (a) default settings -> the configured llm_model

@pytest.mark.parametrize("task", ["classify_intent", "deep_analysis", "contract_analysis"])
async def test_default_settings_request_configured_model(cfg, task):
    res = await mg.complete(task=task, prompt="merhaba")
    assert _Recorder.instances[-1]["model"] == "deepseek-chat"
    assert res.model == "deepseek-chat"


async def test_long_prompt_and_override_use_configured_model(cfg):
    await mg.complete(task="short_narrative", prompt="x" * 9000)
    await mg.complete(task="short_narrative", prompt="hi", model_override="strong")
    assert [i["model"] for i in _Recorder.instances] == ["deepseek-chat"] * 2


async def test_settings_temperature_and_max_tokens_are_defaults(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "llm_temperature", 0.25)
    monkeypatch.setattr(cfg, "llm_max_tokens", 1234)
    await mg.complete(task="deep_analysis", prompt="hi")
    last = _Recorder.instances[-1]
    assert (last["temperature"], last["extra_body"]["max_tokens"]) == (0.25, 1234)
    await mg.complete(task="deep_analysis", prompt="hi", temperature=0.9, max_tokens=50)
    last = _Recorder.instances[-1]
    assert (last["temperature"], last["extra_body"]["max_tokens"]) == (0.9, 50)


# (b) tier overrides

async def test_tier_overrides_are_honoured(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "llm_model_cheap", "small-x")
    monkeypatch.setattr(cfg, "llm_model_strong", "big-y")
    await mg.complete(task="classify_intent", prompt="hi")
    await mg.complete(task="deep_analysis", prompt="hi")
    await mg.complete(task="short_narrative", prompt="x" * 9000)  # long prompt -> strong
    assert [i["model"] for i in _Recorder.instances] == ["small-x", "big-y", "big-y"]


def test_one_tier_override_leaves_the_other_on_llm_model(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "llm_model_strong", "big-y")
    assert mc.select_model("classify_intent").model_id == "deepseek-chat"
    assert mc.select_model("deep_analysis").model_id == "big-y"


def test_catalog_maps_tasks_to_tiers_not_models():
    assert set(mc.TASK_TO_TIER.values()) == {mc.Tier.CHEAP, mc.Tier.STRONG}
    assert mc.TASK_TO_TIER["classify_intent"] == mc.Tier.CHEAP
    assert mc.TASK_TO_TIER["deep_analysis"] == mc.Tier.STRONG


# (c) architecture: no vendor model id outside config.py

def test_no_vendor_model_id_in_app_outside_config():
    pattern = re.compile(r"gpt-4o|deepseek-chat")
    # app/services/llm_router.py still carries the old ids (its docstring and the
    # MODELS["gpt-4o"] lookups). Another PR owns that file; delete this entry when
    # it is fixed -- the test fails if the entry no longer violates.
    pending = {"services/llm_router.py"}
    offenders = {
        p.relative_to(_APP).as_posix()
        for p in _APP.rglob("*.py")
        if p.relative_to(_APP).as_posix() != "config.py"
        and pattern.search(p.read_text(encoding="utf-8"))
    }
    assert offenders == pending, f"vendor model ids hard-coded in: {sorted(offenders ^ pending)}"


# (d) 4xx is not retried and is named in the log

async def test_4xx_model_error_is_not_retried_and_logged_once(cfg, monkeypatch, caplog):
    calls = []

    async def _raw(*_a, **_k):
        calls.append(1)
        raise _ProviderError(400)

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    with caplog.at_level(logging.ERROR, logger=mg.logger.name):
        with pytest.raises(mg.LLMUnavailable):
            await mg.complete(task="deep_analysis", prompt="hi", max_attempts=3)
    assert len(calls) == 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    msg = errors[0].getMessage()
    assert "api.deepseek.com" in msg and "deepseek-chat" in msg
    assert "sk-test-not-real" not in msg


@pytest.mark.parametrize("status", [429, 500])
async def test_transient_errors_are_still_retried(cfg, monkeypatch, status):
    calls = []

    async def _raw(*_a, **_k):
        calls.append(1)
        raise _ProviderError(status)

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    monkeypatch.setattr(mg, "LLM_CALL_BACKOFF_BASE_SECONDS", 0)
    with pytest.raises(RuntimeError):
        await mg.complete(task="deep_analysis", prompt="hi", max_attempts=3)
    assert len(calls) == 3


def test_config_status_names_pair_without_key_or_network(cfg):
    st = mg.llm_config_status()
    assert st["base_url_host"] == "api.deepseek.com"
    assert st["models"] == {"cheap": "deepseek-chat", "strong": "deepseek-chat"}
    assert st["ready"] is True
    assert "sk-test-not-real" not in repr(st)


# (e) unknown price -> null cost

async def test_unknown_price_cost_is_null_and_logged_once(cfg, caplog):
    with caplog.at_level(logging.WARNING, logger=mc.logger.name):
        r1 = await mg.complete(task="deep_analysis", prompt="hi")
        r2 = await mg.complete(task="classify_intent", prompt="hi again")
    assert r1.cost_usd is None and r2.cost_usd is None
    assert len([r for r in caplog.records if "price unknown" in r.getMessage()]) == 1
    snap = mg.ledger_snapshot()
    assert snap["unpriced_calls"] == 2 and snap["total_cost_usd"] == 0.0


async def test_known_price_costs_only_that_model(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "llm_model_cheap", "small-x")
    monkeypatch.setattr(cfg, "llm_model_prices", {"small-x": (0.001, 0.002)})

    async def _raw(*_a, **_k):
        return "t", None, 1000, 1000

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    cheap = await mg.complete(task="classify_intent", prompt="hi")
    strong = await mg.complete(task="deep_analysis", prompt="hi")  # deepseek-chat: no price
    assert cheap.cost_usd == pytest.approx(0.003)
    assert strong.cost_usd is None
