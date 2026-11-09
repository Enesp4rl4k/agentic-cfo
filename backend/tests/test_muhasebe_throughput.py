"""Booking a large statement: the model is asked only where the rules failed, in parallel, once per input."""
from __future__ import annotations

import asyncio
import threading

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


class ThreadRecordingClassifier(THPClassifier):
    """The real rules, noting which threads ran them."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: set[int] = set()

    def classify(self, *args, **kwargs):
        self.threads.add(threading.get_ident())
        return super().classify(*args, **kwargs)


@pytest.mark.asyncio
async def test_a_large_statement_is_classified_off_the_event_loop_thread():
    """6,000 rows of rule matching must not run on the thread that serves requests.

    This used to be a timing test: a heartbeat on the loop, judged by its longest pause.
    Under a loaded CI runner, GIL contention with the booking thread made single pauses
    of 0.5-0.9 s while the loop kept answering, so the bound failed at random (twice, the
    second time by 0.016 s). What matters is where the work runs, which does not depend
    on how busy the machine is: rows are classified in a worker thread and the loop only
    waits on it. Run inline, the rules would execute on the loop's own thread.
    """
    classifier = ThreadRecordingClassifier()
    agent = MuhasebeAgent(classifier=classifier, use_llm_fallback=False, regional_packs=["tr"])
    txs = [_tx(i, "Ocak ofis kirası Levent" if i % 2 else "Personel maaş ödemesi", 100_000 + i)
           for i in range(6000)]

    loop_thread = threading.get_ident()
    sonuc = await agent.run("perf", txs)

    assert sonuc.kayit_sayisi == 6000
    assert classifier.threads, "the rules never ran"
    assert loop_thread not in classifier.threads, "the rules ran on the event loop's own thread"
