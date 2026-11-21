"""Plan v10 G23 — a free-form invoice number is unique per counterparty and side, not alone.

`test_invoice_identity_review.py` holds the headline case (two suppliers, one number). Here:
the key itself, how names are normalised, and what the ledger and the open-item index do.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.main  # noqa: F401
from app.core.invoice_identity import (
    document_key,
    is_unique_id,
    key_party,
    lacks_counterparty,
    normalise_party,
    open_item_key,
    party_token,
    tax_number_in,
)
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services import ledger
from tests.db_helpers import gecici_oturum

ORG = "org-g23"


# ── what a name is ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "a, b",
    [
        ("Alfa Gıda A.Ş.", "ALFA GIDA AS"),
        ("Alfa Gıda A.Ş.", "alfa gıda anonim şirketi"),
        ("Alfa Gıda A.Ş.", "  Alfa   Gıda  A.S "),
        ("Beta Tekstil Ltd. Şti.", "BETA TEKSTİL LTD ŞTİ"),
        ("Beta Tekstil Ltd. Şti.", "Beta Tekstil Limited Şirketi"),
        ("Işık Ltd.Şti.", "ISIK LTD STI"),         # İ/I/ı/i and Ş all fold, and "Ltd.Şti." has no space
        ("IŞIK Ltd", "ışık ltd."),
        ("Yıldız, Tekstil", "YILDIZ TEKSTIL"),      # punctuation and diacritics-less exports
    ],
)
def test_spellings_of_one_supplier_are_one_name(a, b):
    assert normalise_party(a) is not None
    assert normalise_party(a) == normalise_party(b)
    assert party_token(ORG, a) == party_token(ORG, b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Alfa Ltd", "Alfa Gıda Ltd"),                  # a word of the name is not noise
        ("Alfa Sanayi A.Ş.", "Alfa Ticaret A.Ş."),     # "Sanayi"/"Ticaret" are not stripped: merging
        ("Beta Ltd", "Betta Ltd"),                      # suppliers loses a payable, splitting them does not
        ("Yıldız Tekstil", "Yıldız Teknoloji"),
        ("Kaya İnşaat", "Kaya Otomotiv"),
        ("Alfa Ltd", "Alfa Ltd 2"),
    ],
)
def test_near_names_are_not_one_supplier(a, b):
    assert party_token(ORG, a) != party_token(ORG, b)


def test_two_legal_forms_over_the_same_words_are_the_same_name():
    """Documented limit: only trailing legal forms come off, so "Alfa A.Ş." and "Alfa Ltd." are alike.

    The same words under two legal forms are, in practice, one trading relationship, and the
    two documents would still need the same number to meet.
    """
    assert normalise_party("Alfa A.Ş.") == normalise_party("Alfa Ltd. Şti.") == "alfa"


def test_a_name_that_is_only_a_legal_form_is_no_name():
    assert normalise_party("A.Ş.") is None
    assert normalise_party("Ltd. Şti.") is None
    assert normalise_party("  ") is None
    assert normalise_party(None) is None
    assert party_token(ORG, "A.Ş.") is None


def test_a_tax_number_beats_the_name_and_survives_spelling():
    vkn = "1234567890"  # passes the VKN check digit
    assert tax_number_in(f"Alfa Gıda A.Ş. (VKN {vkn})") == vkn
    assert party_token(ORG, f"Alfa Gıda A.Ş. VKN: {vkn}") == party_token(ORG, f"ALFA GIDA {vkn}")
    assert party_token(ORG, f"Alfa {vkn}").startswith("t")
    assert party_token(ORG, "Alfa Gıda").startswith("n")


def test_a_number_that_fails_its_check_digits_is_not_a_tax_number():
    assert tax_number_in("Alfa 1234567891") is None            # VKN check digit wrong
    assert tax_number_in("Alfa 12345678901") is None           # TCKN rules not met
    assert tax_number_in("10000000146") == "10000000146"       # a valid TCKN
    assert tax_number_in("12345678901234") is None             # too long to be either


def test_the_token_is_salted_by_the_organisation_and_holds_no_clear_identifier():
    token = party_token("org-a", "Alfa Gıda A.Ş. 1234567890")
    assert token != party_token("org-b", "Alfa Gıda A.Ş. 1234567890")
    assert "1234567890" not in document_key("org-a", "A-1", "Alfa 1234567890", "income")
    assert "alfa" not in document_key("org-a", "A-1", "Alfa Ltd", "income").lower()


# ── what an invoice's key is ─────────────────────────────────────────────────────────────────


def test_a_free_form_number_carries_its_side_and_counterparty():
    sale = document_key(ORG, "A-1", "Alfa Ltd", "income")
    purchase = document_key(ORG, "A-1", "Alfa Ltd", "expense")
    assert sale.startswith("inv:s:n") and sale.endswith(":A-1")
    assert purchase.startswith("inv:p:n") and purchase.endswith(":A-1")
    assert sale != purchase                                         # same number, same party, other side
    assert document_key(ORG, "A-1", "Beta Ltd", "income") != sale   # same number, other party
    assert document_key(ORG, "a-1", "ALFA LTD.", "income") == sale  # same document, written differently


@pytest.mark.parametrize("number", ["f47ac10b-58cc-4372-a567-0e02b2c3d479", "GIB2024000000050"])
def test_a_uuid_or_gib_number_names_its_document_whoever_issued_it(number):
    assert is_unique_id(number)
    assert document_key(ORG, number, "Alfa Ltd", "income") == f"doc:{number.upper() if number[0] == 'G' else number}"
    assert document_key(ORG, number, "Beta Ltd", "expense") == document_key(ORG, number, None, None)


def test_no_counterparty_keeps_the_old_key_and_is_flagged_not_guessed():
    for counterparty in (None, "", "   ", "A.Ş."):
        key = document_key(ORG, "A-1", counterparty, "income")
        assert key == "doc:A-1"
        assert lacks_counterparty(key)
    assert document_key(ORG, "A-1", "Alfa Ltd", None) == "doc:A-1"  # an unknown side is not guessed either
    assert not lacks_counterparty(document_key(ORG, "A-1", "Alfa Ltd", "income"))
    assert not lacks_counterparty("doc:GIB2024000000050")


def test_unknown_suppliers_do_not_collapse_into_one_identity():
    """Two rows with no counterparty and different numbers stay two; no row is given a shared 'unknown'."""
    assert document_key(ORG, "A-1", None, "income") != document_key(ORG, "A-2", None, "income")
    assert party_token(ORG, None) is None


def test_open_item_key_is_the_bare_number_or_the_whole_key():
    assert open_item_key("doc:A-1") == "A-1"
    sale = document_key(ORG, "A-1", "Alfa Ltd", "income")
    assert open_item_key(sale) == sale
    assert len(sale) + len("~k12-yeni") <= 120                     # source_record_id is 120 wide
    assert len(document_key(ORG, "X" * 64, "Alfa", "income")) <= 128   # open_items.document_id is 128 wide
    assert key_party(sale) == (sale.split(":")[1], sale.split(":")[2])
    assert key_party("doc:A-1") is None


# ── the ledger ───────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    async with gecici_oturum() as session:
        yield session


async def _org(db) -> str:
    org_id = f"org-g23-{uuid.uuid4().hex[:8]}"
    db.add(Organization(id=org_id, name="G23", slug=f"slug-{org_id}"))
    await db.commit()
    return org_id


async def _upload(db, org_id, *rows: dict, days_ago: int = 3):
    """One completed job of invoice rows: {document_id, counterparty, cents, type?}."""
    job = AnalysisJob(
        id=str(uuid.uuid4()), org_id=org_id, status=JobStatus.COMPLETED, filename="f.csv",
        file_path="/tmp/f.csv", file_type="csv",
    )
    db.add(job)
    await db.flush()
    for r in rows:
        db.add(Transaction(
            id=str(uuid.uuid4()), job_id=job.id, transaction_date=datetime.now(UTC) - timedelta(days=days_ago),
            amount_kurus=r["cents"], type=r.get("type", "income"), currency="TRY",
            category="revenue" if r.get("type", "income") == "income" else "cogs",
            vendor=r.get("counterparty"), counterparty=r.get("counterparty"),
            description=f"Fatura {r['document_id']}", document_id=r["document_id"],
            due_date=datetime.now(UTC) + timedelta(days=20), date_is_estimated=False,
        ))
    await db.commit()
    return await ledger.append_job(db, job.id)


async def _rows(db, org_id) -> list[CanonicalTransaction]:
    return list((await db.execute(
        select(CanonicalTransaction).where(CanonicalTransaction.org_id == org_id)
        .order_by(CanonicalTransaction.source_record_id)
    )).scalars())


async def _items(db, org_id) -> list[OpenItem]:
    return list((await db.execute(select(OpenItem).where(OpenItem.org_id == org_id))).scalars())


@pytest.mark.asyncio
async def test_two_suppliers_with_one_number_are_two_rows_and_two_open_items(db):
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ltd", "cents": 100_000, "type": "expense"})
    counts = await _upload(
        db, org_id, {"document_id": "A-1", "counterparty": "Beta Ltd", "cents": 250_000, "type": "expense"}
    )
    assert (counts["new"], counts["already"], counts["possible_duplicate"]) == (1, 0, 0)
    assert sorted(r.amount_cents for r in await _rows(db, org_id)) == [100_000, 250_000]
    items = await _items(db, org_id)
    assert sorted(i.amount_cents for i in items) == [100_000, 250_000]   # both payables reach the radar
    assert len({i.document_id for i in items}) == 2
    summary = await ledger.ledger_summary(db, org_id)
    assert summary["open_items"]["payable_cents"] == 350_000


@pytest.mark.asyncio
async def test_the_same_supplier_sending_the_same_invoice_again_is_one_document(db):
    org_id = await _org(db)
    first = {"document_id": "A-1", "counterparty": "Alfa Gıda A.Ş.", "cents": 100_000}
    await _upload(db, org_id, first)
    counts = await _upload(db, org_id, {**first, "counterparty": "ALFA GIDA ANONIM SIRKETI"})
    assert (counts["new"], counts["already"]) == (0, 1)
    assert len(await _rows(db, org_id)) == 1 and len(await _items(db, org_id)) == 1


@pytest.mark.asyncio
async def test_the_same_number_from_one_party_in_two_directions_is_two_documents(db):
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ltd", "cents": 100_000, "type": "income"})
    counts = await _upload(
        db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ltd", "cents": 100_000, "type": "expense"}
    )
    assert counts["new"] == 1
    assert {r.direction for r in await _rows(db, org_id)} == {"income", "expense"}
    assert {i.direction for i in await _items(db, org_id)} == {"receivable", "payable"}


@pytest.mark.asyncio
async def test_two_spellings_with_the_same_number_and_amount_are_held_for_a_person(db):
    """One name inside the other, same number, same amount, same weeks: one supplier's invoice read twice, or not."""
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Gıda San. ve Tic. A.Ş.", "cents": 100_000})
    counts = await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Gıda A.Ş.", "cents": 100_000})
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)
    assert len(await _rows(db, org_id)) == 2          # written, not dropped: a person decides
    assert len(await _items(db, org_id)) == 1         # and the held one is not yet a payable


@pytest.mark.asyncio
async def test_different_names_with_the_same_number_and_amount_are_held_for_a_person(db):
    """Not a gate any more: a longer form of a name, or an OCR typo, is the same invoice as often as not."""
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Sanayi A.Ş.", "cents": 100_000})
    counts = await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ticaret A.Ş.", "cents": 100_000})
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)
    assert len(await _items(db, org_id)) == 1


@pytest.mark.asyncio
async def test_a_near_name_with_the_same_number_and_another_amount_is_another_supplier(db):
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Sanayi A.Ş.", "cents": 100_000})
    counts = await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ticaret A.Ş.", "cents": 120_000})
    assert (counts["new"], counts["possible_duplicate"]) == (1, 0)
    assert len(await _items(db, org_id)) == 2


@pytest.mark.asyncio
async def test_the_same_amount_from_a_name_and_a_tax_number_stays_a_suspicion(db):
    """A name against a tax number may be one company: the duplicate window still holds it."""
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Gıda A.Ş.", "cents": 100_000})
    counts = await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa 1234567890", "cents": 100_000})
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)


@pytest.mark.asyncio
async def test_a_number_without_a_counterparty_is_counted_under_the_old_key_and_flagged(db):
    org_id = await _org(db)
    counts = await _upload(db, org_id, {"document_id": "A-1", "counterparty": None, "cents": 100_000})
    assert counts["new"] == 1 and counts["no_counterparty"] == 1
    assert [r.source_record_id for r in await _rows(db, org_id)] == ["doc:A-1"]
    assert await _items(db, org_id) == []                       # no counterparty, no open item (as before)
    job = (await db.execute(select(AnalysisJob).where(AnalysisJob.org_id == org_id))).scalars().one()
    assert job.result_metadata["ledger"]["no_counterparty"] == 1
    summary = await ledger.ledger_summary(db, org_id)
    assert summary["last_upload"]["no_counterparty"] == 1


@pytest.mark.asyncio
async def test_unknown_counterparties_are_not_one_identity(db):
    org_id = await _org(db)
    await _upload(
        db, org_id,
        {"document_id": "A-1", "counterparty": None, "cents": 100_000},
        {"document_id": "A-2", "counterparty": None, "cents": 200_000},
    )
    assert len(await _rows(db, org_id)) == 2


@pytest.mark.asyncio
async def test_a_gib_number_is_still_one_document_across_suppliers_fields(db):
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "GIB2024000000001", "counterparty": "Alfa Ltd", "cents": 100_000})
    counts = await _upload(db, org_id, {"document_id": "GIB2024000000001", "counterparty": None, "cents": 100_000})
    assert (counts["new"], counts["already"], counts["no_counterparty"]) == (0, 1, 0)
    assert (await _rows(db, org_id))[0].source_record_id == "doc:GIB2024000000001"


@pytest.mark.asyncio
async def test_a_category_correction_finds_its_row_under_the_new_key(db):
    from app.models.category_override import CategoryOverride
    from app.models.user import User
    from app.services.ledger_correction import apply_category_correction

    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ltd", "cents": 100_000, "type": "expense"})
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Beta Ltd", "cents": 250_000, "type": "expense"})
    beta = next(r for r in await _rows(db, org_id) if r.amount_cents == 250_000)
    job_tx = (await db.execute(
        select(Transaction).where(Transaction.amount_kurus == 250_000, Transaction.job_id == beta.source_job_id)
    )).scalars().one()
    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", org_id=org_id)
    db.add(user)
    await db.flush()
    result = await apply_category_correction(db, job_tx, org_id, "rent", user)
    await db.commit()
    assert result["ledger"] == "updated" and result["source_record_id"] == beta.source_record_id
    rows = {r.amount_cents: r.category for r in await _rows(db, org_id)}
    assert rows == {100_000: "cogs", 250_000: "rent"}              # Alfa's row is untouched
    kept = (await db.execute(select(CategoryOverride).where(CategoryOverride.org_id == org_id))).scalars().one()
    assert kept.source_record_id == beta.source_record_id


@pytest.mark.asyncio
async def test_open_item_unique_index_is_per_document_not_per_number(db):
    org_id = await _org(db)
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ltd", "cents": 100_000})
    n_before = (await db.execute(select(func.count()).select_from(OpenItem))).scalar_one()
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Alfa Ltd", "cents": 100_000})   # again: no new item
    await _upload(db, org_id, {"document_id": "A-1", "counterparty": "Beta Ltd", "cents": 130_000})   # another: a new one
    n_after = (await db.execute(select(func.count()).select_from(OpenItem))).scalar_one()
    assert n_after == n_before + 1
