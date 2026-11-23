"""Review follow-ups of the export / retention work: expiry on its own schedule, upload-only purge, the retention
range, erasure racing an export, and the export's fixed file location."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.database import Base
from app.models.erasure_record import OrgErasureRequest
from app.models.job_run import ScheduledJobRun
from app.models.privacy_records import DataExport
from app.services import org_erasure as svc
from app.services.privacy import export_flow, jobs, retention
from tests.api_helpers import kullanici
from tests.db_helpers import gecici_veritabani
from tests.test_org_erasure import _insert, _membership, _two_orgs
from tests.test_privacy_retention import NOW, _company, _policy

EXPORTS = "/api/v1/privacy/exports"
T = Base.metadata.tables


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


@pytest.fixture(autouse=True)
def _storage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    monkeypatch.setattr(get_settings(), "allow_inline_job_fallback", False)


def _zip(eid: str, text: str = "PK") -> Path:
    path = export_flow.export_path(eid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


async def _ready(db: Any, org: str, *, expired: bool, file_path: str | None = None) -> DataExport:
    now = datetime.now(UTC)
    row = DataExport(org_id=org, requested_by=str(uuid.uuid4()), status="ready", ready_at=now,
                     expires_at=now - timedelta(minutes=1) if expired else now + timedelta(hours=5))
    db.add(row)
    await db.flush()
    row.file_path = file_path or str(export_flow.export_path(row.id))
    await db.commit()
    return row


# ── blocker: export files expire on their own schedule ───────────────────────

async def test_expired_exports_are_deleted_by_their_own_job_even_in_dry_run(maker, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "retention_dry_run", True)  # the default
    outside = tmp_path / "outside.txt"
    outside.write_text("not an export")
    async with maker() as db:
        old = await _ready(db, "org-x", expired=True, file_path=str(outside))  # a tampered path must not be followed
        live = await _ready(db, "org-x", expired=False)
        old_zip, live_zip = _zip(old.id), _zip(live.id)
        old_part = old_zip.with_name(old_zip.name + ".part")
        old_part.write_text("half")
        live_id, old_id = live.id, old.id
    monkeypatch.setattr("app.database.engine", lambda: None)
    monkeypatch.setattr("app.database.get_session_factory", lambda _e: maker)
    await jobs.run_export_expiry()
    assert not old_zip.exists() and not old_part.exists() and live_zip.exists() and outside.exists()
    async with maker() as db:
        assert (await db.get(DataExport, old_id)).status == "expired" and (await db.get(DataExport, old_id)).file_path is None
        assert (await db.get(DataExport, live_id)).status == "ready"
        runs = (await db.execute(select(ScheduledJobRun).where(ScheduledJobRun.job == jobs.EXPORT_EXPIRY))).scalars().all()
        assert [r.status for r in runs] == ["done"]  # the scheduler ledger recorded the run
    await jobs.run_export_expiry()  # same hour again: the ledger makes it a no-op
    async with maker() as db:
        assert (await db.execute(select(func.count()).select_from(ScheduledJobRun).where(
            ScheduledJobRun.job == jobs.EXPORT_EXPIRY))).scalar_one() == 1


def test_the_expiry_job_is_registered_hourly() -> None:
    added: list[str] = []

    class Sched:
        def add_job(self, fn, trigger, id, **kw):
            added.append(id)

    jobs.register_privacy_jobs(Sched(), lambda fn, name, **kw: fn)
    assert "export_expiry" in added


async def test_the_download_refuses_an_expired_export_even_if_the_file_is_still_there(client) -> None:
    hdr, org, uid = await kullanici(client, "dl@example.com", role="owner")
    await _membership(client, uid, org, "owner")
    async with client._maker() as db:
        row = await _ready(db, org, expired=True)
        path = _zip(row.id)
        eid = row.id
    assert path.exists()
    got = await client.get(f"{EXPORTS}/{eid}/download", headers=hdr)
    assert got.status_code == 410 and b"PK" not in got.content


# ── retention: only the classes the PR documents ─────────────────────────────

async def test_the_upload_purge_deletes_the_raw_file_and_not_reports_or_board_decks(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a = await _company(db, "A", tmp_path)
        job = a["old"]["job"]
        keep = [tmp_path / "reports" / job / "report.pdf", tmp_path / "board_decks" / f"{job}.pdf",
                tmp_path / "uploads" / a["old"]["file"].parent.name / "datasources" / "x.csv", tmp_path / f"{job}_demo.csv"]
        for p in keep:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("keep me")
        await retention.purge_org(db, a["org"], _policy(), dry_run=False, now=NOW)
        await db.commit()
    assert not a["old"]["file"].exists()  # the raw upload went
    assert all(p.exists() for p in keep), "reports, board decks or data-source files were deleted by the upload purge"
    assert a["fresh"]["file"].exists()


async def test_a_company_may_shorten_retention_never_lengthen_it(maker) -> None:
    platform = retention.platform_policy()
    assert platform["notification_days"] == 180
    assert retention.validate_choice({"notification_days": 60}) == {"notification_days": 60}
    assert retention.validate_choice({"notification_days": 180}) == {"notification_days": 180}
    for bad in ({"notification_days": 181}, {"notification_days": 100000}, {"notification_days": 29},
                {"alert_history_days": 366}):
        with pytest.raises(ValueError):
            retention.validate_choice(bad)

    class Org:  # a stored value from before the rule, or written around the API
        retention_policy = {"notification_days": 100000, "alert_history_days": 5, "outbox_body_days": 45}

    eff = retention.effective_policy(Org())  # type: ignore[arg-type]
    assert eff["notification_days"] == 180  # clamped to the platform default
    assert eff["alert_history_days"] == retention.FLOOR_DAYS  # clamped up to the floor
    assert eff["outbox_body_days"] == 45


# ── erasure and an export ────────────────────────────────────────────────────

async def test_erasure_deletes_the_organisations_export_files_including_a_running_one(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, b, _ = await _two_orgs(db)
        running = DataExport(org_id=a["org"], requested_by="u", status="running")  # no file_path recorded yet
        db.add(running)
        await db.commit()
        a_ids = list((await db.execute(select(DataExport.id).where(DataExport.org_id == a["org"]))).scalars())
        b_ids = list((await db.execute(select(DataExport.id).where(DataExport.org_id == b["org"]))).scalars())
        a_files = [p for i in a_ids for p in (_zip(i), _zip(i).with_name(f"{i}.zip.part"))]
        for p in a_files:
            p.write_text("ZIP")
        b_files = [_zip(i) for i in b_ids]
        await svc.erase_org(db, a["org"], storage_root=tmp_path)
    assert a_files and not [p for p in a_files if p.exists()], "an export file of the erased company remains"
    assert all(p.exists() for p in b_files)
    async with maker() as db:
        assert not (await db.execute(select(DataExport).where(DataExport.id.in_(a_ids)))).scalars().all()


async def test_an_export_fails_closed_while_its_organisation_is_being_erased(maker, tmp_path: Path) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        row = DataExport(org_id=a["org"], requested_by="u", status="queued")
        db.add(row)
        await _insert(db, T["org_erasure_requests"], "A", target_org_id=a["org"], status="executing", mode="anonymise")
        await db.commit()
        status = await export_flow.build_export(db, row.id)
        assert status == "failed"
        fresh = await db.get(DataExport, row.id)
        assert fresh.error_code == "org_erasing" and fresh.file_path is None
        assert not export_flow.export_path(row.id).exists()
        assert (await db.execute(select(func.count()).select_from(OrgErasureRequest))).scalar_one() == 1
