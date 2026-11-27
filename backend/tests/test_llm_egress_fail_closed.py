"""Masked mode fails closed, visibly; every consumer that parses model output restores AFTER parsing and never
writes a placeholder into the books.

Fail closed: no company context, or a names dictionary that cannot be read completely -> no outbound request,
the caller's honest "AI step unavailable" path, an audit row with the reason, an operator alert, a count on the
owner's card. The system-job allow-list is explicit (and empty today).

Consumers of model output as data (found by grepping json.loads / schema parses over agents and services):
  data_ingestion._extract_transactions_with_llm  JSON array -> transactions (books): strict restore
  nl_query_engine.generate_nl_insight            JSON object -> answer text: narrative restore
  nl_query_engine.generate_nl_insight_stream     text stream + follow-ups JSON: never crashes on a quoted name
  thp_classifier._llm_siniflandir                first token must be a known THP code: a placeholder never is
  llm_structured._structured / boardroom         pydantic narratives: restored field by field after parsing
  reasoning_loop (_think/_plan)                  parses router text, but never reaches a model (TypeError on
                                                 `max_tokens`, a separate product bug left as it is: reported)
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from app.platform import model_gateway as mg
from app.platform.llm_egress import refusals
from app.platform.llm_egress.system_calls import SYSTEM_CALLS
from tests.llm_egress_harness import CANARY, Recorder, leaked_in, open_world

TOKEN = re.compile(r"\[\[[A-Z]+_[A-Z0-9]{3}_\d+[a-z]?\]\]")


def test_the_system_call_allow_list_is_explicit_and_justified() -> None:
    from tests.llm_egress_discovery import discover

    assert isinstance(SYSTEM_CALLS, dict)
    for task, reason in SYSTEM_CALLS.items():
        assert len(reason) >= 40, f"{task}: say why this call carries no tenant data"
    assert len(discover()) >= 40  # the review behind the (empty) list covered every call site


async def test_a_refusal_is_recorded_with_its_reason_and_raises_the_honest_unavailable(monkeypatch) -> None:
    from app.platform.llm_egress import audit

    rows: list[dict] = []
    async with open_world(monkeypatch) as env:
        monkeypatch.setattr(audit, "persist_call_log", lambda **kw: rows.append(kw))
        with pytest.raises(mg.LLMUnavailable) as err:  # the exception every caller already handles
            await mg.complete_text(task="anomaly_narrative", prompt=f"{CANARY.counterparty} 1.000,00 TL")
        assert env.rec.count() == 0
    assert isinstance(err.value, mg.LLMEgressRefused) and err.value.reason == "no_organisation_context"
    assert rows[0]["error"] == "egress_refused:no_organisation_context" and rows[0]["task"] == "anomaly_narrative"
    assert rows[0]["data_mode"] == "masked" and rows[0]["ok"] is False


async def test_the_api_says_why_nothing_was_sent() -> None:
    from starlette.requests import Request

    from app.main import llm_unavailable_handler

    request = Request({"type": "http", "method": "POST", "path": "/api/v1/chat/ceo", "headers": [], "query_string": b""})
    response = await llm_unavailable_handler(request, mg.LLMEgressRefused(refusals.MESSAGES["dictionary_unavailable"],
                                                                          "dictionary_unavailable"))
    body = json.loads(response.body)
    assert response.status_code == 503 and "gönderilmedi" in json.dumps(body, ensure_ascii=False)
    assert "llm_egress_refused" in json.dumps(body)


async def test_operators_are_alerted_about_refusals(monkeypatch) -> None:
    from app.models.llm_call_log import LLMCallLog
    from app.services import operator_alerts, ops_watch

    raised: list[tuple] = []

    async def fake_alert(db, code, *, dedupe="", detail="", now=None):
        raised.append((code, detail))
        return 1

    monkeypatch.setattr(operator_alerts, "raise_alert", fake_alert)
    async with open_world(monkeypatch) as env:
        now = datetime.now(UTC)
        async with env.maker() as db:
            assert await ops_watch._llm_egress_refusals(db, now) == 0
            db.add(LLMCallLog(org_id=env.org_id, task_type="chat", model="-", ok=False, bytes_out=0, data_mode="masked",
                              error="egress_refused:no_organisation_context", created_at=now - timedelta(hours=1)))
            await db.commit()
            assert await ops_watch._llm_egress_refusals(db, now) == 1
    assert raised == [("llm_egress_refused", "no_organisation_context=1")]
    assert "llm_egress_refused" in operator_alerts.ALERTS


async def test_the_review_continuation_runs_its_ai_steps_for_the_jobs_company(monkeypatch) -> None:
    """The defect the review found: approved jobs continued without a company, so names went out unmasked."""
    from app.core.tenancy import get_current_tenant
    from tests.llm_egress_entries import _review

    seen: list[str | None] = []

    async def driver(env) -> None:
        seen.append(get_current_tenant())

    async with open_world(monkeypatch) as env:
        await _review(env, driver, monkeypatch)
        assert seen == [env.org_id]


# ── consumers that parse model output ────────────────────────────────────────

async def test_data_ingestion_never_books_a_placeholder_and_keeps_a_quoted_name(monkeypatch) -> None:
    from app.agents.data_ingestion import _extract_transactions_with_llm
    from app.config import get_settings

    def reply(texts: list[str]) -> str:
        known = TOKEN.findall("\n".join(texts))
        cp = next(t for t in known if t.startswith("[[CP_"))
        return json.dumps([
            {"date": "15.03.2026", "amount": 1500.0, "type": "expense", "description": f"FAST {cp}", "vendor": cp,
             "confidence": 0.9},
            {"date": "16.03.2026", "amount": 99.5, "type": "expense", "description": "x", "vendor": "[[CP_ZZZ_4]]",
             "confidence": 0.95},
        ], ensure_ascii=True)

    async with open_world(monkeypatch, Recorder(reply=reply), tenant=True) as env:
        rows = await _extract_transactions_with_llm(f"15.03.2026 {CANARY.counterparty} 1.500,00 TL", get_settings())
        assert leaked_in(env.rec.text()) == []
    assert rows[0]["vendor"] == CANARY.counterparty and rows[0]["amount"] == 1500.0
    assert rows[1]["vendor"] is None and rows[1]["__unresolved__"] == ["vendor"]


async def test_an_unresolved_row_is_held_as_unreadable_not_booked() -> None:
    from app.services.ingest.hold import row_reasons

    row = {"amount_cents": 9950, "currency": "TRY", "type": "expense", "transaction_date": "2026-03-16",
           "confidence": 0.55, "line_unreadable": True, "vendor": None, "description": ""}
    assert row_reasons(row)  # held for a person


async def test_nl_insight_parses_before_restoring_a_name_with_quotes(monkeypatch) -> None:
    from app.agents import nl_query_engine
    from app.models.open_item import OpenItem

    quoted = 'Usta "Gıda" Ltd. Şti.'

    def reply(texts: list[str]) -> str:
        cp = TOKEN.findall("\n".join(texts))[0]
        return json.dumps({"answer": f"{cp} borcu 1.500,00 TL.", "follow_ups": [f"{cp} ne zaman öder?"]})

    async with open_world(monkeypatch, Recorder(reply=reply), tenant=True) as env:
        async with env.maker() as db:
            from datetime import date

            db.add(OpenItem(org_id=env.org_id, direction="payable", instrument="invoice", document_id="inv:q:2",
                            counterparty=quoted, amount_cents=150000, issue_date=date(2026, 3, 1)))
            await db.commit()
        out = await nl_query_engine.generate_nl_insight(
            f"{quoted} borcu ne kadar?", {"intent": "payables", "value": 1500, "context": {}},
            {"pnl": {"revenue": 1, "net_income": 1, "net_margin": 0.1}, "cashflow": {"net_change": 1}}, [], None,
        )
    assert out["answer"] == f"{quoted} borcu 1.500,00 TL." and out["follow_ups"] == [f"{quoted} ne zaman öder?"]


async def test_the_thp_classifier_never_takes_a_placeholder_for_an_account(monkeypatch) -> None:
    from app.services.accounting.thp_classifier import _llm_siniflandir

    async with open_world(monkeypatch, Recorder(reply="[[CP_ZZZ_1]]"), tenant=True):
        assert await _llm_siniflandir(f"{CANARY.counterparty} ödemesi", CANARY.vendor, "expense", 150000) is None
    async with open_world(monkeypatch, Recorder(reply="770"), tenant=True):
        assert await _llm_siniflandir(f"{CANARY.counterparty} ödemesi", CANARY.vendor, "expense", 150000) == ("770", 0.75)


async def test_the_nl_stream_survives_a_restored_name_inside_its_follow_up_json(monkeypatch) -> None:
    from app.agents import nl_query_engine
    from app.models.open_item import OpenItem

    quoted = 'Usta "Gıda" Ltd. Şti.'

    def reply(texts: list[str]) -> str:
        cp = TOKEN.findall("\n".join(texts))[0]
        return f'{cp} borcu 1.500,00 TL.\n{{"follow_ups": ["{cp} ne zaman öder?"]}}'

    async with open_world(monkeypatch, Recorder(reply=reply), tenant=True) as env:
        async with env.maker() as db:
            from datetime import date

            db.add(OpenItem(org_id=env.org_id, direction="payable", instrument="invoice", document_id="inv:q:3",
                            counterparty=quoted, amount_cents=150000, issue_date=date(2026, 3, 1)))
            await db.commit()
        pieces = [p async for p in nl_query_engine.generate_nl_insight_stream(
            f"{quoted} borcu?", {"intent": "payables", "value": 1500, "context": {}},
            {"pnl": {"revenue": 1, "net_income": 1, "net_margin": 0.1}, "cashflow": {"net_change": 1}}, None,
        )]
    text = "".join(p for p in pieces if not p.startswith("\x00"))
    assert f"{quoted} borcu 1.500,00 TL." in text and "[[" not in text
    assert any(p.startswith("\x00FOLLOW_UPS:") for p in pieces)   # degrades to [] if the JSON broke; never crashes
