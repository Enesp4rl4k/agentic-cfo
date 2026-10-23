"""Plan v5 §F0 — a user's category corrections are applied, everywhere.

`classifier.learn()` saved every correction as a CategoryRule, and nothing ever
applied one: no ingest path called `classify()`. A user corrected the same
vendor every month. These tests pin the loop closed:

- the matcher (vendor in its field or in the description, keywords, folded
  diacritics, vendor before keyword),
- only "apply always" rules are standing rules,
- the ingestion node applies them before P&L reads a category,
- the worker hands the pipeline the org and its rules, stores where each
  category came from, and counts the hits with the rows,
- a standing correction reports which finished analyses it changes, and a
  finished analysis can be recomputed — unless its SMMM packet is sealed,
- every ingest seam (pipeline, scheduled sync) applies the rules.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app.services.classifier import (
    USER_RULE,
    RuleSpec,
    apply_rules,
    load_rules,
    match_rule,
    rules_from_state,
    rules_to_state,
)
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

TURKCELL = RuleSpec(id="r1", category="utilities", vendor="Turkcell İletişim")
KIRA = RuleSpec(id="r2", category="rent", keyword="ofis kirası")


# ── matcher ───────────────────────────────────────────────────────────────────


def test_vendor_rule_matches_the_vendor_field():
    assert match_rule([TURKCELL], vendor="Turkcell İletişim A.Ş.", description="") == TURKCELL


def test_vendor_rule_matches_a_bank_line_that_names_the_vendor():
    """Bank statements put the counterparty in the description, not a field."""
    hit = match_rule([TURKCELL], vendor=None, description="EFT TURKCELL ILETISIM FATURA")
    assert hit == TURKCELL


def test_keyword_rule_and_folded_diacritics():
    assert match_rule([KIRA], vendor=None, description="Ekim OFIS KIRASI odemesi") == KIRA


def test_vendor_rule_wins_over_keyword_rule():
    both = [KIRA, TURKCELL]
    hit = match_rule(both, vendor="Turkcell İletişim", description="ofis kirası turkcell")
    assert hit == TURKCELL


def test_a_vendor_rule_does_not_match_a_partial_name():
    """"Turkcell İletişim" must not swallow every line that merely says Turkcell."""
    assert match_rule([TURKCELL], vendor=None, description="TURKCELL FATURA") is None


def test_no_match_leaves_the_row_alone():
    rows = [{"category": "other_expense", "vendor": "Migros", "description": "market"}]
    assert not apply_rules(rows, [TURKCELL, KIRA])
    assert rows[0] == {"category": "other_expense", "vendor": "Migros", "description": "market"}


def test_apply_rules_overwrites_marks_and_counts():
    rows = [
        {"category": "other_expense", "vendor": None, "description": "TURKCELL ILETISIM FATURA"},
        {"category": "other_expense", "vendor": "Turkcell İletişim", "description": ""},
        {"category": "other_expense", "vendor": None, "description": "ofis kirası"},
    ]
    hits = apply_rules(rows, [TURKCELL, KIRA])
    assert [r["category"] for r in rows] == ["utilities", "utilities", "rent"]
    assert all(r["category_source"] == USER_RULE for r in rows)
    assert hits == {"r1": 2, "r2": 1}


def test_rules_round_trip_through_the_agent_state():
    assert rules_from_state(rules_to_state([TURKCELL, KIRA])) == [TURKCELL, KIRA]


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        yield c, tmp_path
        await arka_plan_bitsin()


async def _rule(db, org_id: str, *, vendor: str, category: str, always: bool = True):
    from app.models.category_rule import CategoryRule

    rule = CategoryRule(org_id=org_id, vendor_match=vendor, category=category,
                        apply_always=always, hit_count=1)
    db.add(rule)
    await db.commit()
    return rule


async def _job(db, org_id: str, tmp_path: Path, *, status: str = "completed",
               rows: list[tuple[str, str]] = ()) -> str:
    from datetime import UTC, datetime

    from app.models.analysis_job import AnalysisJob
    from app.models.transaction import Transaction

    f = tmp_path / f"ekstre-{len(list(tmp_path.iterdir()))}.csv"
    f.write_text("tarih,aciklama,tutar\n2026-08-01,Tahsilat,1000\n", encoding="utf-8")
    job = AnalysisJob(filename=f.name, file_path=str(f), file_type="csv",
                      org_id=org_id, status=status)
    db.add(job)
    await db.flush()
    for vendor, category in rows:
        db.add(Transaction(job_id=job.id, amount_kurus=10_000, currency="TRY",
                           type="expense", category=category, vendor=vendor,
                           description=f"{vendor} fatura",
                           transaction_date=datetime(2026, 8, 1, tzinfo=UTC)))
    await db.commit()
    return job.id


# ── standing rules only ───────────────────────────────────────────────────────


async def test_only_apply_always_rules_are_standing_rules(ortam):
    client, _ = ortam
    _, org_id, _ = await kullanici(client, "kural@example.com")
    async with client._maker() as db:
        await _rule(db, org_id, vendor="Turkcell", category="utilities", always=True)
        await _rule(db, org_id, vendor="Migros", category="cogs", always=False)
        rules = await load_rules(org_id, db)
        other = await load_rules("baska-org", db)
    assert [r.vendor for r in rules] == ["Turkcell"]
    assert other == []


# ── pipeline node ─────────────────────────────────────────────────────────────


async def test_ingestion_node_applies_rules_before_downstream(monkeypatch):
    from app.agents import orchestrator

    class _Sonuc:
        ok = True
        detail = "ok"
        confidence = 0.95
        needs_review = False
        patch = {"transactions": [
            {"category": "other_expense", "vendor": None,
             "description": "TURKCELL ILETISIM FATURA", "amount_cents": 100, "type": "expense"},
        ]}

    async def sahte(state, cfg):
        return _Sonuc()

    monkeypatch.setattr(orchestrator, "run_data_ingestion", sahte)
    state: dict[str, Any] = {"logs": [], "category_rules": rules_to_state([TURKCELL])}
    patch = await orchestrator.node_data_ingestion(state, {})

    assert patch["transactions"][0]["category"] == "utilities"
    assert patch["transactions"][0]["category_source"] == USER_RULE
    assert patch["category_rule_hits"] == {"r1": 1}


# ── worker ────────────────────────────────────────────────────────────────────


async def test_worker_passes_org_and_rules_and_records_source_and_hits(ortam, monkeypatch):
    from app.models.category_rule import CategoryRule
    from app.models.transaction import Transaction
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    _, org_id, _ = await kullanici(client, "isci-kural@example.com")
    async with client._maker() as db:
        rule = await _rule(db, org_id, vendor="Turkcell", category="utilities")
        rule_id = rule.id
        job_id = await _job(db, org_id, tmp_path, status="pending")

    alinan: list[dict[str, Any]] = []

    async def sahte(**kw: Any) -> dict[str, Any]:
        alinan.append(kw)
        return {
            "transactions": [{"amount_cents": 50_00, "type": "expense",
                              "category": "utilities", "category_source": USER_RULE,
                              "vendor": "Turkcell", "description": "Turkcell fatura",
                              "transaction_date": "2026-08-01"}],
            "dashboard_json": {"pnl": {"revenue": 0}},
            "anomalies": [], "logs": [],
            "category_rule_hits": {rule_id: 1},
            "awaiting_review": False, "min_confidence": 0.95,
        }

    monkeypatch.setattr("app.agents.orchestrator.run_cfo_pipeline", sahte)
    sonuc = await run_cfo_analysis({}, job_id)

    assert sonuc.get("ok") is True, sonuc
    assert alinan[0]["org_id"] == org_id  # was never passed before §F0
    assert [r["vendor"] for r in alinan[0]["category_rules"]] == ["Turkcell"]
    async with client._maker() as db:
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalar_one()
        assert tx.category == "utilities"
        assert tx.category_source == USER_RULE
        assert (await db.get(CategoryRule, rule_id)).hit_count == 2


# ── corrections → affected analyses ───────────────────────────────────────────


async def test_standing_correction_reports_the_analyses_it_changes(ortam):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "duzelt@example.com")
    async with client._maker() as db:
        job_a = await _job(db, org_id, tmp_path, rows=[("Turkcell", "other_expense"),
                                                      ("Turkcell", "other_expense")])
        job_b = await _job(db, org_id, tmp_path, rows=[("TURKCELL", "other_expense")])
        job_c = await _job(db, org_id, tmp_path, rows=[("Migros", "other_expense")])
        from app.models.transaction import Transaction
        tx_id = (await db.execute(
            select(Transaction.id).where(Transaction.job_id == job_a).limit(1)
        )).scalar_one()

    res = await client.patch(f"/api/v1/transactions/{tx_id}/category", headers=headers,
                             json={"category": "utilities", "apply_always": True})
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data["affected_job_ids"]) == {job_a, job_b}
    assert job_c not in data["affected_job_ids"]

    async with client._maker() as db:
        from app.models.transaction import Transaction
        edited = await db.get(Transaction, tx_id)
        assert edited.category == "utilities"
        assert edited.category_source == "user_edit"


async def test_one_off_correction_changes_nothing_else(ortam):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "tek@example.com")
    async with client._maker() as db:
        job_a = await _job(db, org_id, tmp_path, rows=[("Turkcell", "other_expense")])
        await _job(db, org_id, tmp_path, rows=[("Turkcell", "other_expense")])
        from app.models.transaction import Transaction
        tx_id = (await db.execute(
            select(Transaction.id).where(Transaction.job_id == job_a)
        )).scalar_one()

    res = await client.patch(f"/api/v1/transactions/{tx_id}/category", headers=headers,
                             json={"category": "utilities", "apply_always": False})
    assert res.json()["data"]["affected_job_ids"] == []
    async with client._maker() as db:
        assert await load_rules(org_id, db) == []


# ── rerun ─────────────────────────────────────────────────────────────────────


async def test_rerun_reopens_a_finished_analysis_and_enqueues(ortam, monkeypatch):
    from app.models.analysis_job import AnalysisJob

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "yeniden@example.com")
    async with client._maker() as db:
        job_id = await _job(db, org_id, tmp_path, status="completed")
    queued: list[str] = []

    async def kuyruk(jid, budget=None):
        queued.append(jid)

    monkeypatch.setattr("app.worker.enqueue_analysis", kuyruk)
    res = await client.post(f"/api/v1/analysis/{job_id}/rerun", headers=headers)

    assert res.status_code == 200, res.text
    assert queued == [job_id]
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, job_id)).status == "pending"


async def test_rerun_refuses_a_job_under_review(ortam, monkeypatch):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "inceleme@example.com")
    async with client._maker() as db:
        job_id = await _job(db, org_id, tmp_path, status="awaiting_review")
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda *a, **k: None)

    res = await client.post(f"/api/v1/analysis/{job_id}/rerun", headers=headers)
    assert res.status_code == 409


async def test_rerun_refuses_a_job_with_a_sealed_smmm_packet(ortam, monkeypatch):
    from app.models.defensibility_packet import DefensibilityPacket

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "muhur@example.com")
    async with client._maker() as db:
        job_id = await _job(db, org_id, tmp_path, status="completed")
        db.add(DefensibilityPacket(org_id=org_id, job_id=job_id, status="finalized"))
        await db.commit()
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda *a, **k: None)

    res = await client.post(f"/api/v1/analysis/{job_id}/rerun", headers=headers)
    assert res.status_code == 409


async def test_rerun_is_owner_scoped(ortam, monkeypatch):
    client, tmp_path = ortam
    _, org_a, _ = await kullanici(client, "sahip@example.com")
    headers_b, _, _ = await kullanici(client, "yabanci@example.com")
    async with client._maker() as db:
        job_id = await _job(db, org_a, tmp_path, status="completed")
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda *a, **k: None)

    res = await client.post(f"/api/v1/analysis/{job_id}/rerun", headers=headers_b)
    assert res.status_code in (403, 404)


# ── every ingest seam applies the rules ───────────────────────────────────────


def test_every_ingest_seam_applies_user_rules():
    """File, e-mail, Paraşüt and ERP-CSV ingests all reach the pipeline through
    the worker; scheduled ERP syncs write canonical rows directly. Both seams
    must apply the org's rules — a new seam without them is the old bug."""
    root = Path(__file__).resolve().parents[1] / "app"
    worker = (root / "worker.py").read_text(encoding="utf-8")
    assert "load_rules(" in worker and "category_rules=category_rules" in worker
    assert "org_id=org_id_str" in worker

    orchestrator = (root / "agents" / "orchestrator.py").read_text(encoding="utf-8")
    assert "apply_rules(patch[\"transactions\"]" in orchestrator

    sync = (root / "services" / "scheduled_sync.py").read_text(encoding="utf-8")
    apply_at = sync.index("apply_rules(")
    insert_at = sync.index("CanonicalTransaction(**row_data)")
    assert apply_at < insert_at, "rules must apply before canonical rows are written"
