"""Booking a large statement: the model is asked only where the rules failed, in parallel, once per input."""
from __future__ import annotations

import asyncio

import pytest

from app.agents.accounting.orchestrator import _LLM_ESZAMANLI, MuhasebeAgent
from app.services.accounting.thp_classifier import THPClassifier, THPSonucu


def _sonuc(kod: str, yontem: str) -> THPSonucu:
    return THPSonucu(hesap_kodu=kod, hesap_adi=kod, ana_grup="7", normal_bakiye="borç", tip="gider",
                     confidence=0.9, yontem=yontem, aciklama="")


class FakeClassifier:
    """Rules know 'kira'; the model answers everything else after a delay."""

    def __init__(self) -> None:
        self.model_calls: list[str] = []
        self.in_flight = 0
        self.peak = 0

    def classify(self, description, amount_kurus, transaction_type, vendor=None):
        return _sonuc("770", "kural") if "kira" in description else _sonuc("770", "varsayılan")

    async def async_classify(self, description, amount_kurus, transaction_type, vendor=None):
        if "kira" in description:
            return _sonuc("770", "kural")
        self.model_calls.append(description)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return _sonuc("760" if "reklam" in description else "740", "llm")


def _agent(classifier) -> MuhasebeAgent:
    agent = MuhasebeAgent(classifier=classifier, use_llm_fallback=True, regional_packs=["tr"])
    return agent


def _tx(i: int, desc: str, amount: int = 1000) -> dict:
    return {"id": f"t{i}", "description": desc, "amount_cents": amount, "type": "expense",
            "transaction_date": "2024-01-05"}


@pytest.mark.asyncio
async def test_rows_keep_their_own_result_and_order():
    fake = FakeClassifier()
    txs = [_tx(0, "ofis kira"), _tx(1, "google reklam"), _tx(2, "bilinmeyen"), _tx(3, "ofis kira")]
    sonuclar = await _agent(fake)._siniflandir(txs)
    assert [(r.hesap_kodu, r.yontem) for r in sonuclar] == [
        ("770", "kural"), ("760", "llm"), ("740", "llm"), ("770", "kural")]
    # The rules' rows never reach the model.
    assert sorted(fake.model_calls) == ["bilinmeyen", "google reklam"]


@pytest.mark.asyncio
async def test_same_input_is_asked_once_and_calls_are_bounded():
    fake = FakeClassifier()
    txs = [_tx(i, f"tedarikci {i % 40}") for i in range(400)]
    sonuclar = await _agent(fake)._siniflandir(txs)
    assert len(sonuclar) == 400 and all(r.yontem == "llm" for r in sonuclar)
    assert len(fake.model_calls) == 40
    assert 1 < fake.peak <= _LLM_ESZAMANLI


@pytest.mark.asyncio
async def test_without_the_model_only_rules_run():
    fake = FakeClassifier()
    agent = MuhasebeAgent(classifier=fake, use_llm_fallback=False, regional_packs=["tr"])
    sonuclar = await agent._siniflandir([_tx(0, "bilinmeyen"), _tx(1, "kira")])
    assert [r.yontem for r in sonuclar] == ["varsayılan", "kural"]
    assert fake.model_calls == []


@pytest.mark.asyncio
async def test_the_event_loop_keeps_answering_while_a_large_statement_is_booked():
    """A heartbeat on the loop must not stall behind 6,000 rows of rule matching and booking."""
    agent = MuhasebeAgent(classifier=THPClassifier(), use_llm_fallback=False, regional_packs=["tr"])
    txs = [_tx(i, "Ocak ofis kirası Levent" if i % 2 else "Personel maaş ödemesi", 100_000 + i)
           for i in range(6000)]
    gaps: list[float] = []
    done = asyncio.Event()

    async def heartbeat():
        loop = asyncio.get_running_loop()
        last = loop.time()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = loop.time()
            gaps.append(now - last)
            last = now

    hb = asyncio.create_task(heartbeat())
    sonuc = await agent.run("perf", txs)
    done.set()
    await hb
    assert sonuc.kayit_sayisi == 6000
    # Rows are classified and booked in a thread; the loop only waits on it.
    # Before, the loop never ran once until the whole statement was booked.
    assert gaps, "the event loop did not run at all while the statement was booked"
    assert max(gaps) < 0.5
