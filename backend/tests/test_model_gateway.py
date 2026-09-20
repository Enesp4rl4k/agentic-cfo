"""Unit tests for the Model Gateway — the single LLM egress point."""
from __future__ import annotations

import asyncio

import pytest

from app.platform import model_gateway as mg
from app.platform.model_gateway import (
    GatewayResult,
    LLMBudgetExceeded,
    LLMUnavailable,
    complete,
    is_placeholder_key,
    ledger_snapshot,
    reset_ledger,
)


@pytest.fixture(autouse=True)
def _clean_gateway(monkeypatch):
    reset_ledger()
    # Don't touch the DB from unit tests — the ledger row write is best-effort.
    monkeypatch.setattr(mg, "_persist_call_log", lambda **_: None)
    # Budget check: don't hit the DB; drive it from the in-process ledger only.
    async def _spend(org_id):
        return float((mg._LEDGER.by_org.get(org_id) or {}).get("cost_usd", 0.0))
    monkeypatch.setattr(mg, "_org_month_spend_usd", _spend)
    yield
    reset_ledger()


# ── placeholder key detection ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "key,expected",
    [
        ("", True),
        (None, True),
        ("llm-placeholder-dev", True),
        ("llm-placeholder-ci", True),
        ("llm-placeholder-anything", True),
        ("sk-real-key-value", False),
    ],
)
def test_is_placeholder_key(key, expected):
    assert is_placeholder_key(key) is expected


async def test_placeholder_key_raises_llm_unavailable(monkeypatch):
    async def _raw(*_a, **_k):
        raise LLMUnavailable("openai_api_key is a placeholder")

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    with pytest.raises(LLMUnavailable):
        await complete(task="short_narrative", prompt="hi")


# ── happy path + cost ledger ───────────────────────────────────────────────

async def test_successful_call_records_cost_and_tokens(monkeypatch):
    async def _raw(cfg, system_prompt, prompt, *, schema, temperature, max_tokens, history=None):
        return "cevap metni", None, 1000, 500

    monkeypatch.setattr(mg, "_raw_chat", _raw)

    res = await complete(task="deep_analysis", prompt="analiz", org_id="org-1")

    assert isinstance(res, GatewayResult)
    assert res.text == "cevap metni"
    assert res.input_tokens == 1000
    assert res.output_tokens == 500
    assert res.cost_usd > 0
    assert res.attempts == 1

    snap = ledger_snapshot()
    assert snap["calls"] == 1
    assert snap["ok_calls"] == 1
    assert snap["total_cost_usd"] == pytest.approx(res.cost_usd)
    assert snap["by_org"]["org-1"]["calls"] == 1
    assert res.model in snap["by_model"]


# ── retry semantics ───────────────────────────────────────────────────────

async def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def _raw(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient 503")
        return "ok", None, 10, 10

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    monkeypatch.setattr(mg, "LLM_CALL_BACKOFF_BASE_SECONDS", 0.0, raising=False)

    res = await complete(task="short_narrative", prompt="x", max_attempts=2)
    assert calls["n"] == 2
    assert res.attempts == 2
    assert res.text == "ok"


async def test_retries_exhausted_raises_and_logs_failure(monkeypatch):
    async def _raw(*_a, **_k):
        raise RuntimeError("still failing")

    monkeypatch.setattr(mg, "_raw_chat", _raw)

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        await complete(task="short_narrative", prompt="x", max_attempts=2,
                       timeout_s=1.0)

    snap = ledger_snapshot()
    assert snap["calls"] == 1
    assert snap["ok_calls"] == 0


async def test_timeout_is_enforced(monkeypatch):
    async def _raw(*_a, **_k):
        await asyncio.sleep(1.0)
        return "late", None, 1, 1

    monkeypatch.setattr(mg, "_raw_chat", _raw)

    with pytest.raises(RuntimeError):
        await complete(task="short_narrative", prompt="x",
                       timeout_s=0.05, max_attempts=1)


# ── caching ───────────────────────────────────────────────────────────────

async def test_cache_hit_skips_second_call(monkeypatch):
    calls = {"n": 0}

    async def _raw(*_a, **_k):
        calls["n"] += 1
        return f"answer {calls['n']}", None, 5, 5

    monkeypatch.setattr(mg, "_raw_chat", _raw)

    a = await complete(task="short_narrative", prompt="same", use_cache=True)
    b = await complete(task="short_narrative", prompt="same", use_cache=True)

    assert calls["n"] == 1
    assert a.text == b.text
    assert b.from_cache is True
    assert a.from_cache is False


# ── structured output ─────────────────────────────────────────────────────

async def test_schema_path_returns_parsed(monkeypatch):
    from pydantic import BaseModel

    class Mini(BaseModel):
        summary: str

        def to_text(self) -> str:
            return self.summary

    async def _raw(cfg, system_prompt, prompt, *, schema, temperature, max_tokens, history=None):
        assert schema is Mini
        obj = Mini(summary="özet")
        return obj.to_text(), obj, 20, 8

    monkeypatch.setattr(mg, "_raw_chat", _raw)

    res = await complete(task="short_narrative", prompt="x", schema=Mini)
    assert isinstance(res.parsed, Mini)
    assert res.parsed.summary == "özet"
    assert res.text == "özet"


# ── per-org budget guard ──────────────────────────────────────────────────

async def test_budget_soft_warn_still_proceeds(monkeypatch, caplog):
    async def _raw(*_a, **_k):
        return "ok", None, 1000, 1000

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    monkeypatch.setattr(mg, "_org_budget_usd", lambda _o: 1.0)
    # Prime the ledger so the org is at ~90% of a $1.00 budget.
    mg._LEDGER.by_org["org-warn"] = {"calls": 1, "cost_usd": 0.90}

    with caplog.at_level("WARNING"):
        res = await complete(task="deep_analysis", prompt="x", org_id="org-warn")
    assert res.text == "ok"
    assert any("LLM budget" in r.message for r in caplog.records)


async def test_budget_hard_cap_raises(monkeypatch):
    async def _raw(*_a, **_k):
        return "should not be called", None, 1, 1

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    monkeypatch.setattr(mg, "_org_budget_usd", lambda _o: 1.0)
    mg._LEDGER.by_org["org-broke"] = {"calls": 5, "cost_usd": 1.50}

    with pytest.raises(LLMBudgetExceeded) as ei:
        await complete(task="deep_analysis", prompt="x", org_id="org-broke")
    assert ei.value.org_id == "org-broke"
    assert ei.value.budget_usd == 1.0


async def test_budget_not_enforced_without_org(monkeypatch):
    async def _raw(*_a, **_k):
        return "ok", None, 1, 1

    monkeypatch.setattr(mg, "_raw_chat", _raw)
    monkeypatch.setattr(mg, "_org_budget_usd", lambda _o: 0.0001)
    res = await complete(task="deep_analysis", prompt="x")  # no org_id
    assert res.text == "ok"
