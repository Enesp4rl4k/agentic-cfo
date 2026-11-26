"""The gateway applies the data mode to every payload: masked, off, raw; chat, structured, stream, embeddings.

A recording fake sits behind the gateways (see `llm_egress_harness`); the code in front of it is real.
"""
from __future__ import annotations

import json
import re

import pytest
import pytest_asyncio
from pydantic import BaseModel

from app import database
from app.core.tenancy import set_current_tenant
from app.models.organization import Organization
from app.platform import embedding_gateway
from app.platform import llm_egress as egress
from app.platform import model_gateway as mg
from app.platform.llm_egress import dictionary, policy
from tests.db_helpers import gecici_veritabani
from tests.llm_egress_harness import (
    CANARY,
    DESCRIPTION,
    LEAK_VALUES,
    Recorder,
    install,
    leaked_in,
    seed_company,
)


@pytest_asyncio.fixture
async def world(monkeypatch):
    async with gecici_veritabani() as maker:
        monkeypatch.setattr(database, "session_factory", lambda: maker)
        policy._CHOICES.clear()
        dictionary.forget()
        org_id = await seed_company(maker)
        rec = Recorder()
        install(monkeypatch, rec)
        # a fixture's contextvars do not reach the test's task: each test calls `world.enter()` first
        yield type("World", (), {"org_id": org_id, "rec": rec, "maker": maker,
                                 "enter": staticmethod(lambda: set_current_tenant(org_id))})
        set_current_tenant(None)
        policy._CHOICES.clear()
        dictionary.forget()


def _placeholders(texts: list[str]) -> list[str]:
    return re.findall(r"\[[A-ZÇĞİÖŞÜ_]+_\d+\]", "\n".join(texts))


SYSTEM = f"Sen {CANARY.company} için çalışan bir danışmansın. Hesap: {CANARY.iban}."
PROMPT = f"{DESCRIPTION}. Tutar 1.234.567,89 TL, tarih 15.03.2026, KDV %20. VKN: {CANARY.vkn}. Kimlik {CANARY.tckn}."
HISTORY = [{"role": "user", "content": f"{CANARY.vendor} ne kadar aldı? kart {CANARY.pan}"},
           {"role": "assistant", "content": f"{CANARY.vendor_short} için 500,00 TL görünüyor."}]


# ── masked: what leaves, and what comes back ─────────────────────────────────

async def test_masked_complete_text_sends_no_canary_and_restores_the_reply(world) -> None:
    world.enter()
    world.rec.reply = lambda texts: "Özet: " + " ve ".join(sorted(set(_placeholders(texts)))[:3]) + " [KARŞI_TARAF_99]"
    out = await mg.complete_text(task="deep_analysis", system_prompt=SYSTEM, prompt=PROMPT, history=HISTORY)
    sent = world.rec.text()
    assert leaked_in(sent) == [], leaked_in(sent)
    assert world.rec.count("chat") == 1
    assert "1.234.567,89 TL" in sent and "15.03.2026" in sent and "KDV %20" in sent  # figures are never masked
    assert _placeholders(world.rec.sent[0].texts)
    assert leaked_in(out) != []                                  # the reply shows the real names again
    assert "[bilinmeyen taraf]" in out and "[KARŞI_TARAF_99]" not in out   # a hallucinated placeholder is never a wrong name


async def test_masked_structured_output_is_restored_field_by_field_and_numbers_are_untouched(world) -> None:
    world.enter()
    class Finding(BaseModel):
        who: str
        note: str
        amount_cents: int
        items: list[str]

        def to_text(self) -> str:
            return self.note

    world.rec.structured = lambda schema: schema(
        who="[KARŞI_TARAF_1]", note="Ödeme [IBAN_1] hesabına", amount_cents=123456789, items=["[KİŞİ_1]", "[KİŞİ_9]"]
    )
    result = await mg.complete(task="deep_analysis", system_prompt=SYSTEM, prompt=PROMPT, schema=Finding)
    assert leaked_in(world.rec.text()) == []
    got = result.parsed
    assert CANARY.counterparty in got.who or CANARY.vendor in got.who
    assert CANARY.iban in got.note or CANARY.iban_spaced in got.note
    assert got.amount_cents == 123456789
    assert got.items[1] == "[bilinmeyen taraf]"


async def test_masked_stream_restores_placeholders_split_across_chunks(world) -> None:
    world.enter()
    world.rec.reply = lambda texts: f"Ödenecek: {_placeholders(texts)[0]} ve [KİŞİ_77] kısa."
    pieces = [p async for p in mg.stream(task="deep_analysis", system_prompt=SYSTEM, prompt=PROMPT, history=HISTORY)]
    text = "".join(pieces)
    assert leaked_in(world.rec.text()) == []
    assert world.rec.count("stream") == 1
    assert "[bilinmeyen taraf]" in text and "[KİŞİ_77]" not in text and "[" not in text.replace("[bilinmeyen taraf]", "")


async def test_the_router_path_goes_through_the_same_choke_point(world) -> None:
    world.enter()
    from app.services.llm_router import LLMTaskRouter

    await LLMTaskRouter()._call_llm(mg.config_for_tier(mg.Tier.STRONG), PROMPT, SYSTEM)
    assert world.rec.count("chat") == 1 and leaked_in(world.rec.text()) == []


async def test_no_organisation_context_masks_patterns_only_and_says_so(world, monkeypatch) -> None:
    world.enter()
    set_current_tenant(None)
    seen = []
    monkeypatch.setattr(mg, "_persist_call_log", lambda **kw: seen.append(kw["tally"]))
    await mg.complete_text(task="short_narrative", prompt=PROMPT)
    sent = world.rec.text()
    assert CANARY.iban not in sent and CANARY.tckn not in sent and CANARY.email not in sent       # patterns work anywhere
    assert CANARY.counterparty_short in sent                                                      # names need a company
    assert "no_organisation_context" in seen[0].flags


# ── off ──────────────────────────────────────────────────────────────────────

async def test_off_makes_no_call_at_all_and_callers_see_unavailable(world, monkeypatch) -> None:
    world.enter()
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_data_mode", "off")
    with pytest.raises(mg.LLMDisabled):
        await mg.complete_text(task="deep_analysis", prompt=PROMPT, system_prompt=SYSTEM)
    with pytest.raises(mg.LLMUnavailable):                 # the exception callers already handle
        await mg.complete(task="deep_analysis", prompt=PROMPT)
    with pytest.raises(mg.LLMDisabled):
        _ = [p async for p in mg.stream(task="deep_analysis", prompt=PROMPT)]
    assert await embedding_gateway.embed_texts([DESCRIPTION], org_id=world.org_id) is None
    assert world.rec.sent == []


# ── raw: unchanged ───────────────────────────────────────────────────────────

async def test_raw_sends_exactly_what_master_sent_byte_for_byte(world, monkeypatch) -> None:
    world.enter()
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_data_mode", "raw")
    await mg.complete_text(task="deep_analysis", system_prompt=SYSTEM, prompt=PROMPT, history=HISTORY)
    # master built the messages with `_build_messages` from the untouched arguments (that function is unchanged)
    expected = [str(m.content) for m in mg._build_messages(SYSTEM, PROMPT, HISTORY)]
    assert world.rec.sent[0].texts == expected
    assert [t for t in expected if CANARY.iban in t]            # and it really carries the canary: raw is raw
    pieces = [p async for p in mg.stream(task="deep_analysis", system_prompt=SYSTEM, prompt=PROMPT, history=HISTORY)]
    assert world.rec.sent[1].texts == expected and "".join(pieces) == world.rec.reply


# ── per organisation ─────────────────────────────────────────────────────────

async def _set_choice(world, value) -> None:
    async with world.maker() as db:
        org = await db.get(Organization, world.org_id)
        org.llm_data_mode = value
        await db.commit()
    policy._CHOICES.clear()


async def test_the_organisation_can_tighten_but_not_loosen_unless_the_operator_allows(world, monkeypatch) -> None:
    world.enter()
    from app.config import get_settings

    assert (await policy.effective_mode(world.org_id)).mode == policy.DataMode.MASKED
    await _set_choice(world, "off")
    assert (await policy.effective_mode(world.org_id)).mode == policy.DataMode.OFF
    await _set_choice(world, "raw")
    capped = await policy.effective_mode(world.org_id)
    assert capped.mode == policy.DataMode.MASKED and capped.capped
    monkeypatch.setattr(get_settings(), "llm_org_may_relax", True)
    assert (await policy.effective_mode(world.org_id)).mode == policy.DataMode.RAW
    await mg.complete_text(task="deep_analysis", prompt=PROMPT)
    assert CANARY.iban_spaced in world.rec.text()               # the owner chose raw, so raw it is


async def test_an_unreadable_organisation_choice_fails_closed(world, monkeypatch) -> None:
    world.enter()
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_data_mode", "raw")
    policy._CHOICES.clear()

    def broken():
        raise RuntimeError("database down")

    monkeypatch.setattr(database, "session_factory", broken)
    assert (await policy.effective_mode(world.org_id)).mode == policy.DataMode.MASKED


# ── embeddings ───────────────────────────────────────────────────────────────

async def test_masked_embeddings_use_stable_pseudonyms_for_index_and_query_alike(world) -> None:
    world.enter()
    chunk = f"{DESCRIPTION} Menekşe Tekstil adına"
    indexed = await embedding_gateway.embed_texts([chunk], org_id=world.org_id)
    query = await embedding_gateway.embed_texts([f"{CANARY.counterparty_short.upper()} ödemeleri"], org_id=world.org_id,
                                                purpose="rag_query")
    assert leaked_in(world.rec.text()) == []
    assert world.rec.count("embed") == 2
    token = re.findall(r"\[KARŞI_TARAF_[0-9a-f]{8}\]", world.rec.sent[0].texts[0])
    assert token and token == re.findall(r"\[KARŞI_TARAF_[0-9a-f]{8}\]", world.rec.sent[1].texts[0])  # same name, same token
    assert indexed.tag == query.tag and indexed.tag.endswith("+pseud1")                              # never mixed with raw vectors


async def test_raw_embeddings_are_unchanged_and_off_embeds_nothing(world, monkeypatch) -> None:
    world.enter()
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_data_mode", "raw")
    out = await embedding_gateway.embed_texts([DESCRIPTION], org_id=world.org_id)
    assert world.rec.sent[0].texts == [DESCRIPTION] and out.tag == get_settings().rag_embedding_model
    monkeypatch.setattr(get_settings(), "llm_data_mode", "off")
    assert await embedding_gateway.embed_texts([DESCRIPTION], org_id=world.org_id) is None
    assert world.rec.count() == 1


async def test_the_retriever_only_compares_vectors_of_its_own_kind(world) -> None:
    world.enter()
    import inspect

    from app.services.rag import retriever

    src = inspect.getsource(retriever.EmbeddingRagRetriever.retrieve)
    assert src.count("embedding_model = :embedding_model") == 2     # the main query and the org-wide fallback


# ── the audit row: counts, never payloads ────────────────────────────────────

async def test_the_audit_tally_has_counts_and_bytes_and_no_payload(world, monkeypatch) -> None:
    world.enter()
    rows = []
    monkeypatch.setattr(mg, "_persist_call_log", lambda **kw: rows.append(kw))
    await mg.complete_text(task="anomaly_narrative", system_prompt=SYSTEM, prompt=PROMPT, history=HISTORY)
    tally = rows[0]["tally"]
    record = tally.as_record()
    assert tally.mode == "masked" and rows[0]["task"] == "anomaly_narrative" and tally.org_id == world.org_id
    assert tally.bytes_out == sum(len(t.encode()) for t in world.rec.sent[0].texts)
    counts = record["counts"]
    assert counts["IBAN"] >= 2 and counts["KARŞI_TARAF"] >= 2 and counts["ŞİRKET"] >= 1 and counts["TELEFON"] >= 1
    assert counts["E_POSTA"] >= 1 and counts["KİŞİ"] >= 1 and counts["KART"] == 1
    assert leaked_in(json.dumps(record, ensure_ascii=False)) == []
    assert not any(v in json.dumps(record, ensure_ascii=False) for v in LEAK_VALUES)


async def test_the_audit_row_is_written_with_its_new_columns(world, monkeypatch) -> None:
    world.enter()
    import asyncio

    from sqlalchemy import select

    from app.models.llm_call_log import LLMCallLog
    from app.platform.llm_egress import audit

    monkeypatch.setattr(mg, "_persist_call_log", audit.persist_call_log)   # the real writer, the real table
    await mg.complete_text(task="anomaly_narrative", prompt=PROMPT, org_id=world.org_id)
    for _ in range(50):
        await asyncio.sleep(0.05)
        async with world.maker() as db:
            rows = (await db.execute(select(LLMCallLog))).scalars().all()
        if rows:
            break
    assert rows and rows[0].data_mode == "masked" and rows[0].bytes_out > 0 and rows[0].replaced["counts"]["IBAN"] >= 1
    async with world.maker() as db:
        usage = await audit.usage_last_days(db, world.org_id, 30)
    assert usage["calls"] == 1 and usage["bytes_out"] == rows[0].bytes_out and usage["calls_by_mode"] == {"masked": 1}


# ── strict document mode ─────────────────────────────────────────────────────

async def test_strict_document_mode_and_off_skip_the_ai_step_with_a_visible_reason(world, monkeypatch) -> None:
    world.enter()
    from app.config import get_settings

    assert await policy.begin_document_extraction(world.org_id) is None
    monkeypatch.setattr(get_settings(), "llm_document_text", "never")
    reason = await policy.begin_document_extraction(world.org_id)
    assert reason and "atlandı" in reason and "LLM_DOCUMENT_TEXT" in reason
    monkeypatch.setattr(get_settings(), "llm_data_mode", "off")
    assert "LLM_DATA_MODE=off" in (await policy.begin_document_extraction(world.org_id) or "")


async def test_the_session_api_is_what_the_gateway_uses() -> None:
    assert egress.open_session is not None and egress.PolicyOff is policy.PolicyOff


# ── the dictionary says when it is not whole ─────────────────────────────────

async def test_a_capped_or_unreadable_dictionary_is_flagged_on_the_call_not_hidden(world, monkeypatch) -> None:
    world.enter()
    seen = []
    monkeypatch.setattr(mg, "_persist_call_log", lambda **kw: seen.append(kw["tally"]))
    monkeypatch.setattr(dictionary, "_CAP", 0)               # every source reports "more rows than the cap"
    dictionary.forget()
    await mg.complete_text(task="short_narrative", prompt=PROMPT)
    assert "dictionary_truncated" in seen[-1].flags

    monkeypatch.setattr(dictionary, "_CAP", 5000)

    async def broken(db, stmt):
        raise RuntimeError("table unreadable")

    monkeypatch.setattr(dictionary, "_values", broken)
    dictionary.forget()
    await mg.complete_text(task="short_narrative", prompt=PROMPT)
    assert "dictionary_incomplete" in seen[-1].flags
    loaded = await dictionary.load(world.org_id)
    assert loaded.complete is False and len(loaded.names) >= 1   # the company's own name is still known


async def test_off_says_so_in_turkish_for_the_person(world, monkeypatch) -> None:
    from app.config import get_settings

    world.enter()
    monkeypatch.setattr(get_settings(), "llm_data_mode", "off")
    with pytest.raises(mg.LLMDisabled) as err:
        await mg.complete_text(task="deep_analysis", prompt=PROMPT)
    assert "kapalı" in str(err.value) and "LLM_DATA_MODE=off" in str(err.value)
