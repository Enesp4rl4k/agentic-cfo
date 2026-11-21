"""G23 review S3: a number that keeps meeting documents that are not it.

- the same file read again maps to the variant it wrote, whatever the OCR now says about the amount;
- a key stops growing at MAX_VARIANTS and asks for a person ("çok sayıda sürüm");
- a category override recorded on a variant survives a rerun instead of reverting to the base row's.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.models.canonical_transaction import CanonicalTransaction
from app.models.category_override import CategoryOverride
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger import append_job
from app.services.ledger_correction import apply_category_correction, apply_overrides
from app.services.ledger_documents import DUPLICATE_WINDOW_DAYS, MAX_VARIANTS
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_duplicate_resolution_radar import (
    SHORT,
    _held,
    _radar_out,
    _resolve,
    _rows,
    _upload,
)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _set_amount(client, job_id, cents):
    async with client._maker() as db:
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().one()
        tx.amount_kurus = cents
        await db.commit()


async def test_the_same_file_read_again_maps_to_its_variant_even_when_the_amount_reads_differently(client):
    _, org_id, _ = await kullanici(client, "var-ocr@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    job2, counts = await _upload(client, org_id, who=SHORT, cents=150_000)
    assert counts["possible_duplicate"] == 1
    before = {r.source_record_id for r in await _rows(client, org_id)}

    for noisy in (150_001, 149_999, 150_100):                        # OCR noise on every re-read
        await _set_amount(client, job2, noisy)
        async with client._maker() as db:
            again = await append_job(db, job2)
        assert (again["new"], again["possible_duplicate"], again["many_versions"]) == (0, 0, 0)
    assert {r.source_record_id for r in await _rows(client, org_id)} == before   # no new ~v row, ever
    assert len([r for r in await _rows(client, org_id) if r.ledger_status == "possible_duplicate"]) == 1


async def test_a_key_stops_growing_at_the_cap_and_says_so(client):
    headers, org_id, _ = await kullanici(client, "var-cap@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    for i in range(MAX_VARIANTS):
        _, counts = await _upload(client, org_id, who=SHORT, cents=110_000 + i * 10_000)
        assert counts["possible_duplicate"] == 1 and counts["many_versions"] == 0
    n = len(await _rows(client, org_id))
    assert n == 1 + MAX_VARIANTS

    _, counts = await _upload(client, org_id, who=SHORT, cents=333_333)          # one more reading
    assert (counts["new"], counts["possible_duplicate"], counts["many_versions"]) == (0, 0, 1)
    assert len(await _rows(client, org_id)) == n                                    # it joined the nearest version
    summary = (await client.get("/api/v1/ledger/summary", headers=headers)).json()["data"]
    assert summary["last_upload"]["many_versions"] == 1


async def test_the_held_list_says_when_a_number_has_too_many_versions(client):
    headers, org_id, _ = await kullanici(client, "var-reason@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    for i in range(MAX_VARIANTS):
        await _upload(client, org_id, who=SHORT, cents=110_000 + i * 10_000)
    listed = (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]
    assert len(listed) == MAX_VARIANTS
    assert {x["reason"] for x in listed} == {"many_versions"}


async def test_one_named_window_and_it_is_three_days():
    """The anomaly agent's duplicate check; documents with numbers are not paired by it (see `repeats`)."""
    assert DUPLICATE_WINDOW_DAYS == 3


# ── a person's override on a variant ─────────────────────────────────────────────────────────


async def test_an_override_on_a_variant_survives_a_rerun_and_never_reverts_to_the_base_rows(client):
    headers, org_id, user_id = await kullanici(client, "var-override@example.com")
    job1, _ = await _upload(client, org_id, who=SHORT, cents=100_000)
    job2, _ = await _upload(client, org_id, who=SHORT, cents=150_000)
    await _resolve(client, headers, (await _held(client, org_id)).id, "keep")

    async with client._maker() as db:
        user = await db.get(User, user_id)
        for job, category in ((job1, "utilities"), (job2, "rent")):
            tx = (await db.execute(select(Transaction).where(Transaction.job_id == job))).scalars().one()
            await apply_category_correction(db, tx, org_id, category, user)
        await db.commit()
        kept = {o.category for o in (await db.execute(
            select(CategoryOverride).where(CategoryOverride.org_id == org_id))).scalars()}
    assert kept == {"utilities", "rent"}

    # A rerun writes fresh Transaction rows (the old ones are replaced) with the file's own categories.
    for job in (job1, job2):
        async with client._maker() as db:
            tx = (await db.execute(select(Transaction).where(Transaction.job_id == job))).scalars().one()
            tx.category, tx.category_source = "cogs", None
            await db.flush()
            set_ = await apply_overrides(db, org_id, job)
            await db.commit()
            assert set_ == 1
    async with client._maker() as db:
        by_job = {
            t.job_id: t.category for t in (await db.execute(select(Transaction))).scalars()
        }
    assert by_job == {job1: "utilities", job2: "rent"}              # each document keeps its own correction


async def test_a_variants_override_survives_a_rerun_whose_amount_reads_differently(client):
    headers, org_id, user_id = await kullanici(client, "var-override2@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    job2, _ = await _upload(client, org_id, who=SHORT, cents=150_000)
    await _resolve(client, headers, (await _held(client, org_id)).id, "keep")
    async with client._maker() as db:
        user = await db.get(User, user_id)
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job2))).scalars().one()
        await apply_category_correction(db, tx, org_id, "rent", user)
        await db.commit()
    await _set_amount(client, job2, 150_007)                           # the rerun reads it a little differently
    async with client._maker() as db:
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job2))).scalars().one()
        tx.category = "cogs"
        await db.flush()
        assert await apply_overrides(db, org_id, job2) == 1
        assert tx.category == "rent"


async def test_the_variants_own_row_not_the_first_is_what_a_correction_changes(client):
    headers, org_id, user_id = await kullanici(client, "var-row@example.com")
    _job1, _ = await _upload(client, org_id, who=SHORT, cents=100_000)
    job2, _ = await _upload(client, org_id, who=SHORT, cents=150_000)
    await _resolve(client, headers, (await _held(client, org_id)).id, "keep")
    async with client._maker() as db:
        user = await db.get(User, user_id)
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job2))).scalars().one()
        result = await apply_category_correction(db, tx, org_id, "rent", user)
        await db.commit()
    assert "~v" in result["source_record_id"]
    rows = {r.amount_cents: r.category for r in await _rows(client, org_id)}
    assert rows == {100_000: "cogs", 150_000: "rent"}
    assert await _radar_out(client, org_id) == 250_000


def test_row_type_is_importable() -> None:
    assert CanonicalTransaction.__tablename__ == "canonical_transactions"
