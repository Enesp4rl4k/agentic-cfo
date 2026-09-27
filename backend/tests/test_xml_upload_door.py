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
from app.services.upload_service import (
    FileValidationError,
    validate_extension,
    validate_xml_payload,
)

GIB = Path(__file__).parent / "fixtures" / "gib_corpus" / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"

# The corpus is GİB's published package, 15 MB, kept out of the repository
# (.gitignore) like the other tests that read it. The door's own rules are
# checked below without it, so CI still proves them.
korpus_var = pytest.mark.skipif(not GIB.exists(), reason="GİB korpusu yerelde yok")

# A minimal UBL-TR document: enough for the door, which decides on the
# extension and the absence of a DTD, not on the invoice's contents.
_UBL_MINIMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>GIB2026000000001</ID>
</Invoice>"""

_BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<Invoice>&lol3;</Invoice>"""


def _gib_files() -> list[Path]:
    return sorted(p for p in GIB.glob("*.xml"))


def test_an_xml_invoice_passes_the_door():
    validate_extension("xml")          # no longer raises
    validate_xml_payload(_UBL_MINIMAL)  # no DTD, no entity
    assert "xml" in _UZANTILAR
    tanima = tani(_UBL_MINIMAL, "fatura.xml")
    assert (tanima.durum, tanima.tur, tanima.alan) == (KESIN, FINANSAL_BELGE, "cfo")


@korpus_var
@pytest.mark.parametrize("name", ["IDIS_Fatura.xml", "HASTANE.xml", "ISTISNA-1.xml"])
def test_gibs_own_invoices_pass_the_door(name: str):
    raw = (GIB / name).read_bytes()
    validate_extension("xml")          # no longer raises
    validate_xml_payload(raw)          # no DTD, no entity
    assert "xml" in _UZANTILAR
    tanima = tani(raw, name)
    assert (tanima.durum, tanima.tur, tanima.alan) == (KESIN, FINANSAL_BELGE, "cfo")


@korpus_var
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


def test_the_upload_page_refuses_xls_with_the_same_advice_as_baglan():
    """.xls passed the upload page's allowlist and then failed inside openpyxl."""
    with pytest.raises(FileValidationError, match="xlsx"):
        validate_extension("xls")


_EDEFTER_MINIMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<edefter:defter xmlns:edefter="http://www.edefter.gov.tr"><x/></edefter:defter>"""


def test_an_edefter_is_named_at_the_door_not_accepted_and_left_empty():
    """A journal went in as a "financial document" and the analysis ended with
    no transactions and no word why — nothing reads e-Defter yet."""
    from app.services.ingest.recognize import edefter_turu

    assert edefter_turu(_EDEFTER_MINIMAL) == "e-Defter (yevmiye / kebir)"
    assert edefter_turu(_UBL_MINIMAL) is None
    assert edefter_turu(b"tarih,tutar\n") is None


async def test_the_door_refuses_an_edefter_with_advice(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.services.ingest.ekle as ekle
    from app.config import get_settings
    from app.database import Base

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        out = await ekle.dosyalari_ekle(db, ekle.Sahip(org_id="o", user_id="u"),
                                        [("1234567808-201804-Y-000000.xml", _EDEFTER_MINIMAL)])
    await engine.dispose()
    d = out["dosyalar"][0]
    assert d["durum"] == ekle.REDDEDILDI
    assert "e-Defter" in d["mesaj"] and "banka ekstresini" in d["mesaj"]
    assert out["job_id"] is None


@korpus_var
def test_every_gib_edefter_sample_is_recognised():
    from app.services.ingest.recognize import edefter_turu

    klasor = GIB.parent.parent.parent / "e_defter" / "e-Defter Paketi" / "xml"
    dosyalar = sorted(klasor.glob("*.xml"))
    assert dosyalar
    for f in dosyalar:
        assert edefter_turu(f.read_bytes()) is not None, f.name
