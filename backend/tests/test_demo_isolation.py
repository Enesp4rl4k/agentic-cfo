"""Demo mode never touches a real organisation.

* The flag is environment-only: no route or service assigns it.
* /demo/seed needs the flag AND a guest workspace; on a real org it would run the sample company's
  rows through that org's ledger.
* /demo/reset deletes the org's whole ledger, so a real org is refused even with the flag on.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api.org import _regional_defaults
from app.config import Settings, get_settings
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.services.auth import create_access_token
from app.services.demo_template import DEMO_FILENAME
from tests.api_helpers import bellek_istemcisi

_APP = Path(__file__).resolve().parent.parent / "app"


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    async with bellek_istemcisi() as c:
        yield c


async def _real_owner(client) -> tuple[dict[str, str], str]:
    async with client._test_sessionmaker() as db:
        org = Organization(name="Gerçek Şirket", slug=f"real-{secrets.token_hex(4)}", **_regional_defaults("TR"))
        db.add(org)
        await db.flush()
        user = User(email=f"o-{secrets.token_hex(4)}@firma.test", hashed_password="x", full_name="Sahip",
                    role=UserRole.OWNER, org_id=org.id)
        db.add(user)
        await db.flush()
        db.add(AnalysisJob(id=secrets.token_hex(16)[:32], status=JobStatus.COMPLETED, filename=DEMO_FILENAME,
                           file_path="x", file_type="csv", org_id=org.id, user_id=str(user.id)))
        await db.commit()
        token = create_access_token(user.id, user.email, user.role)
        return {"Authorization": f"Bearer {token}"}, str(org.id)


async def _jobs(client, org_id: str) -> int:
    async with client._test_sessionmaker() as db:
        return len((await db.execute(select(AnalysisJob).where(AnalysisJob.org_id == org_id))).scalars().all())


@pytest.mark.asyncio
async def test_reset_refuses_a_real_org_and_keeps_its_data(client):
    headers, org_id = await _real_owner(client)
    r = await client.delete("/api/v1/demo/reset", headers=headers)
    assert r.status_code == 403
    assert await _jobs(client, org_id) == 1


@pytest.mark.asyncio
async def test_seed_refuses_a_real_org_and_adds_nothing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    headers, org_id = await _real_owner(client)
    r = await client.post("/api/v1/demo/seed", headers=headers)
    assert r.status_code == 403
    assert await _jobs(client, org_id) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_seed_needs_the_flag_even_for_a_guest(client, tmp_path, monkeypatch):
    from tests.golden_seed import _auth, _guest

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    guest = await _guest(client)
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert (await client.post("/api/v1/demo/seed", headers=_auth(guest))).status_code == 403
    assert (await client.post("/api/v1/demo/guest")).status_code == 403


def test_demo_mode_is_off_by_default_and_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert Settings(_env_file=None).demo_mode is False  # type: ignore[call-arg]
    monkeypatch.setenv("DEMO_MODE", "true")
    assert Settings(_env_file=None).demo_mode is True  # type: ignore[call-arg]


def test_nothing_in_the_app_assigns_the_demo_flag():
    assign = re.compile(r"(setattr\([^)]*[\"']demo_mode[\"']|\.demo_mode\s*=[^=])")
    offenders = [p.relative_to(_APP).as_posix() for p in _APP.rglob("*.py")
                 if assign.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == [], f"demo_mode must stay environment-only: {offenders}"
