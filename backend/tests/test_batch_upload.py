"""Documents dropped together are one analysis, not one each.

Dropping three e-Fatura XMLs on /baglan started three separate analyses — each
with its own review to clear, its own LLM run and no combined picture. Seen on
a live instance: three files in, three jobs out, all "awaiting_review".

The first financial document opens the analysis, the rest attach to it, and the
run is started once every file is in place.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.ingest.ekle as ekle
from app.database import Base
from app.models.analysis_job import AnalysisJob
from app.models.data_source import DataSource, DataSourceDomain, DataSourceType

_FATURA = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>GIB%03d</ID>
</Invoice>"""


def _fatura(n: int) -> bytes:
    return _FATURA % n


@pytest_asyncio.fixture
async def db(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path), raising=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
def baslatilanlar(monkeypatch):
    """Records each analysis start instead of queueing one."""
    calls: list[str] = []

    async def fake_enqueue(job_id, budget_input=None):
        calls.append(job_id)
        return "queued"

    import app.worker as worker

    monkeypatch.setattr(worker, "enqueue_analysis", fake_enqueue)
    return calls


async def test_three_invoices_become_one_analysis_started_once(db, baslatilanlar):
    out = await ekle.dosyalari_ekle(
        db, ekle.Sahip(org_id="org-1", user_id="u1"),
        [("f1.xml", _fatura(1)), ("f2.xml", _fatura(2)), ("f3.xml", _fatura(3))],
    )
    assert [d["durum"] for d in out["dosyalar"]] == [ekle.EKLENDI] * 3
    assert len({d["job_id"] for d in out["dosyalar"]}) == 1, "üç dosya tek analize girmeli"

    jobs = (await db.execute(select(AnalysisJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].filename == "f1.xml"

    ekler = (await db.execute(
        select(DataSource).where(DataSource.domain == DataSourceDomain.CFO)
    )).scalars().all()
    assert sorted(e.filename for e in ekler) == ["f2.xml", "f3.xml"]
    assert {e.source_type for e in ekler} == {DataSourceType.FINANCIAL_DOCUMENT}

    assert baslatilanlar == [jobs[0].id], "analiz bir kez başlamalı"
    assert "3 belge tek analizde birleştirildi" in out["dosyalar"][0]["mesaj"]


async def test_the_same_file_twice_in_one_request_is_added_once(db, baslatilanlar):
    out = await ekle.dosyalari_ekle(
        db, ekle.Sahip(org_id="org-1", user_id="u1"),
        [("f1.xml", _fatura(1)), ("kopya.xml", _fatura(1))],
    )
    durumlar = [d["durum"] for d in out["dosyalar"]]
    assert durumlar.count(ekle.EKLENDI) == 1
    assert ekle.MUKERRER in durumlar
    assert len((await db.execute(select(DataSource))).scalars().all()) == 0
    assert len(baslatilanlar) == 1


async def test_a_single_document_still_starts_its_own_analysis(db, baslatilanlar):
    out = await ekle.dosyalari_ekle(
        db, ekle.Sahip(org_id="org-1", user_id="u1"), [("tek.xml", _fatura(9))],
    )
    d = out["dosyalar"][0]
    assert d["durum"] == ekle.EKLENDI
    assert d["mesaj"] == "Analiz başlatıldı."
    assert baslatilanlar == [d["job_id"]]
