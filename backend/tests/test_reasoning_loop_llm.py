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
def _clean_counts():
    rl.FALLBACKS.clear()
    yield
    rl.FALLBACKS.clear()


async def test_the_llm_path_is_taken_when_the_mode_allows(monkeypatch) -> None:
    async with open_world(monkeypatch, Recorder(reply=_reply), tenant=True) as env:
        result = await rl.ReasoningLoop().run(QUESTION, CONTEXT)
    assert env.rec.count() == 4, "think, plan, one act step and synthesize each reach the (fake) provider"
    assert result.llm == {"calls": 4, "unavailable": [], "failures": []}
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
