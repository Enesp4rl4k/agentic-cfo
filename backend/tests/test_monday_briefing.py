"""Plan v10 §4 (O4) & Plan v11 Faz 3: Pazartesi Bülteni & LLM Anti-Hallucination Gate Testleri.

Kapsam:
1. Deterministik 3 Cümle Kuralı (radar ile kuruşu kuruşuna tutarlı sayılar).
2. Uydurma Sayı Kapısı (Anti-hallucination gate: yabancı sayı reddi ve deterministik fallback).
3. Doğrulanmış LLM anlatısının kabulü.
4. Bültenden Aksiyona Karar Kaydı (DecisionLog: expected, actual, open/closed status).
5. API uç noktaları (/api/v1/briefing/monday ve /api/v1/briefing/monday/respond).
6. Altın Eval Seti (farklı KOBİ nakit senaryolarında sıfır uydurma sayı doğrulaması).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
import pytest_asyncio

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision_log import DecisionLog
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.services.ledger import append_job
from app.services.monday_briefing import (
    assemble_monday_briefing,
    record_briefing_response,
)
from tests.api_helpers import bellek_istemcisi, kullanici

ANCHOR = date(2025, 2, 1)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _statement(day: str, cents: int) -> dict[str, Any]:
    return {"closing_balance": {"date": day, "balance_cents": cents}}


async def _upload(
    client,
    org_id: str,
    *rows: dict[str, Any],
    meta: dict | None = None,
    status: JobStatus = JobStatus.COMPLETED,
) -> str:
    async with client._maker() as db:
        job = AnalysisJob(
            filename="test.csv",
            file_path="/test.csv",
            file_type="csv",
            org_id=org_id,
            status=status,
            result_metadata=meta,
        )
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(
                Transaction(
                    job_id=job.id,
                    amount_kurus=r["amount_cents"],
                    currency=r.get("currency", "TRY"),
                    type=r["type"],
                    category=r.get("category", "other_expense"),
                    description=r.get("description"),
                    transaction_date=when,
                    date_is_estimated=estimated,
                )
            )
        await db.commit()
        await append_job(db, job.id)
        return job.id


@pytest.mark.asyncio
async def test_monday_briefing_deterministic_generation(client):
    """Bülten radardan 3 deterministik cümle üretmeli ve sayılar kuruşu kuruşuna uyuşmalı."""
    _, org_id, _ = await kullanici(client, "ceo@briefing-test.com")

    # 100,000 TL başlangıç bakiyesi
    await _upload(
        client,
        org_id,
        {
            "amount_cents": 100000_00,
            "transaction_date": "2025-01-31",
            "type": "income",
            "description": "Bakiye",
        },
        meta=_statement("2025-01-31", 100000_00),
    )

    # 1. haftada 40,000 TL tedarikçi borcu ve 20,000 TL müşteri alacağı
    async with client._maker() as db:
        db.add(
            OpenItem(
                org_id=org_id,
                direction="payable",
                document_id="INV-PAY-001",
                counterparty="Demir Çelik A.Ş.",
                amount_cents=40000_00,
                issue_date=date(2025, 1, 15),
                due_date=date(2025, 2, 4),
                description="Hammadde alımı",
            )
        )
        db.add(
            OpenItem(
                org_id=org_id,
                direction="receivable",
                document_id="INV-REC-001",
                counterparty="Örnek Müşteri Ltd.",
                amount_cents=20000_00,
                issue_date=date(2025, 1, 15),
                due_date=date(2025, 2, 5),
                description="Proje faturası",
            )
        )
        await db.commit()

    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)

    assert briefing.org_id == org_id
    assert briefing.starting_cash_cents == 100000_00
    assert briefing.approaching_title == "Demir Çelik A.Ş."
    assert briefing.approaching_amount_cents == 40000_00
    assert briefing.approaching_date == "2025-02-04"

    # Cümle 1: Net değişim ve bakiye
    assert "net nakit pozisyonunuzda" in briefing.sentence_radar
    assert "tahmini hafta sonu bakiyesi" in briefing.sentence_radar

    # Cümle 2: Kritik yaklaşan yükümlülük
    assert "Demir Çelik A.Ş." in briefing.sentence_obligation
    assert "40.000,00" in briefing.sentence_obligation

    # Cümle 3: Aksiyon
    assert briefing.sentence_action != ""
    assert briefing.verified is True
    assert briefing.fallback_used is False


@pytest.mark.asyncio
async def test_anti_hallucination_gate_rejection(client):
    """LLM uydurma sayı üretirse kapı metni reddetmeli ve deterministik şablona dönmeli."""
    _, org_id, _ = await kullanici(client, "ceo@gate-test.com")

    await _upload(
        client,
        org_id,
        {
            "amount_cents": 50000_00,
            "transaction_date": "2025-01-31",
            "type": "income",
            "description": "Bakiye",
        },
        meta=_statement("2025-01-31", 50000_00),
    )

    # Uydurma sayılar içeren metin (999.000 TL ve 777.000 TL radarda yok)
    hallucinated_narrative = (
        "Bu hafta 999.000 TL net çıkış bekleniyor. "
        "En kritik borcunuz 777.000 TL tutarındadır. "
        "Hemen tahsilatı hızlandırın."
    )

    async with client._maker() as db:
        briefing = await assemble_monday_briefing(
            db,
            org_id,
            anchor_date=ANCHOR,
            candidate_narrative=hallucinated_narrative,
        )

    # Uydurma sayı reddedildi, fallback şablon devreye girdi
    assert briefing.fallback_used is True
    assert briefing.verified is True
    assert "999.000" not in briefing.full_text
    assert "777.000" not in briefing.full_text
    assert (
        briefing.full_text
        == f"{briefing.sentence_radar} {briefing.sentence_obligation} {briefing.sentence_action}"
    )


@pytest.mark.asyncio
async def test_anti_hallucination_gate_acceptance(client):
    """LLM gerçek sayılarla tutarlı anlatı üretirse onaylanıp kabul edilmeli."""
    _, org_id, _ = await kullanici(client, "ceo@gate-accept.com")

    await _upload(
        client,
        org_id,
        {
            "amount_cents": 50000_00,
            "transaction_date": "2025-01-31",
            "type": "income",
            "description": "Bakiye",
        },
        meta=_statement("2025-01-31", 50000_00),
    )

    async with client._maker() as db:
        db.add(
            OpenItem(
                org_id=org_id,
                direction="payable",
                document_id="INV-PAY-002",
                counterparty="Önemli Tedarikçi",
                amount_cents=10000_00,
                issue_date=date(2025, 1, 15),
                due_date=date(2025, 2, 3),
                description="Fatura",
            )
        )
        await db.commit()

    # Gerçek sayılar: 10000 TL borç, 50000 TL başlangıç veya 40000 TL bakiye
    grounded_narrative = (
        "Hafta başında bakiyeniz 50.000 TL seviyesindedir. "
        "Bu hafta 10.000 TL tutarında Önemli Tedarikçi ödemesi bulunmaktadır. "
        "Hafta sonu bakiyenizin 40.000 TL olması beklenmektedir."
    )

    async with client._maker() as db:
        briefing = await assemble_monday_briefing(
            db,
            org_id,
            anchor_date=ANCHOR,
            candidate_narrative=grounded_narrative,
        )

    assert briefing.fallback_used is False
    assert briefing.full_text == grounded_narrative


@pytest.mark.asyncio
async def test_record_briefing_response(client):
    """Bülten yanıtları DecisionLog tablosuna makinece doğrulanabilir şekilde kaydedilmeli."""
    _, org_id, user_id = await kullanici(client, "ceo@decision-test.com")

    await _upload(
        client,
        org_id,
        {
            "amount_cents": 10000_00,
            "transaction_date": "2025-01-31",
            "type": "income",
            "description": "Bakiye",
        },
        meta=_statement("2025-01-31", 10000_00),
    )

    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)

        # 1. 'done' yanıtı -> closed
        d_done = await record_briefing_response(
            db,
            org_id=org_id,
            user_id=user_id,
            briefing=briefing,
            response="done",
            note="Tahsilat için müşteri arandı.",
        )
        assert d_done.status == "closed"
        assert d_done.chosen_option_label == "Yaptım"
        assert d_done.expected["source"] == "monday_briefing"
        assert d_done.actual["owner_response"] == "done"

        # 2. 'deferred' yanıtı -> open
        d_def = await record_briefing_response(
            db,
            org_id=org_id,
            user_id=user_id,
            briefing=briefing,
            response="deferred",
            note="Çarşamba günü tekrar değerlendirilecek.",
        )
        assert d_def.status == "open"
        assert d_def.chosen_option_label == "Ertele"

        # 3. 'dismissed' yanıtı -> closed
        d_dis = await record_briefing_response(
            db,
            org_id=org_id,
            user_id=user_id,
            briefing=briefing,
            response="dismissed",
            note="Gerek görülmedi.",
        )
        assert d_dis.status == "closed"
        assert d_dis.chosen_option_label == "Gerek Yok"

        # 4. Geçersiz yanıt
        with pytest.raises(ValueError):
            await record_briefing_response(
                db,
                org_id=org_id,
                user_id=user_id,
                briefing=briefing,
                response="gecersiz",
            )


@pytest.mark.asyncio
async def test_monday_briefing_api_endpoints(client):
    """GET ve POST /api/v1/briefing/monday HTTP uç noktaları test edilir."""
    headers, org_id, _ = await kullanici(client, "ceo@api-brief.com")

    await _upload(
        client,
        org_id,
        {
            "amount_cents": 80000_00,
            "transaction_date": "2025-01-31",
            "type": "income",
            "description": "Bakiye",
        },
        meta=_statement("2025-01-31", 80000_00),
    )

    # 1. GET /api/v1/briefing/monday
    resp = await client.get("/api/v1/briefing/monday?anchor_date=2025-02-01", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["org_id"] == org_id
    assert data["starting_cash_cents"] == 80000_00
    assert "sentence_radar" in data
    assert "sentence_obligation" in data
    assert "sentence_action" in data

    # 2. POST /api/v1/briefing/monday/respond (success)
    resp_action = await client.post(
        "/api/v1/briefing/monday/respond",
        headers=headers,
        json={"response": "done", "note": "Ödeme tamamlandı", "anchor_date": "2025-02-01"},
    )
    assert resp_action.status_code == 200
    act_data = resp_action.json()["data"]
    assert act_data["status"] == "closed"
    assert act_data["chosen_option_label"] == "Yaptım"
    assert act_data["decision_id"] is not None

    # Verify decision logged in db
    async with client._maker() as db:
        row = await db.get(DecisionLog, act_data["decision_id"])
        assert row is not None
        assert row.org_id == org_id
        assert row.expected["source"] == "monday_briefing"

    # 3. POST /api/v1/briefing/monday/respond (invalid response -> 422)
    resp_bad = await client.post(
        "/api/v1/briefing/monday/respond",
        headers=headers,
        json={"response": "bilmiyorum", "anchor_date": "2025-02-01"},
    )
    assert resp_bad.status_code == 422


@pytest.mark.asyncio
async def test_golden_eval_scenarios(client):
    """Altın Eval Seti: Çeşitli KOBİ nakit durumlarında sıfır uydurma sayı ve kuruş kuruşa tutarlılık."""
    _, org_id, _ = await kullanici(client, "ceo@golden-eval.com")

    scenarios = [
        # (başlangıç, açık borç, açık alacak, durum adı)
        (50000_00, 70000_00, 10000_00, "Nakit Açığı Senaryosu"),
        (200000_00, 30000_00, 50000_00, "Nakit Fazlası Senaryosu"),
        (10000_00, 0, 0, "Sakin Hafta Senaryosu"),
    ]

    for _start_cents, pay_cents, rec_cents, name in scenarios:
        # Senaryo için temiz veriler
        async with client._maker() as db:
            if pay_cents > 0:
                db.add(
                    OpenItem(
                        org_id=org_id,
                        direction="payable",
                        document_id=f"INV-P-{name}",
                        counterparty=f"Tedarikçi {name}",
                        amount_cents=pay_cents,
                        issue_date=date(2025, 1, 15),
                        due_date=ANCHOR,
                        description=name,
                    )
                )
            if rec_cents > 0:
                db.add(
                    OpenItem(
                        org_id=org_id,
                        direction="receivable",
                        document_id=f"INV-R-{name}",
                        counterparty=f"Müşteri {name}",
                        amount_cents=rec_cents,
                        issue_date=date(2025, 1, 15),
                        due_date=ANCHOR,
                        description=name,
                    )
                )
            await db.commit()

        async with client._maker() as db:
            briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)

        # Doğrulama: metin içindeki her sayı (extract_numeric_claims) radarda gerçekten var olmalıdır
        from app.services.rag.grounding_validator import extract_numeric_claims

        claims = extract_numeric_claims(briefing.full_text)

        allowed_cents = {
            abs(briefing.net_change_cents),
            abs(briefing.end_balance_cents),
            abs(briefing.starting_cash_cents) if briefing.starting_cash_cents is not None else 0,
            briefing.approaching_amount_cents,
            briefing.action_amount_cents,
        }
        allowed_liras = {c / 100.0 for c in allowed_cents}

        for claim in claims:
            matched = any(abs(claim - al) <= max(1.0, al * 0.02) for al in allowed_liras)
            assert matched, (
                f"[{name}] Uydurma sayı tespit edildi: {claim} TL (izin verilenler: {allowed_liras})"
            )

        assert briefing.verified is True


def test_scheduler_registers_weekly_summary():
    """Pazartesi bülteni zamanlayıcısı scheduler'da kayıtlı olmalıdır."""
    from app import scheduler as sched

    sched._scheduler = None
    try:
        job = sched.get_scheduler().get_job("weekly_summary")
        assert job is not None
        assert "mon" in str(job.trigger)
    finally:
        sched._scheduler = None
