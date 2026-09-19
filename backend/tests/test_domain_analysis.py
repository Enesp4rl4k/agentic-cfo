"""Tek motor: gerçek veri varsa analiz, yoksa "veri yok" — asla tahmin.

The kernels answered every domain question whether or not there was data,
with numbers derived from CFO figures, fixed constants and each other. These
tests hold the replacement to three promises:

1. Real files attached to the job → the domain's own orchestrator runs on them.
2. Not enough files → no analysis and no invented number; the answer names
   what is missing and how to get it.
3. The only figures shown without domain data are ones the CFO report really
   contains, each with its source.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.agents.orchestration import domain_analysis as da
from tests.test_agents.test_chro_pipeline import HEADCOUNT_CSV
from tests.test_agents.test_cto_pipeline import BILLING_CSV, INCIDENT_CSV


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _job(db, *, pnl: dict | None = None):
    from app.models.analysis_job import AnalysisJob
    from app.models.report import Report, ReportFormat

    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id="org-1")
    db.add(job)
    await db.flush()
    if pnl is not None:
        db.add(Report(job_id=job.id, report_type="dashboard", report_format=ReportFormat.JSON,
                      data={"pnl": pnl}))
    await db.commit()
    return job


async def _attach(db, tmp_path, job, domain: str, source_type: str, content: str, name: str = "f.csv"):
    from app.models.data_source import DataSource

    p = tmp_path / f"{domain}-{source_type}-{name}"
    p.write_text(content, encoding="utf-8")
    db.add(DataSource(job_id=job.id, domain=domain, source_type=source_type,
                      filename=name, file_path=str(p), file_size_bytes=p.stat().st_size))
    await db.commit()


PNL = {"revenue": 1_000_000_00, "opex": {"technology": 80_000_00, "marketing": 50_000_00, "salary": 300_000_00}}


@pytest.mark.asyncio
async def test_no_data_means_no_analysis_and_no_invented_number(db) -> None:
    job = await _job(db, pnl=PNL)
    out = await da.analiz_et(db, job, "cto")
    assert out["durum"] == da.VERI_YOK
    assert out["sonuc"] is None
    text = str(out)
    for invented in ("security_score", "open_vulnerabilities", "health_score", "velocity_trend"):
        assert invented not in text, f"{invented} hiçbir veriye dayanmıyor"


@pytest.mark.asyncio
async def test_without_data_it_says_what_to_upload_and_how(db) -> None:
    job = await _job(db, pnl=PNL)
    out = await da.durum(db, job, "cto")
    assert len(out["eksik"]) == 4
    assert all(k["nasil"] for k in out["kaynaklar"])
    assert any("GitHub" in k["nasil"] for k in out["kaynaklar"])


@pytest.mark.asyncio
async def test_the_cfo_books_real_spend_is_shown_with_its_source(db) -> None:
    job = await _job(db, pnl=PNL)
    kalemler = (await da.durum(db, job, "cto"))["cfo_gercek"]["kalemler"]
    assert kalemler == [{
        "kategori": "technology",
        "etiket": "Banka hareketlerindeki teknoloji harcaması",
        "tutar_kurus": 80_000_00,
        "gelire_orani": 0.08,
        "kaynak": "CFO raporu — 'technology' kategorisindeki işlemlerin toplamı",
    }]


@pytest.mark.asyncio
async def test_no_cfo_report_means_no_cfo_figures(db) -> None:
    job = await _job(db)
    assert (await da.durum(db, job, "cmo"))["cfo_gercek"] == {"var": False, "kalemler": []}


@pytest.mark.asyncio
async def test_real_files_run_the_orchestrator(db, tmp_path) -> None:
    job = await _job(db, pnl=PNL)
    await _attach(db, tmp_path, job, "cto", "cloud_billing", BILLING_CSV)
    await _attach(db, tmp_path, job, "cto", "incident_log", INCIDENT_CSV)
    out = await da.analiz_et(db, job, "cto")
    assert out["durum"] == da.ANALIZ_EDILDI
    assert out["provenance"]["data_source"] == "real"
    assert out["sonuc"]["infra"], "bulut faturasından altyapı analizi çıkmalı"
    assert "cloud_billing_csv" not in out["sonuc"], "kullanıcının dosyası geri yankılanmamalı"


@pytest.mark.asyncio
async def test_a_domain_that_needs_every_file_waits_for_all_of_them(db, tmp_path) -> None:
    job = await _job(db)
    await _attach(db, tmp_path, job, "chro", "headcount", HEADCOUNT_CSV)
    out = await da.analiz_et(db, job, "chro")
    assert out["durum"] == da.EKSIK_VERI
    assert out["sonuc"] is None
    assert set(out["eksik"]) == {"attrition", "compensation"}


@pytest.mark.asyncio
async def test_an_excel_file_reaches_the_orchestrator_as_rows_not_bytes(db, tmp_path) -> None:
    """The CEO wizard read .xlsx as UTF-8 text — replacement characters."""
    import openpyxl

    job = await _job(db)
    wb = openpyxl.Workbook()
    ws = wb.active
    for line in BILLING_CSV.strip().splitlines():
        ws.append(line.split(","))
    path = tmp_path / "fatura.xlsx"
    wb.save(path)
    text = da._read_as_csv(str(path))
    assert text is not None and text.splitlines()[0] == "service,cost,environment,month"


@pytest.mark.asyncio
async def test_every_domain_has_a_door(db) -> None:
    job = await _job(db)
    for kod in da.ALANLAR:
        out = await da.durum(db, job, kod)
        assert out["kaynaklar"] and all(k["nasil"] for k in out["kaynaklar"]), kod


@pytest.mark.asyncio
async def test_an_unknown_domain_is_refused(db) -> None:
    job = await _job(db)
    with pytest.raises(da.AlanBilinmiyor):
        await da.durum(db, job, "cfo2")
