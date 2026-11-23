"""Retention: conservative, idempotent, dry-run first, one organisation at a time; and the notice acceptance hooks."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.config import get_settings
from app.database import Base
from app.models.decision import Decision, DecisionKind
from app.models.organization import Organization
from app.models.privacy_records import RetentionRun, TermsAcceptance
from app.services import org_erasure
from app.services.outbox import SCRUBBED
from app.services.privacy import notices, retention
from tests.api_helpers import kullanici
from tests.db_helpers import gecici_veritabani
from tests.test_org_erasure import _insert, _membership, _rows

T = Base.metadata.tables
NOW = datetime(2026, 11, 23, tzinfo=UTC)
OLD, FRESH = NOW - timedelta(days=400), NOW - timedelta(days=2)


@pytest.fixture(autouse=True)
def _storage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


async def _company(db: Any, tag: str, storage: Path) -> dict[str, Any]:
    """An organisation with old and fresh rows of everything retention touches."""
    org = str(uuid.uuid4())
    await _insert(db, T["organizations"], tag, id=org, slug=f"o-{uuid.uuid4().hex[:8]}", is_active=True, is_demo_guest=False,
                  country_code="TR", base_currency="TRY", locale="tr-TR", plan="free", subscription_plan="free",
                  subscription_status="inactive", max_members=5, max_jobs_per_month=5, regional_packs=[])
    ids: dict[str, Any] = {"org": org}
    for name, when in (("old", OLD), ("fresh", FRESH)):
        await _insert(db, T["outbox_messages"], tag, org_id=org, status="sent", sent_at=when, created_at=when, body=f"body {name}",
                      key=f"{org}-{name}")
        await _insert(db, T["in_app_notifications"], tag, org_id=org, created_at=when)
        await _insert(db, T["alert_history"], tag, org_id=org, created_at=when)
        path = storage / "uploads" / f"{org}-{name}" / "s.csv"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        job = await _insert(db, T["analysis_jobs"], tag, org_id=org, status="completed", created_at=when, file_path=str(path))
        await _insert(db, T["transactions"], tag, job_id=job, raw_text="raw document text")
        await _insert(db, T["rag_chunks"], tag, org_id=org, job_id=job, chunk_index=0)
        ids[name] = {"job": job, "file": path}
    await _insert(db, T["canonical_transactions"], tag, org_id=org, basis="book", ledger_status="active")
    await db.commit()
    return ids


async def _counts(db: Any, org: str) -> dict[str, int]:
    async def n(table: str, **where: Any) -> int:
        t = T[table]
        stmt = select(func.count()).select_from(t)
        for k, v in where.items():
            stmt = stmt.where(t.c[k] == v)
        return int((await db.execute(stmt)).scalar_one())
    return {"outbox_scrubbed": int((await db.execute(select(func.count()).select_from(T["outbox_messages"]).where(
                T["outbox_messages"].c.org_id == org, T["outbox_messages"].c.body == SCRUBBED))).scalar_one()),
            "notifications": await n("in_app_notifications", org_id=org), "alerts": await n("alert_history", org_id=org),
            "chunks": await n("rag_chunks", org_id=org), "ledger": await n("canonical_transactions", org_id=org)}


def _policy(**over: int) -> dict[str, int]:
    return {**retention.platform_policy(), "upload_days": 365, **over}


async def test_a_dry_run_counts_and_changes_nothing(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a = await _company(db, "A", tmp_path)
        before = await _counts(db, a["org"])
        counts = await retention.purge_org(db, a["org"], _policy(), dry_run=True, now=NOW)
        assert counts == {"uploads": 1, "outbox_bodies": 1, "notifications": 1, "alert_history": 1}
        assert await _counts(db, a["org"]) == before and a["old"]["file"].exists()


async def test_the_purge_is_bound_to_one_organisation_and_keeps_the_books(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, b = await _company(db, "A", tmp_path), await _company(db, "B", tmp_path)
        before_b = await _counts(db, b["org"])
        counts = await retention.purge_org(db, a["org"], _policy(), dry_run=False, now=NOW)
        await db.commit()
        assert counts == {"uploads": 1, "outbox_bodies": 1, "notifications": 1, "alert_history": 1}
        after = await _counts(db, a["org"])
        assert after == {"outbox_scrubbed": 1, "notifications": 1, "alerts": 1, "chunks": 1, "ledger": 1}
        assert not a["old"]["file"].exists() and a["fresh"]["file"].exists()  # only the old upload's file goes
        txt = {r["job_id"]: r["raw_text"] for r in await _rows(db, T["transactions"])}
        assert txt[a["old"]["job"]] is None and txt[a["fresh"]["job"]] == "raw document text"
        jobs = {r["id"]: r["file_path"] for r in await _rows(db, T["analysis_jobs"])}
        assert jobs[a["old"]["job"]] == "" and jobs[a["fresh"]["job"]]
        assert await _counts(db, b["org"]) == before_b and b["old"]["file"].exists()  # the neighbour is untouched
        again = await retention.purge_org(db, a["org"], _policy(), dry_run=False, now=NOW)
        assert again == {"uploads": 0, "outbox_bodies": 0, "notifications": 0, "alert_history": 0}  # idempotent


async def test_defaults_keep_every_upload(maker, tmp_path: Path) -> None:
    assert get_settings().retention_upload_days == 0 and get_settings().retention_dry_run is True
    async with maker() as db:
        a = await _company(db, "A", tmp_path)
        counts = await retention.purge_org(db, a["org"], retention.platform_policy(), dry_run=False, now=NOW)
        assert counts["uploads"] == 0 and a["old"]["file"].exists()


async def test_the_platform_purge_expires_tokens_and_truncates_addresses_once(maker) -> None:
    async with maker() as db:
        uid = await _insert(db, T["users"], "A", org_id=None, role="analyst", is_active=True, email="x@x.test")
        await _insert(db, T["password_reset_tokens"], "A", user_id=uid, expires_at=OLD)
        await _insert(db, T["password_reset_tokens"], "A", user_id=uid, expires_at=NOW + timedelta(days=1))
        await _insert(db, T["audit_logs"], "A", user_id=uid, ip_address="203.0.113.77", user_agent="UA", created_at=OLD)
        await _insert(db, T["audit_logs"], "A", user_id=uid, ip_address="203.0.113.78", user_agent="UA", created_at=FRESH)
        await _insert(db, T["audit_logs"], "A", user_id=uid, ip_address="2001:db8:1234:5678::1", user_agent=None, created_at=OLD)
        await db.commit()
        dry = await retention.purge_platform(db, retention.platform_policy(), dry_run=True, now=NOW)
        assert dry == {"tokens": 1, "invitations": 0, "audit_ip": 2}
        assert (await db.execute(select(func.count()).select_from(T["password_reset_tokens"]))).scalar_one() == 2
        done = await retention.purge_platform(db, retention.platform_policy(), dry_run=False, now=NOW)
        await db.commit()
        assert done == dry
        ips = sorted((r["ip_address"], r["user_agent"]) for r in await _rows(db, T["audit_logs"]))
        assert ips == [("2001:db8:1234::", None), ("203.0.113.0", None), ("203.0.113.78", "UA")]
        assert await retention.purge_platform(db, retention.platform_policy(), dry_run=False, now=NOW) == {
            "tokens": 0, "invitations": 0, "audit_ip": 0}


async def test_a_run_records_counts_only_and_skips_erased_and_guest_workspaces(maker, tmp_path: Path, monkeypatch) -> None:
    async with maker() as db:
        a = await _company(db, "A", tmp_path)
        gone = await _company(db, "B", tmp_path)
        guest = await _company(db, "B", tmp_path)
        await db.execute(update(T["organizations"]).where(T["organizations"].c.id == gone["org"]).values(is_active=False, name=org_erasure.ERASED))
        await db.execute(update(T["organizations"]).where(T["organizations"].c.id == guest["org"]).values(is_demo_guest=True))
        await db.execute(update(T["organizations"]).where(T["organizations"].c.id == a["org"]).values(retention_policy={"upload_days": 365}))
        await db.commit()
        dry = await retention.run_retention(db, now=NOW)  # RETENTION_DRY_RUN defaults to true
        assert dry["dry_run"] is True and dry["organisations"] == 1 and dry["counts"]["outbox_bodies"] == 1 and dry["counts"]["uploads"] == 1
        assert a["old"]["file"].exists()
        real = await retention.run_retention(db, dry_run=False, now=NOW)
        assert real["counts"]["outbox_bodies"] == 1 and not a["old"]["file"].exists()
        assert gone["old"]["file"].exists() and guest["old"]["file"].exists()
        again = await retention.run_retention(db, dry_run=False, now=NOW)
        assert sum(again["counts"].values()) == 0
        runs = (await db.execute(select(RetentionRun).order_by(RetentionRun.started_at))).scalars().all()
        assert [r.dry_run for r in runs] == [True, False, False] and all(r.status == "done" for r in runs)
        blob = repr([(r.scope, r.counts, r.policy) for r in runs])
        assert a["org"] not in blob and "ZZPII" not in blob


def test_company_choices_have_a_floor_and_only_known_keys() -> None:
    assert retention.validate_choice({"outbox_body_days": 30, "upload_days": 0}) == {"outbox_body_days": 30, "upload_days": 0}
    for bad in ({"outbox_body_days": 29}, {"notification_days": 0}, {"token_days": 90}, {"upload_days": "30"}, {"upload_days": True}):
        with pytest.raises(ValueError):
            retention.validate_choice(bad)  # type: ignore[arg-type]
    assert retention.truncate_ip("10.1.2.3") == "10.1.2.0" and retention.truncate_ip("not an ip") is None


async def test_the_owner_sets_and_resets_the_companys_choices_and_it_is_recorded(client) -> None:
    owner, org, uid = await kullanici(client, "owner@example.com", role="owner")
    await _membership(client, uid, org, "owner")
    viewer, _, uid_v = await kullanici(client, "v@example.com", attach_org=False, role="analyst")
    async with client._maker() as db:
        from app.models.user import User

        (await db.get(User, uid_v)).org_id = org
        await db.commit()
    await _membership(client, uid_v, org, "analyst")
    url = "/api/v1/privacy/retention"
    assert (await client.put(url, json={"policy": {"outbox_body_days": 60}}, headers=viewer)).status_code == 403
    assert (await client.put(url, json={"policy": {"outbox_body_days": 10}}, headers=owner)).status_code == 422
    assert (await client.put(url, json={"policy": {"token_days": 60}}, headers=owner)).status_code == 422
    ok = await client.put(url, json={"policy": {"outbox_body_days": 60, "upload_days": 400}}, headers=owner)
    assert ok.status_code == 200 and ok.json()["data"]["effective"]["outbox_body_days"] == 60
    reset = await client.put(url, json={"policy": {"outbox_body_days": None}}, headers=owner)
    assert reset.json()["data"]["company_choice"] == {"upload_days": 400}
    async with client._maker() as db:
        rows = (await db.execute(select(Decision).where(Decision.org_id == org, Decision.kind == DecisionKind.RETENTION_POLICY_CHANGE)
                                 .order_by(Decision.decided_at))).scalars().all()
        assert [r.after for r in rows] == [{"outbox_body_days": 60, "upload_days": 400}, {"upload_days": 400}]
        assert (await db.get(Organization, org)).retention_policy == {"upload_days": 400}
    ov = (await client.get("/api/v1/privacy/overview", headers=owner)).json()["data"]
    assert ov["retention"]["can_edit"] is True and ov["retention"]["dry_run"] is True and ov["retention"]["company_choice"] == {"upload_days": 400}
    assert {t["key"] for t in ov["third_parties"]} >= {"llm_provider", "smtp_provider"}
    prev = await client.get("/api/v1/privacy/retention/preview", headers=owner)
    assert prev.status_code == 200 and set(prev.json()["data"]["would_purge"]) == {"uploads", "outbox_bodies", "notifications", "alert_history"}
    ov_v = (await client.get("/api/v1/privacy/overview", headers=viewer)).json()["data"]
    assert ov_v["retention"]["can_edit"] is False and ov_v["export"] is None


# ── notices ──────────────────────────────────────────────────────────────────

async def test_acceptance_is_versioned_and_asked_again_when_the_version_changes(client, monkeypatch) -> None:
    hdr, _, uid = await kullanici(client, "p@example.com", role="owner")
    st = (await client.get("/api/v1/privacy/notices", headers=hdr)).json()["data"]
    assert st["must_accept"] and st["privacy_notice"]["accepted_version"] is None and st["privacy_notice"]["url"] is None
    cur = get_settings()
    stale = await client.post("/api/v1/privacy/notices/accept", json={"privacy_notice": "eski"}, headers=hdr)
    assert stale.status_code == 409
    assert (await client.post("/api/v1/privacy/notices/accept", json={}, headers=hdr)).status_code == 422
    ok = await client.post("/api/v1/privacy/notices/accept",
                           json={"privacy_notice": cur.privacy_notice_version, "terms": cur.terms_version}, headers=hdr)
    assert ok.status_code == 200 and sorted(ok.json()["data"]["recorded"]) == ["privacy_notice", "terms"]
    assert ok.json()["data"]["notices"]["must_accept"] is False
    again = await client.post("/api/v1/privacy/notices/accept", json={"terms": cur.terms_version}, headers=hdr)
    assert again.json()["data"]["recorded"] == []  # the same version is not recorded twice
    monkeypatch.setattr(cur, "privacy_notice_version", "taslak-2")
    monkeypatch.setattr(cur, "privacy_notice_url", "https://example.test/gizlilik")
    st2 = (await client.get("/api/v1/privacy/notices", headers=hdr)).json()["data"]
    assert st2["must_accept"] and st2["privacy_notice"]["must_accept"] and not st2["terms"]["must_accept"]
    assert st2["privacy_notice"]["accepted_version"] == "taslak-1" and st2["privacy_notice"]["url"] == "https://example.test/gizlilik"
    async with client._maker() as db:
        n = (await db.execute(select(func.count()).select_from(TermsAcceptance).where(TermsAcceptance.user_id == uid))).scalar_one()
        assert n == 2
    assert (await client.get("/api/v1/privacy/notices")).status_code in (401, 403)


async def test_unknown_document_is_refused(maker) -> None:
    async with maker() as db:
        with pytest.raises(ValueError, match="unknown document"):
            await notices.accept(db, "u1", {"cookie_policy": "1"})
