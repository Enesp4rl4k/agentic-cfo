"""The company export (owner, async, bounded, time-limited, recorded) and the member's own export."""
from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import get_settings
from app.database import Base
from app.models.audit_log import AuditLog
from app.models.decision import Decision, DecisionKind
from app.models.privacy_records import DataExport
from app.services.privacy import export_bundle, export_flow
from tests.api_helpers import kullanici
from tests.db_helpers import gecici_veritabani
from tests.test_org_erasure import _insert, _membership, _rows, _two_orgs

EXPORTS = "/api/v1/privacy/exports"


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


@pytest.fixture(autouse=True)
def _no_inline(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "allow_inline_job_fallback", False)  # tests build explicitly


def _everything(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        return "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())


async def test_the_bundle_holds_the_company_and_only_the_company(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        job = a["analysis_jobs"]
        f = tmp_path / "uploads" / job / "statement.csv"
        f.parent.mkdir(parents=True)
        f.write_text("date,amount\n")
        jt = Base.metadata.tables["analysis_jobs"]
        await db.execute(jt.update().where(jt.c.id == job).values(file_path=str(f), filename="statement.csv"))
        await db.commit()
        dest = tmp_path / "a.zip"
        manifest = await export_bundle.build(db, a["org"], dest, tmp_path, 10_000_000)
        users = await _rows(db, Base.metadata.tables["users"])
    blob = _everything(dest)
    assert "ZZPIIA" in blob
    with zipfile.ZipFile(dest) as zf:  # none of the neighbour's records; its shared member is A's member too
        leaked = [n for n in zf.namelist() if n != "members.json" and b"ZZPIIB" in zf.read(n)]
    assert not leaked, leaked
    for u in users:  # no credential of any account, whatever company it belongs to
        for secret in (u["hashed_password"], u["api_key"]):
            assert secret not in blob
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "README.txt", "ledger.jsonl", "decisions.jsonl", "members.json", "settings.json",
                "uploads.json", f"files/{job}/statement.csv"} <= names
        first = json.loads(zf.read("ledger.jsonl").decode().splitlines()[0])
        assert "org_id" in first and "amount_cents" in first
    assert manifest["files"]["included"] == 1 and not manifest["size_bound_reached"]
    assert manifest["datasets"]["members"]["rows"] == 3  # two of its own and the member it shares with B
    for ds in manifest["datasets"].values():
        assert not [c for c in ds["columns"] if export_bundle.SECRET_COLUMN.search(c.split(".")[-1])]


async def test_the_size_bound_cuts_and_says_so(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        f = tmp_path / "uploads" / a["analysis_jobs"] / "big.csv"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x" * 50_000)
        jt = Base.metadata.tables["analysis_jobs"]
        await db.execute(jt.update().where(jt.c.id == a["analysis_jobs"]).values(file_path=str(f)))
        await db.commit()
        manifest = await export_bundle.build(db, a["org"], tmp_path / "s.zip", tmp_path, 20_000)
    assert manifest["size_bound_reached"] is True
    assert manifest["files"]["omitted"] == [{"job_id": a["analysis_jobs"], "reason": "size_limit"}]


async def test_a_file_outside_the_storage_root_is_never_packed(maker, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("do not pack")
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        jt = Base.metadata.tables["analysis_jobs"]
        await db.execute(jt.update().where(jt.c.id == a["analysis_jobs"]).values(file_path=str(outside)))
        await db.commit()
        manifest = await export_bundle.build(db, a["org"], tmp_path / "o.zip", tmp_path / "store", 10_000_000)
    assert manifest["files"]["omitted"][0]["reason"] == "outside_storage"
    assert "do not pack" not in _everything(tmp_path / "o.zip")
    outside.unlink()


async def _owner_and_company(client: Any, email: str) -> tuple[dict[str, str], str]:
    hdr, org, uid = await kullanici(client, email, role="owner")
    await _membership(client, uid, org, "owner")
    async with client._maker() as db:
        await _insert(db, Base.metadata.tables["canonical_transactions"], "A", org_id=org, basis="book", ledger_status="active")
        await db.commit()
    return hdr, org


async def test_owner_requests_a_job_builds_it_and_downloads_until_it_expires(client) -> None:
    hdr, org = await _owner_and_company(client, "owner@example.com")
    first = await client.post(EXPORTS, headers=hdr)
    assert first.status_code == 200 and first.json()["data"]["status"] == "queued" and first.json()["data"]["created"]
    eid = first.json()["data"]["export_id"]
    again = await client.post(EXPORTS, headers=hdr)  # one live export per company
    assert again.json()["data"]["export_id"] == eid and again.json()["data"]["created"] is False
    assert (await client.get(f"{EXPORTS}/{eid}/download", headers=hdr)).status_code == 409  # not built yet

    async with client._maker() as db:
        assert await export_flow.build_export(db, eid) == "ready"
        assert await export_flow.build_export(db, eid) == "ready"  # twice is harmless
        decisions = (await db.execute(select(Decision).where(Decision.org_id == org, Decision.kind == DecisionKind.DATA_EXPORT))).scalars().all()
        assert [d.outcome for d in decisions] == ["requested"]
    status = (await client.get(f"{EXPORTS}/{eid}", headers=hdr)).json()["data"]
    assert status["status"] == "ready" and status["summary"]["ledger"]["rows"] == 1 and status["download"]
    got = await client.get(f"{EXPORTS}/{eid}/download", headers=hdr)
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
    assert got.content[:2] == b"PK" and "no-store" in got.headers["cache-control"]

    async with client._maker() as db:
        row = await db.get(DataExport, eid)
        assert row.downloads == 1 and row.expires_at - row.ready_at == timedelta(hours=get_settings().data_export_ttl_hours)
        path = Path(row.file_path)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        assert (await client.get(f"{EXPORTS}/{eid}/download", headers=hdr)).status_code == 410
        assert await export_flow.purge_expired(db) == 1
        assert not path.exists() and (await db.get(DataExport, eid)).file_path is None
    fresh = await client.post(EXPORTS, headers=hdr)  # the window closed: a new one may be asked for
    assert fresh.json()["data"]["created"] is True and fresh.json()["data"]["export_id"] != eid


async def test_only_the_owner_of_that_company_may_ask_or_read(client) -> None:
    hdr, org = await _owner_and_company(client, "owner2@example.com")
    other, _ = await _owner_and_company(client, "owner3@example.org")
    adm, _, uid_adm = await kullanici(client, "adm@example.com", attach_org=False, role="admin")
    async with client._maker() as db:
        from app.models.user import User

        (await db.get(User, uid_adm)).org_id = org
        await db.commit()
    await _membership(client, uid_adm, org, "admin")
    eid = (await client.post(EXPORTS, headers=hdr)).json()["data"]["export_id"]
    async with client._maker() as db:
        await export_flow.build_export(db, eid)
    assert (await client.post(EXPORTS, headers=adm)).status_code == 403
    assert (await client.get(f"{EXPORTS}/{eid}", headers=adm)).status_code == 403
    assert (await client.get(f"{EXPORTS}/{eid}", headers=other)).status_code == 404
    assert (await client.get(f"{EXPORTS}/{eid}/download", headers=other)).status_code == 404
    assert (await client.post(EXPORTS)).status_code in (401, 403)


async def test_a_sweeper_builds_what_the_queue_dropped(client) -> None:
    hdr, _ = await _owner_and_company(client, "sweep@example.com")
    eid = (await client.post(EXPORTS, headers=hdr)).json()["data"]["export_id"]
    async with client._maker() as db:
        assert (await export_flow.build_pending(db))["built"] == 0  # too fresh: the queue may still have it
        assert (await export_flow.build_pending(db, now=datetime.now(UTC) + timedelta(minutes=5)))["built"] == 1
        assert (await db.get(DataExport, eid)).status == "ready"


async def test_a_failed_build_leaves_a_code_and_no_file(client, monkeypatch) -> None:
    hdr, _ = await _owner_and_company(client, "fail@example.com")
    eid = (await client.post(EXPORTS, headers=hdr)).json()["data"]["export_id"]

    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(export_bundle, "build", boom)
    async with client._maker() as db:
        assert await export_flow.build_export(db, eid) == "failed"
        row = await db.get(DataExport, eid)
        assert row.error_code == "build_failed" and row.file_path is None
        assert "secret detail" not in repr(row.summary) + repr(row.error_code)


async def test_my_data_is_the_callers_own_and_nobody_elses(client) -> None:
    mine, _, uid = await kullanici(client, "me@example.com", role="owner")
    _, _, other = await kullanici(client, "someone@example.com", attach_org=False, role="analyst")
    async with client._maker() as db:
        db.add(AuditLog(user_id=uid, user_email="me@example.com", user_role="owner", action="POST /a", resource="/a", ip_address="10.0.0.1"))
        db.add(AuditLog(user_id=other, user_email="someone@example.com", user_role="analyst", action="POST /b", resource="/b"))
        await db.commit()
    r = await client.get("/api/v1/privacy/my-data", headers=mine)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["profile"]["email"] == "me@example.com" and data["profile"]["user_id"] == uid
    assert [e["action"] for e in data["audit_entries"]] == ["POST /a"] and data["audit_entries"][0]["ip_address"] == "10.0.0.1"
    blob = r.text
    assert "someone@example.com" not in blob and "hashed_password" not in blob and "api_key" not in blob
    legacy = await client.get("/api/v1/compliance/data-export", headers=mine)  # the old path answers the same
    assert legacy.status_code == 200 and legacy.json()["profile"]["user_id"] == uid
    assert (await client.get("/api/v1/privacy/my-data")).status_code in (401, 403)
