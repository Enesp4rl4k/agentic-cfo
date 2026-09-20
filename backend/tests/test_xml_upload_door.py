"""e-Fatura XML gets through the door a person actually uses, and a bomb does not.

The recogniser already read `.xml` as a financial document, and the analysis
pipeline already parses UBL-TR — but both upload doors rejected the extension,
so GİB's own sample invoices came back "Bu dosya türü desteklenmiyor. Excel,
CSV ya da PDF yükleyin." from `POST /veri/ekle`. Found by running the /baglan
flow against the GİB corpus on a live instance.

ElementTree expands internal entities, so the door refuses any document
declaring a DTD or an entity before anything parses it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.xml_safety import UnsafeXMLError, guvenli_mi, parse_xml
from app.services.ingest.ekle import _UZANTILAR
from app.services.ingest.recognize import FINANSAL_BELGE, KESIN, tani
from app.services.upload_service import FileValidationError, validate_extension, validate_xml_payload

GIB = Path(__file__).parent / "fixtures" / "gib_corpus" / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"

_BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<Invoice>&lol3;</Invoice>"""


def _gib_files() -> list[Path]:
    return sorted(p for p in GIB.glob("*.xml"))


def test_the_corpus_is_present():
    assert _gib_files(), "GİB UBL-TR örnek paketi tests/fixtures altında bulunamadı"


@pytest.mark.parametrize("name", ["IDIS_Fatura.xml", "HASTANE.xml", "ISTISNA-1.xml"])
def test_gibs_own_invoices_pass_the_door(name: str):
    raw = (GIB / name).read_bytes()
    validate_extension("xml")          # no longer raises
    validate_xml_payload(raw)          # no DTD, no entity
    assert "xml" in _UZANTILAR
    tanima = tani(raw, name)
    assert (tanima.durum, tanima.tur, tanima.alan) == (KESIN, FINANSAL_BELGE, "cfo")


def test_every_published_sample_is_accepted_by_the_safety_check():
    for f in _gib_files():
        guvenli_mi(f.read_bytes())     # raises if any would be refused


def test_an_entity_bomb_is_refused_before_parsing():
    with pytest.raises(UnsafeXMLError):
        guvenli_mi(_BOMB)
    with pytest.raises(UnsafeXMLError):
        parse_xml(_BOMB)
    with pytest.raises(FileValidationError):
        validate_xml_payload(_BOMB)


def test_a_file_that_is_not_xml_is_refused():
    with pytest.raises(FileValidationError):
        validate_xml_payload(b"tarih,aciklama,tutar\n2026-01-01,kira,1000\n")


def test_the_ubl_parser_refuses_a_bomb_too():
    from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser

    with pytest.raises(UnsafeXMLError):
        UBLTRInvoiceParser.parse_xml(_BOMB.decode("utf-8"))


async def test_the_job_keeps_the_name_the_person_gave_the_file(tmp_path):
    """Every job was called "document.<ext>", so a job list, the setup page and
    an accountant's client screen showed the same word for every upload."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import Base
    from app.services.upload_service import UploadResult, create_analysis_job

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        job = await create_analysis_job(
            result=UploadResult(job_id="j1", file_path=str(tmp_path / "document.xml"), ext="xml",
                                size_bytes=10, original_name="C:/temp/GIB2025000000001.xml"),
            user_id=None, org_id=None, db=db,
        )
        assert job.filename == "GIB2025000000001.xml"   # no path, the person's own name

        adsiz = await create_analysis_job(
            result=UploadResult(job_id="j2", file_path=str(tmp_path / "d.csv"), ext="csv", size_bytes=1),
            user_id=None, org_id=None, db=db,
        )
        assert adsiz.filename == "document.csv"
    await engine.dispose()
