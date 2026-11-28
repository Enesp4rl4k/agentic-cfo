"""ReasoningLoop reaches the model when the data mode allows it, says so when it does not, and never hides a bug.

Before this change every phase called `LLMTaskRouter.complete(task=, prompt=, max_tokens=)`. That method takes no
`max_tokens`, so each call raised TypeError; a bare `except` logged it at debug level and the loop answered from its
template, always. The fallback made the bug invisible. Now the phases call the Model Gateway's public API, and a
fallback is classified: "unavailable" (no key, `off`, masked-mode refusal, budget) is the honest template path with
the product's "Yapay zekâ adımı atlandı" note; anything else is a FAILURE that is logged at ERROR with its type,
counted, written as an audit row and listed in the trace.

Fake transport only (`tests/llm_egress_harness.py`): no provider is contacted.
"""
from __future__ import annotations

import json
import logging

import pytest

from app.agents.narrative_guard import AI_STEP_SKIPPED
from app.services import reasoning_loop as rl
from tests.llm_egress_harness import CANARY, Recorder, leaked_in, open_world

QUESTION = f"{CANARY.counterparty} ödemesi nakit akışını nasıl etkiler?"
CONTEXT = {"pnl": {"revenue": 123_456_789, "net_margin": 0.08, "gross_margin": 0.3, "ebitda": 9_000_000},
           "cashflow": {"operating": 5_000_000, "net": 1_000_000}}


def _reply(texts: list[str]) -> str:
    prompt = texts[-1]
    if '"observations"' in prompt:
        return json.dumps({"observations": [f"MODEL-OBS {CANARY.counterparty} bakiyesi yüksek"], "uncertainties": [],
                           "domain_focus": "cfo", "key_numbers": {"revenue": 123_456_789}}, ensure_ascii=False)
    if '"reasoning_approach"' in prompt:
        return json.dumps({"reasoning_approach": "MODEL-PLAN",
                           "steps": [{"step_id": 1, "description": "nakit etkisini yorumla", "tool": "llm"}]})
    if "max 3 cümle" in prompt:
        return "MODEL-ACT nakit etkisi sınırlı."
    return "MODEL-ANSWER Nakit pozisyonu güçlü kalır."


@pytest.fixture(autouse=True)
def _clean_counts(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "reasoning_loop_enabled", True)  # every test below: the flag ON
    rl.FALLBACKS.clear()
    yield
    rl.FALLBACKS.clear()


def test_the_loop_is_off_by_default_and_the_chat_says_so(monkeypatch) -> None:
    from app.api.chat import reasoning_choice
    from app.config import Settings, get_settings

    assert Settings.model_fields["reasoning_loop_enabled"].default is False
    assert Settings.model_fields["reasoning_loop_timeout_seconds"].default == 60.0
    monkeypatch.setattr(get_settings(), "reasoning_loop_enabled", False)
    assert reasoning_choice(True) == (False, rl.LOOP_DISABLED_NOTE)
    assert reasoning_choice(False) == (False, None)
    monkeypatch.setattr(get_settings(), "reasoning_loop_enabled", True)
    assert reasoning_choice(True) == (True, None)
    assert rl.MAX_LLM_CALLS == 6  # think, plan, at most 3 act steps, synthesize (documented)


async def test_a_disabled_loop_makes_no_model_call(monkeypatch) -> None:
    from app.config import get_settings

    async with open_world(monkeypatch, Recorder(reply=_reply), tenant=True) as env:
        monkeypatch.setattr(get_settings(), "reasoning_loop_enabled", False)
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    assert env.rec.count() == 0 and result.answer == rl.LOOP_DISABLED_NOTE and result.llm["disabled"]


async def test_the_number_of_calls_is_capped(monkeypatch) -> None:
    def many_steps(texts: list[str]) -> str:
        if '"reasoning_approach"' in texts[-1]:
            return json.dumps({"reasoning_approach": "x", "steps": [
                {"step_id": i, "description": f"adım {i}", "tool": "llm"} for i in range(1, 9)]})
        return _reply(texts)

    async with open_world(monkeypatch, Recorder(reply=many_steps), tenant=True) as env:
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT, max_act_steps=8)
    assert env.rec.count() == rl.MAX_LLM_CALLS and len(result.actions) == rl.MAX_ACT_STEPS


async def test_the_whole_loop_has_a_time_limit(monkeypatch) -> None:
    import asyncio

    from app.config import get_settings
    from app.platform import model_gateway
    from app.platform.llm_egress import audit

    async def slow(**kwargs):
        await asyncio.sleep(5)

    rows: list[dict] = []
    async with open_world(monkeypatch, Recorder(reply=_reply), tenant=True):
        monkeypatch.setattr(get_settings(), "reasoning_loop_timeout_seconds", 0.05)
        monkeypatch.setattr(model_gateway, "complete", slow)
        monkeypatch.setattr(audit, "persist_call_log", lambda **kw: rows.append(kw))
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    assert result.answer.startswith(rl.LOOP_TIMEOUT_NOTE) and result.llm["timed_out"]
    assert [(r["task"], r["error"]) for r in rows] == [("reasoning_loop.loop", "TimeoutError:loop_timeout")]


async def test_a_provider_failure_is_one_audit_row_not_two(monkeypatch) -> None:
    """The gateway writes the failed call's row; the loop counts its fallback but writes no second row."""
    from app.platform import model_gateway as mg
    from app.platform.llm_egress import audit

    class _Down:
        async def ainvoke(self, messages):
            raise RuntimeError("upstream 500")

    gateway_rows: list[dict] = []
    loop_rows: list[dict] = []
    async with open_world(monkeypatch, Recorder(reply=_reply), tenant=True):
        monkeypatch.setattr(mg, "_build_client", lambda cfg, temperature, max_tokens: _Down())
        monkeypatch.setattr(mg, "_persist_call_log", lambda **kw: gateway_rows.append(kw))
        monkeypatch.setattr(audit, "persist_call_log", lambda **kw: loop_rows.append(kw))
        monkeypatch.setattr(mg, "LLM_CALL_BACKOFF_BASE_SECONDS", 0)
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    failed = [r for r in gateway_rows if not r["ok"]]
    assert len(failed) == len(result.llm["failures"]) >= 2, (failed, result.llm)  # one row per failed call
    assert loop_rows == [], "the loop wrote a second row for a failure the gateway already recorded"


async def test_the_llm_path_is_taken_when_the_mode_allows(monkeypatch) -> None:
    async with open_world(monkeypatch, Recorder(reply=_reply), tenant=True) as env:
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    assert env.rec.count() == 4, "think, plan, one act step and synthesize each reach the (fake) provider"
    assert result.llm == {"calls": 4, "unavailable": [], "failures": [], "timed_out": False}
    assert result.answer.startswith("MODEL-ANSWER")
    assert result.think.observations[0].startswith("MODEL-OBS") and CANARY.counterparty in result.think.observations[0]
    assert result.plan.reasoning_approach == "MODEL-PLAN"
    assert result.actions[0].output.startswith("MODEL-ACT")
    assert leaked_in(env.rec.text()) == [], "masked mode: the question's counterparty left unmasked"
    assert rl.fallback_counts() == {}


@pytest.mark.parametrize(("mode", "tenant", "note"), [
    ("off", True, AI_STEP_SKIPPED["off"]),
    ("masked", False, AI_STEP_SKIPPED["refused"]),  # no company known: masked mode fails closed
])
async def test_the_labelled_template_path_when_the_mode_does_not_allow(monkeypatch, mode, tenant, note) -> None:
    async with open_world(monkeypatch, Recorder(reply=_reply), mode=mode, tenant=tenant) as env:
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    assert env.rec.count() == 0
    assert result.answer.startswith(note), result.answer
    assert result.llm["calls"] == 0 and result.llm["failures"] == []
    assert result.llm["unavailable"], "the skip is recorded per phase"
    assert all(k.startswith(tuple(f"{p}:unavailable:" for p in ("think", "plan", "act", "synthesize")))
               for k in rl.fallback_counts())


async def test_a_type_error_in_the_call_path_is_not_treated_as_llm_unavailable(monkeypatch, caplog) -> None:
    """The original bug, reproduced: the call itself is wrong. It must be loud, counted and audited."""
    from app.platform import model_gateway
    from app.platform.llm_egress import audit

    async def wrong_signature(**kwargs):
        raise TypeError("complete() got an unexpected keyword argument 'max_tokens'")

    rows: list[dict] = []
    async with open_world(monkeypatch, Recorder(reply=_reply), tenant=True) as env:
        monkeypatch.setattr(model_gateway, "complete", wrong_signature)
        monkeypatch.setattr(model_gateway, "complete_text", wrong_signature)
        monkeypatch.setattr(audit, "persist_call_log", lambda **kw: rows.append(kw))
        with caplog.at_level(logging.INFO, logger="app.services.reasoning_loop"):
            result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    assert env.rec.count() == 0
    assert not any(result.answer.startswith(n) for n in AI_STEP_SKIPPED.values()), "a bug is not 'AI step skipped'"
    assert result.llm["failures"] and all(f.endswith(":TypeError") for f in result.llm["failures"])
    assert result.llm["unavailable"] == []
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors and all("TypeError" in r.getMessage() for r in errors)
    assert rl.fallback_counts().get("think:failure:TypeError") == 1
    assert rows and {r["error"] for r in rows} == {"TypeError:fallback"}
    assert {r["task"] for r in rows} >= {"reasoning_loop.think", "reasoning_loop.synthesize"}
    assert all("max_tokens" not in str(r) for r in rows), "the audit row stores the type and a code, never the message"
