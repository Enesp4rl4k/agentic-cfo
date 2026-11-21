"""The morning brief states figures from one source and checks every number.

Before: revenue was summed over up to ten per-upload P&Ls (overlapping uploads counted
twice), a missing net margin became 0, and the LLM text was never checked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import update

from app.models.analysis_job import AnalysisJob
from app.services import morning_brief
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

ROW = {"amount_cents": 40_000_00, "transaction_date": "2025-01-20", "type": "income",
       "category": "sales", "description": "Satış", "document_id": "F-1"}


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


class _Store:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value


async def _run_brief(client, monkeypatch, org_id: str, llm) -> dict:
    import app.database as database
    import app.platform.model_gateway as gateway
    import app.worker as worker
    from app import scheduler

    store = _Store()

    async def pool():
        return store

    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr(database, "get_session_factory", lambda _e: client._maker)
    monkeypatch.setattr(worker, "get_arq_pool", pool)
    monkeypatch.setattr(gateway, "complete_text", llm)
    async with client._maker() as db:  # the scheduler looks at the last 24 hours
        await db.execute(update(AnalysisJob).values(completed_at=datetime.now(UTC)))
        await db.commit()
    await scheduler._generate_morning_brief_for_org(org_id)
    return json.loads(store.values[scheduler.morning_brief_key(org_id)])


async def _no_llm(**_kw: object) -> str:
    raise RuntimeError("no key")


@pytest.mark.asyncio
async def test_overlapping_uploads_are_not_counted_twice(client, monkeypatch):
    _, org_id, _ = await kullanici(client, "a@morning.com")
    await upload(client, org_id, ROW, meta=statement("2025-01-31", 90_000_00))
    await upload(client, org_id, ROW)  # the same invoice again, in a second upload
    brief = await _run_brief(client, monkeypatch, org_id, _no_llm)
    assert "₺40.000,00 gelir" in brief["brief"]
    assert "₺80.000,00" not in brief["brief"]
    assert "%" not in brief["brief"]  # no margin defaulted to 0
    assert "tarihli verilere göre" in brief["brief"]
    assert brief["figures_source"] == "ledger+radar" and brief["narrative"] == "template"


@pytest.mark.asyncio
async def test_an_unknown_figure_is_left_out_not_written_as_zero(client, monkeypatch):
    _, org_id, _ = await kullanici(client, "b@morning.com")
    await upload(client, org_id)  # a completed upload with no rows and no statement
    brief = await _run_brief(client, monkeypatch, org_id, _no_llm)
    assert "gelir" not in brief["brief"] and "Banka bakiyesi" not in brief["brief"]
    assert "₺0,00" not in brief["brief"]


@pytest.mark.asyncio
async def test_a_narrative_with_an_invented_number_is_replaced_by_the_template(client, monkeypatch):
    _, org_id, _ = await kullanici(client, "c@morning.com")
    await upload(client, org_id, ROW, meta=statement("2025-01-31", 90_000_00))

    async def liar(**_kw: object) -> str:
        return "Cironuz ₺999.999,00 oldu, harika."

    brief = await _run_brief(client, monkeypatch, org_id, liar)
    assert "999.999" not in brief["brief"]
    assert brief["narrative"] == "template"


@pytest.mark.asyncio
async def test_a_narrative_of_known_numbers_is_kept_and_dated(client, monkeypatch):
    _, org_id, _ = await kullanici(client, "d@morning.com")
    await upload(client, org_id, ROW, meta=statement("2025-01-31", 90_000_00))

    async def honest(**_kw: object) -> str:
        return "Defterde ₺40.000,00 gelir var; banka bakiyesi ₺90.000,00."

    brief = await _run_brief(client, monkeypatch, org_id, honest)
    assert brief["narrative"] == "llm"
    assert brief["brief"].startswith("Defterde ₺40.000,00 gelir var")
    assert "tarihli verilere göre" in brief["brief"]


def test_the_verifier_accepts_only_facts():
    facts = morning_brief.MorningFacts(
        data_date="2025-02-03", job_count=2, critical_count=1, high_count=0,
        revenue_cents=40_000_00, expense_cents=10_000_00,
    )
    assert morning_brief.accept_narrative("Gelir ₺40.000,00, kâr ₺30.000,00.", facts)
    assert morning_brief.accept_narrative("Marj %75 oldu.", facts) is None
    assert morning_brief.accept_narrative("", facts) is None
