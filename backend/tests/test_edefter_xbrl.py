"""e-Defter (XBRL GL) — doğrulayan, GİB'in kendi şeması.

The predecessor of this generator emitted a flat listing of its own design
under GİB's namespace and reported `is_valid: True`, meaning only that debit
equalled credit. Validated against the edefter.xsd GİB publishes — the same
schema its own sample passes — it was rejected at the root element, before any
content was examined.

So the check here is not "does our code agree with our code". It is the
authority's schema, applied to the authority's sample first (to prove the
harness works) and then to ours.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.edefter_xbrl import (
    EDefterError,
    EDefterXBRLGenerator,
    LedgerOwner,
)

CORPUS = Path(__file__).resolve().parent / "fixtures" / "gib_corpus" / "e_defter"
PKG = CORPUS / "e-Defter Paketi"
XSD = PKG / "xsd" / "edefter.xsd"
GIB_JOURNAL = PKG / "xml" / "1234567808-201804-Y-000000.xml"

OWNER = LedgerOwner(
    vkn="1234567808",
    title="TechNova Yazılım A.Ş.",
    creator="SMMM Ali Can",
    fiscal_year_start="2024-01-01",
    fiscal_year_end="2024-12-31",
    software_name="1234567808##C-Suite##C-Suite e-Defter##1.0",
)

ENTRIES = [
    {
        "kayit_id": "e1",
        "tarih": "2024-01-15T00:00:00",
        "aciklama": "Ocak yazılım lisans geliri",
        "kaynak_islem_id": "tx-1",
        "satirlar": [
            {"hesap_kodu": "120.01", "hesap_adi": "Alıcılar", "borc": 28_500_00, "alacak": 0},
            {"hesap_kodu": "600.01", "hesap_adi": "Yurtiçi Satışlar", "borc": 0, "alacak": 23_750_00},
            {"hesap_kodu": "391.01", "hesap_adi": "Hesaplanan KDV", "borc": 0, "alacak": 4_750_00},
        ],
    },
    {
        "kayit_id": "e2",
        "tarih": "2024-01-20T00:00:00",
        "aciklama": "Ofis kirası",
        "satirlar": [
            {"hesap_kodu": "770.01", "hesap_adi": "Genel Yönetim Giderleri", "borc": 12_000_00, "alacak": 0},
            {"hesap_kodu": "102.01", "hesap_adi": "Bankalar", "borc": 0, "alacak": 12_000_00},
        ],
    },
]


def _journal():
    return EDefterXBRLGenerator.generate_journal(ENTRIES, period="2024-01", owner=OWNER)


def _ledger():
    return EDefterXBRLGenerator.generate_ledger(ENTRIES, period="2024-01", owner=OWNER)


# ── Schema validation, against GİB's published XSD ───────────────────────────

def _schema():
    """Build the validator, or skip with the reason.

    edefter.xsd imports the XBRL instance schema over HTTP, so this needs
    network the first time. A machine without it should say so rather than
    quietly pass.
    """
    lxml_etree = pytest.importorskip("lxml.etree", reason="lxml kurulu değil")
    if not XSD.is_file():
        pytest.skip("GİB e-Defter paketi yok — python scripts/fetch_gib_corpus.py")
    try:
        return lxml_etree, lxml_etree.XMLSchema(lxml_etree.parse(str(XSD)))
    except Exception as exc:  # pragma: no cover - offline machines
        pytest.skip(f"edefter.xsd derlenemedi (ağ gerekebilir): {exc}")


def test_the_harness_validates_gibs_own_ledger() -> None:
    """If the authority's own file does not pass, the check below proves nothing."""
    etree, schema = _schema()
    assert schema.validate(etree.parse(str(GIB_JOURNAL))), (
        f"GİB'in kendi örneği şemadan geçmedi: {schema.error_log}"
    )


@pytest.mark.parametrize("kind", ["yevmiye", "kebir"])
def test_generated_ledger_validates_against_gib_schema(kind: str) -> None:
    etree, schema = _schema()
    pkg = _journal() if kind == "yevmiye" else _ledger()
    doc = etree.fromstring(pkg.xml.encode("utf-8"))
    assert schema.validate(doc), (
        f"{kind} şemadan geçmedi:\n  "
        + "\n  ".join(e.message for e in schema.error_log[:5])
    )


def test_root_is_defter_in_gibs_namespace() -> None:
    """`edefter:journal` — the old root — does not exist in the schema at all."""
    pkg = _journal()
    assert "<edefter:defter" in pkg.xml
    assert "http://www.edefter.gov.tr" in pkg.xml
    assert "edefter:journal" not in pkg.xml


def test_qname_prefixes_are_declared() -> None:
    """`iso4217:TRY` and `iso639:tr` live in element text.

    ElementTree emits xmlns declarations only for namespaces used in tags and
    attribute names, so without explicit declarations the schema rejects the
    currency unit and the language — which is exactly what it should do.
    """
    xml = _journal().xml
    assert 'xmlns:iso4217="http://www.xbrl.org/2003/iso4217"' in xml
    assert "iso4217:TRY" in xml


def test_hash_value_is_unqualified() -> None:
    """edefter.xsd declares HashValue locally with no elementFormDefault, so it
    belongs to no namespace."""
    xml = _journal().xml
    assert "<HashValue>" in xml
    assert "<edefter:HashValue>" not in xml


# ── What the ledger says about itself ────────────────────────────────────────

def test_it_never_claims_to_be_filable() -> None:
    """Structurally complete and legally incomplete are different things, and a
    single "valid" flag blurs them. Filing needs a mali mühür we do not have."""
    pkg = _journal()
    assert pkg.filable is False
    assert "mali mühür" in pkg.unfilable_reason


def test_file_name_follows_gib_convention() -> None:
    assert _journal().file_name == "1234567808-202401-Y-000000.xml"
    assert _ledger().file_name == "1234567808-202401-K-000000.xml"


def test_amounts_are_lira_derived_from_integer_kurus() -> None:
    """Kuruş are integers precisely so the single division happens here."""
    xml = _journal().xml
    assert ">28500.00<" in xml
    assert ">23750.00<" in xml
    assert ">4750.00<" in xml


def test_debit_and_credit_are_marked_per_line() -> None:
    xml = _journal().xml
    assert xml.count(">D<") == 2   # 120 and 770
    assert xml.count(">C<") == 3   # 600, 391, 102


def test_journal_balances() -> None:
    pkg = _journal()
    assert pkg.is_balanced
    assert pkg.total_debit_kurus == 40_500_00
    assert pkg.line_count == 5


# ── Kebir is the journal read down the account column ────────────────────────

def test_ledger_groups_by_account_without_inventing_movements() -> None:
    """GİB checks that yevmiye and kebir agree. Deriving both from the same rows
    is the only way they can."""
    journal, ledger = _journal(), _ledger()
    assert ledger.line_count == journal.line_count
    assert ledger.total_debit_kurus == journal.total_debit_kurus
    assert ledger.total_credit_kurus == journal.total_credit_kurus
    # Five lines across five distinct accounts in this fixture.
    assert ledger.entry_count == 5


def test_ledger_declares_itself_a_ledger() -> None:
    assert ">ledger<" in _ledger().xml
    assert ">journal<" in _journal().xml


# ── Refusals ─────────────────────────────────────────────────────────────────

def test_a_line_carrying_both_sides_is_refused() -> None:
    """One detail is one side. A row with both is two rows merged upstream, and
    splitting it here would invent a structure the sealed record does not have.
    """
    bad = [{
        "kayit_id": "x",
        "tarih": "2024-01-01T00:00:00",
        "satirlar": [{"hesap_kodu": "100", "hesap_adi": "Kasa", "borc": 100, "alacak": 50}],
    }]
    with pytest.raises(EDefterError, match="hem borç hem alacak"):
        EDefterXBRLGenerator.generate_journal(bad, period="2024-01", owner=OWNER)


@pytest.mark.parametrize("bad_vkn", ["", "123", "123456789", "123456789012", "abcdefghij"])
def test_a_ledger_needs_a_real_vkn(bad_vkn: str) -> None:
    with pytest.raises(EDefterError, match="VKN"):
        EDefterXBRLGenerator.generate_journal(
            ENTRIES, period="2024-01",
            owner=LedgerOwner(vkn=bad_vkn, title="X"),
        )


@pytest.mark.parametrize("bad_period", ["2024", "2024-13", "01-2024", ""])
def test_period_must_be_year_month(bad_period: str) -> None:
    with pytest.raises(EDefterError, match="dönem"):
        EDefterXBRLGenerator.generate_journal(
            ENTRIES, period=bad_period, owner=OWNER
        )


def test_period_end_is_the_last_day_of_the_month() -> None:
    for period, expected in (
        ("2024-01", "2024-01-31"),
        ("2024-02", "2024-02-29"),   # leap year
        ("2023-02", "2023-02-28"),
        ("2024-12", "2024-12-31"),
    ):
        # Entries dated inside the period: the generator refuses another
        # month's posting, so the fixture moves with the month under test.
        moved = [{**e, "tarih": f"{period}-15T00:00:00"} for e in ENTRIES]
        pkg = EDefterXBRLGenerator.generate_journal(
            moved, period=period, owner=OWNER
        )
        assert f">{expected}<" in pkg.xml, period


def test_blank_owner_details_are_omitted_not_invented() -> None:
    """A ledger carrying a plausible address nobody entered is worse than one
    carrying none."""
    pkg = EDefterXBRLGenerator.generate_journal(
        ENTRIES, period="2024-01",
        owner=LedgerOwner(vkn="1234567808", title="Yalın A.Ş."),
    )
    assert "organizationAddress" not in pkg.xml
    assert "entityPhoneNumber" not in pkg.xml
    assert "creator" not in pkg.xml
