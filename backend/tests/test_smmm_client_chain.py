"""Müşavirin müşteri listesi ile uyum zinciri aynı şey hakkında konuşmalı.

`SMMMMusteriKayit` carried `client_org_id`, `last_job_id`, `last_analysis_at`,
`health_score` and `health_label`, and the model called them a denormalized
cache. Nothing ever wrote one of them. So `/smmm/dashboard` counted its
"analysed clients" from a field that was always null, and every accountant who
opened that page saw zero — while the compliance chain sat one table away with
the real answer in it.

An accountant could register forty clients and run the chain for none of them,
because a job had no way to say which client it was for.

The fields stay unwritten on purpose. A cache drifts from what it caches, and
this codebase has spent a lot of this work unpicking values that drifted
silently. Status is derived from the jobs, which cannot.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.defensibility_packet import DefensibilityPacket
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit
from app.models.user import User
from app.services.smmm_clients import (
    ClientNotOwned,
    assert_owns_client,
    status_for_clients,
)


@pytest_asyncio.fixture
async def db_session():
    """An in-memory database, per test.

    Matches the pattern in test_api_integration; there is no shared session
    fixture in this suite.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def book(db_session: AsyncSession):
    """One accountant with three client companies."""
    user = User(email="musavir@example.com", hashed_password="x", full_name="SMMM")
    db_session.add(user)
    await db_session.flush()

    m = SMMMMuhasebeci(user_id=user.id, unvan="SMMM Ahmet", oda_no="34-1")
    db_session.add(m)
    await db_session.flush()

    clients = []
    for name in ("Demir İnşaat A.Ş.", "Öztürk Holding", "Yıldız Tekstil"):
        c = SMMMMusteriKayit(muhasebeci_id=m.id, firma_adi=name)
        db_session.add(c)
        clients.append(c)
    await db_session.flush()
    return user, m, clients


def _job(client_id: str | None, *, status: str, minutes_ago: int = 0) -> AnalysisJob:
    return AnalysisJob(
        status=status,
        filename="x.csv",
        file_path="/tmp/x.csv",
        file_type="csv",
        smmm_client_id=client_id,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


# ── Derived status ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_client_with_no_jobs_reads_as_having_no_data(db_session, book) -> None:
    _user, _m, clients = book
    durum = await status_for_clients(db_session, [str(c.id) for c in clients])
    for c in clients:
        s = durum[str(c.id)]
        assert s.job_count == 0
        assert s.stage == "veri_yok"
        assert not s.needs_attention


@pytest.mark.asyncio
async def test_status_follows_the_newest_job_for_each_client(db_session, book) -> None:
    _user, _m, clients = book
    target = str(clients[0].id)
    db_session.add(_job(target, status=JobStatus.FAILED, minutes_ago=60))
    newest = _job(target, status=JobStatus.COMPLETED, minutes_ago=1)
    db_session.add(newest)
    await db_session.flush()

    s = (await status_for_clients(db_session, [target]))[target]
    assert s.job_count == 2
    assert s.last_job_id == str(newest.id)
    assert s.stage == "analiz_edildi"


@pytest.mark.asyncio
async def test_a_failed_run_asks_for_attention(db_session, book) -> None:
    _user, _m, clients = book
    target = str(clients[0].id)
    db_session.add(_job(target, status=JobStatus.FAILED))
    await db_session.flush()

    s = (await status_for_clients(db_session, [target]))[target]
    assert s.stage == "basarisiz"
    assert s.needs_attention


@pytest.mark.asyncio
async def test_pending_approvals_are_counted_per_client(db_session, book) -> None:
    """The number that makes the page worth opening: whose work is waiting."""
    _user, _m, clients = book
    target = str(clients[0].id)
    job = _job(target, status=JobStatus.COMPLETED)
    db_session.add(job)
    await db_session.flush()
    for i in range(3):
        db_session.add(
            SMMMOnayKaydi(
                job_id=job.id,
                kayit_id=f"k{i}",
                durum=OnayDurumu.BEKLIYOR,
                orijinal_kayit={},
            )
        )
    db_session.add(
        SMMMOnayKaydi(
            job_id=job.id, kayit_id="onaylanan",
            durum=OnayDurumu.ONAYLANDI, orijinal_kayit={},
        )
    )
    await db_session.flush()

    s = (await status_for_clients(db_session, [target]))[target]
    assert s.pending_review == 3, "yalnızca bekleyenler sayılmalı"
    assert s.stage == "onay_bekliyor"
    assert s.needs_attention


@pytest.mark.asyncio
async def test_a_sealed_packet_moves_the_client_to_done(db_session, book) -> None:
    _user, _m, clients = book
    target = str(clients[0].id)
    job = _job(target, status=JobStatus.COMPLETED)
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        DefensibilityPacket(job_id=job.id, status="finalized", summary={}, payload={})
    )
    await db_session.flush()

    s = (await status_for_clients(db_session, [target]))[target]
    assert s.packet_sealed
    assert s.stage == "muhurlendi"
    assert not s.needs_attention


@pytest.mark.asyncio
async def test_one_client_s_work_does_not_leak_into_another(db_session, book) -> None:
    _user, _m, clients = book
    a, b = str(clients[0].id), str(clients[1].id)
    db_session.add(_job(a, status=JobStatus.COMPLETED))
    await db_session.flush()

    out = await status_for_clients(db_session, [a, b])
    assert out[a].job_count == 1
    assert out[b].job_count == 0


@pytest.mark.asyncio
async def test_a_company_analysing_itself_belongs_to_no_client(db_session, book) -> None:
    """`smmm_client_id` is null for the ordinary case, and such a job must not
    be attributed to anybody's client."""
    _user, _m, clients = book
    db_session.add(_job(None, status=JobStatus.COMPLETED))
    await db_session.flush()

    out = await status_for_clients(db_session, [str(c.id) for c in clients])
    assert all(s.job_count == 0 for s in out.values())


@pytest.mark.asyncio
async def test_no_clients_is_not_an_error(db_session) -> None:
    assert await status_for_clients(db_session, []) == {}


# ── Ownership ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_accountant_may_name_their_own_client(db_session, book) -> None:
    user, _m, clients = book
    assert await assert_owns_client(db_session, str(user.id), str(clients[0].id))


@pytest.mark.asyncio
async def test_someone_else_s_client_is_refused(db_session, book) -> None:
    """`client_id` arrives as a plain form field on an upload. Without this an
    accountant could file work against another accountant's client by guessing
    an id."""
    _user, _m, clients = book
    other = User(email="baska@example.com", hashed_password="x", full_name="Other")
    db_session.add(other)
    await db_session.flush()

    with pytest.raises(ClientNotOwned):
        await assert_owns_client(db_session, str(other.id), str(clients[0].id))


@pytest.mark.asyncio
async def test_an_unknown_client_id_is_refused(db_session, book) -> None:
    user, _m, _clients = book
    with pytest.raises(ClientNotOwned):
        await assert_owns_client(db_session, str(user.id), "yok-boyle-bir-id")


@pytest.mark.asyncio
async def test_a_deactivated_client_cannot_receive_new_work(db_session, book) -> None:
    user, _m, clients = book
    clients[0].is_active = False
    await db_session.flush()
    with pytest.raises(ClientNotOwned):
        await assert_owns_client(db_session, str(user.id), str(clients[0].id))


# ── The dashboard must not go back to the dead cache ─────────────────────────

def test_the_portal_no_longer_reads_fields_nobody_writes() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "smmm_benchmark.py"
    ).read_text(encoding="utf-8")
    for dead in ("c.health_score", "c.health_label", "c.last_job_id"):
        assert dead not in src, (
            f"{dead} hiçbir kod tarafından yazılmıyor — panel onu okursa "
            "sayılar yapısal olarak sıfır kalır"
        )
