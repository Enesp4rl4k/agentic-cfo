"""G23 review: one supplier's invoice split by its spelling must not count twice in the cash radar.

Every scenario asserts the RADAR total (what the user plans cash on), not only the ledger flag, before
and after each resolution: a row held as a possible duplicate puts no money in the radar; "separate"
opens its item; "same" leaves one, and teaches the ledger that the two names are one supplier.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.counterparty_alias import CounterpartyAlias
from app.models.decision import Decision
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.services.cash_radar import compute_cash_radar
from app.services.ledger import append_job
from tests.api_helpers import bellek_istemcisi, kullanici

FULL = "Alfa Gıda San. ve Tic. A.Ş."
SHORT = "Alfa Gıda A.Ş."
VKN = "Alfa Gıda 1234567890"
TODAY = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _upload(client, org_id, *, number="A-1", who=SHORT, cents=100_000, days_ago=2, due_in=20) -> tuple[str, dict]:
    async with client._maker() as db:
        job = AnalysisJob(id=str(uuid.uuid4()), org_id=org_id, status=JobStatus.COMPLETED, filename="f.csv",
                          file_path="/f.csv", file_type="csv")
        db.add(job)
        await db.flush()
        db.add(Transaction(
            id=str(uuid.uuid4()), job_id=job.id, transaction_date=TODAY - timedelta(days=days_ago),
            amount_kurus=cents, type="expense", currency="TRY", category="cogs", vendor=who, counterparty=who,
            description=f"Alış {number}", document_id=number, due_date=(TODAY + timedelta(days=due_in)).date(),
            date_is_estimated=False,
        ))
        await db.commit()
        return job.id, await append_job(db, job.id)


async def _radar_out(client, org_id) -> int:
    """What the radar plans to pay: every payable it carries, whichever bucket it falls in."""
    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=TODAY.date())
    return (sum(w.outflow_cents for w in radar.weeks) + radar.undated_payables_cents
            + radar.beyond_horizon_cents)


async def _rows(client, org_id) -> list[CanonicalTransaction]:
    async with client._maker() as db:
        return list((await db.execute(
            select(CanonicalTransaction).where(CanonicalTransaction.org_id == org_id)
            .order_by(CanonicalTransaction.created_at)
        )).scalars())


async def _held(client, org_id) -> CanonicalTransaction:
    return next(r for r in await _rows(client, org_id) if r.ledger_status == "possible_duplicate")


async def _resolve(client, headers, row_id, action) -> dict:
    res = await client.post(f"/api/v1/ledger/rows/{row_id}/resolve", headers=headers, json={"action": action})
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def _confirm(client, headers, row_id):
    return await client.post("/api/v1/ledger/counterparty-aliases", headers=headers,
                             json={"row_id": row_id, "confirm": True})


async def _aliases(client, org_id) -> list[CounterpartyAlias]:
    async with client._maker() as db:
        return list((await db.execute(
            select(CounterpartyAlias).where(CounterpartyAlias.org_id == org_id))).scalars())


async def _items(client, org_id) -> list[OpenItem]:
    async with client._maker() as db:
        return list((await db.execute(select(OpenItem).where(OpenItem.org_id == org_id))).scalars())


# ── two spellings of one supplier ────────────────────────────────────────────────────────────


async def test_a_split_is_held_and_counted_once_until_a_person_answers(client):
    headers, org_id, _ = await kullanici(client, "split1@example.com")
    await _upload(client, org_id, who=FULL)
    _, counts = await _upload(client, org_id, who=SHORT)

    assert counts["possible_duplicate"] == 1 and counts["new"] == 0
    assert len(await _items(client, org_id)) == 1               # the held row opened no item
    assert await _radar_out(client, org_id) == 100_000          # once, not 200.000
    listed = (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]
    assert listed[0]["reason"] == "same_number_may_be_a_different_document"
    assert {listed[0]["counterparty"], listed[0]["matches"][0]["counterparty"]} == {FULL, SHORT}


async def test_exclude_alone_teaches_nothing_and_proposes_the_alias(client):
    headers, org_id, _ = await kullanici(client, "split2@example.com")
    await _upload(client, org_id, who=FULL)
    await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)

    done = await _resolve(client, headers, held.id, "exclude")

    assert await _radar_out(client, org_id) == 100_000          # still once, after the answer
    assert len(await _items(client, org_id)) == 1
    assert await _aliases(client, org_id) == []                  # excluding is not a statement about suppliers
    proposal = done["proposed_alias"]
    assert {proposal["alias_name"], proposal["canonical_name"]} == {FULL, SHORT}
    assert proposal["confirmation_text"] == f"Bundan sonra {SHORT} ve {FULL} aynı tedarikçi sayılacak."
    async with client._maker() as db:
        decisions = (await db.execute(select(Decision).where(Decision.org_id == org_id))).scalars().all()
    assert [(d.kind, d.outcome, d.decided_via) for d in decisions] == [("duplicate_resolution", "same_document", "human")]


async def test_confirming_the_alias_is_its_own_decision_and_stops_the_splitting(client):
    headers, org_id, user_id = await kullanici(client, "split2b@example.com")
    await _upload(client, org_id, who=FULL)
    job2, _ = await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)
    await _resolve(client, headers, held.id, "exclude")

    res = await _confirm(client, headers, held.id)
    assert res.status_code == 200, res.text
    (alias,) = await _aliases(client, org_id)
    assert (alias.org_id, alias.created_by, alias.revoked_at) == (org_id, user_id, None)
    async with client._maker() as db:
        decisions = (await db.execute(
            select(Decision).where(Decision.org_id == org_id).order_by(Decision.decided_at))).scalars().all()
    assert [(d.kind, d.outcome) for d in decisions] == [
        ("duplicate_resolution", "same_document"), ("counterparty_alias", "created")]
    own = decisions[1]
    assert own.reason == f"Bundan sonra {SHORT} ve {FULL} aynı tedarikçi sayılacak."
    assert own.before["active"] is False and own.after["active"] is True
    assert alias.decision_id == own.id

    # The same invoice under either name, next month or on a rerun, is one document and no new question.
    _, again = await _upload(client, org_id, who=SHORT)
    assert (again["new"], again["possible_duplicate"], again["already"]) == (0, 0, 1)
    _, other = await _upload(client, org_id, who=FULL)
    assert (other["new"], other["possible_duplicate"]) == (0, 0)
    async with client._maker() as db:
        rerun = await append_job(db, job2)                       # the job that was held, read again
    assert (rerun["new"], rerun["possible_duplicate"]) == (0, 0)
    assert await _radar_out(client, org_id) == 100_000
    assert len(await _rows(client, org_id)) == 2                 # the kept row and the excluded one: nothing grew


async def _user_id(client, email) -> str:
    from app.models.user import User

    async with client._maker() as db:
        return str((await db.execute(select(User.id).where(User.email == email))).scalar_one())


async def test_separate_documents_both_count_once_a_person_says_so(client):
    headers, org_id, _ = await kullanici(client, "split3@example.com")
    await _upload(client, org_id, who=FULL)
    await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)

    done = await _resolve(client, headers, held.id, "keep")

    assert done["open_item"] == "opened" and done["proposed_alias"] is None
    assert len(await _items(client, org_id)) == 2
    assert await _radar_out(client, org_id) == 200_000
    assert await _aliases(client, org_id) == []
    # Neither name is asked about again.
    _, again = await _upload(client, org_id, who=SHORT)
    assert (again["new"], again["possible_duplicate"]) == (0, 0)
    assert await _radar_out(client, org_id) == 200_000


async def test_a_vkn_on_one_upload_and_a_name_on_the_next_are_one_supplier_once_confirmed(client):
    headers, org_id, _ = await kullanici(client, "vkn@example.com")
    await _upload(client, org_id, who=VKN)
    _, counts = await _upload(client, org_id, who=SHORT)
    assert counts["possible_duplicate"] == 1 and await _radar_out(client, org_id) == 100_000

    held = await _held(client, org_id)
    await _resolve(client, headers, held.id, "exclude")
    assert await _radar_out(client, org_id) == 100_000
    assert (await _confirm(client, headers, held.id)).status_code == 200
    (alias,) = await _aliases(client, org_id)
    assert alias.canonical_token.startswith("t") and alias.alias_token.startswith("n")

    _, again = await _upload(client, org_id, who=SHORT)
    assert (again["new"], again["possible_duplicate"], again["already"]) == (0, 0, 1)


async def test_the_same_invoice_a_few_weeks_apart_is_still_held(client):
    headers, org_id, _ = await kullanici(client, "apart@example.com")
    await _upload(client, org_id, who=FULL, days_ago=40)
    _, counts = await _upload(client, org_id, who=SHORT, days_ago=20)   # 20 days later: outside the 3-day window

    assert counts["possible_duplicate"] == 1
    assert await _radar_out(client, org_id) == 100_000
    await _resolve(client, headers, (await _held(client, org_id)).id, "exclude")
    assert await _radar_out(client, org_id) == 100_000


async def test_two_suppliers_numbering_alike_months_apart_are_two_payables(client):
    """E-invoice numbering restarts per supplier: same number and amount far apart in time is no evidence."""
    _, org_id, _ = await kullanici(client, "months@example.com")
    await _upload(client, org_id, who=FULL, days_ago=100)
    _, counts = await _upload(client, org_id, who=SHORT, days_ago=20)
    assert (counts["new"], counts["possible_duplicate"]) == (1, 0)
    assert await _radar_out(client, org_id) == 200_000


async def test_the_same_number_and_amount_from_plainly_different_companies_is_held_for_a_person(client):
    """The names are no longer a gate (G23 follow-up a): a person decides, and is told the names differ."""
    _, org_id, _ = await kullanici(client, "differentco@example.com")
    await _upload(client, org_id, who="Alfa Sanayi A.Ş.")
    _, counts = await _upload(client, org_id, who="Beta Ticaret A.Ş.")
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)
    assert await _radar_out(client, org_id) == 100_000


async def test_different_numbers_from_one_supplier_are_different_documents(client):
    """Instalments, identical recurring invoices, batch billing: same supplier, amount and day."""
    _, org_id, _ = await kullanici(client, "instalments@example.com")
    await _upload(client, org_id, number="T-1", who=SHORT)
    _, counts = await _upload(client, org_id, number="T-2", who=SHORT)
    assert (counts["new"], counts["possible_duplicate"]) == (1, 0)
    assert await _radar_out(client, org_id) == 200_000


async def test_two_suppliers_with_one_number_and_different_amounts_are_two_payables(client):
    _, org_id, _ = await kullanici(client, "twosup@example.com")
    await _upload(client, org_id, who="Alfa Ltd", cents=100_000)
    _, counts = await _upload(client, org_id, who="Beta Ltd", cents=250_000)
    assert (counts["new"], counts["possible_duplicate"]) == (1, 0)
    assert await _radar_out(client, org_id) == 350_000


async def test_an_alias_is_per_organisation(client):
    headers, org_id, _ = await kullanici(client, "orga@example.com")
    _, other_org, _ = await kullanici(client, "orgb@example.com")
    await _upload(client, org_id, who=FULL)
    await _upload(client, org_id, who=SHORT)
    held = await _held(client, org_id)
    await _resolve(client, headers, held.id, "exclude")
    assert (await _confirm(client, headers, held.id)).status_code == 200

    await _upload(client, other_org, who=FULL)
    _, counts = await _upload(client, other_org, who=SHORT)
    assert counts["possible_duplicate"] == 1                     # the other company's names were never confirmed
    assert await _aliases(client, other_org) == []
    assert len(await _aliases(client, org_id)) == 1


# ── the same key, not obviously the same document ────────────────────────────────────────────


async def test_an_identical_reupload_is_a_no_op(client):
    _, org_id, _ = await kullanici(client, "same@example.com")
    await _upload(client, org_id, who=SHORT)
    _, counts = await _upload(client, org_id, who=SHORT)
    assert (counts["new"], counts["already"], counts["possible_duplicate"]) == (0, 1, 0)
    assert await _radar_out(client, org_id) == 100_000


@pytest.mark.parametrize(
    "second",
    [
        {"who": "Alfa Gıda Ltd. Şti."},          # same name, another legal form: the key ignores it
        {"cents": 150_000},                       # same number, another amount
        {"days_ago": 20},                         # same number, a date far from the first
    ],
)
async def test_same_key_other_document_is_held_with_both_versions_not_absorbed(client, second):
    headers, org_id, _ = await kullanici(client, f"key{abs(hash(str(second))) % 10_000}@example.com")
    await _upload(client, org_id, who=SHORT)
    _, counts = await _upload(client, org_id, **second)

    assert (counts["new"], counts["already"], counts["possible_duplicate"]) == (0, 0, 1)
    rows = await _rows(client, org_id)
    assert len(rows) == 2 and "~v" in rows[1].source_record_id    # its own identity, nothing overwritten
    assert rows[0].amount_cents == 100_000                        # the first document is untouched
    assert await _radar_out(client, org_id) == 100_000            # the held one is not in the radar
    listed = (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]
    assert listed[0]["reason"] == "same_number_may_be_a_different_document"
    assert listed[0]["matches"][0]["id"] == rows[0].id            # both versions visible

    # Reading the same file again does not make a third row or a second question.
    _, again = await _upload(client, org_id, **second)
    assert (again["new"], again["possible_duplicate"], again["already"]) == (0, 0, 1)


async def test_a_different_document_a_person_confirms_counts_beside_the_first(client):
    headers, org_id, _ = await kullanici(client, "keepboth@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    await _upload(client, org_id, who=SHORT, cents=150_000)
    await _resolve(client, headers, (await _held(client, org_id)).id, "keep")
    assert await _radar_out(client, org_id) == 250_000
    assert len(await _items(client, org_id)) == 2
    assert await _aliases(client, org_id) == []                  # same supplier: nothing to link
    _, again = await _upload(client, org_id, who=SHORT, cents=150_000)
    assert (again["new"], again["possible_duplicate"]) == (0, 0)


async def test_the_same_document_a_person_confirms_stays_one_payable(client):
    headers, org_id, _ = await kullanici(client, "samedoc@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    await _upload(client, org_id, who="Alfa Gıda Ltd. Şti.", cents=100_000)
    done = await _resolve(client, headers, (await _held(client, org_id)).id, "exclude")
    assert done["proposed_alias"] is None                        # one party token: nothing to alias
    assert await _radar_out(client, org_id) == 100_000
    _, again = await _upload(client, org_id, who="Alfa Gıda Ltd. Şti.", cents=100_000)
    assert (again["new"], again["possible_duplicate"]) == (0, 0)
    assert await _radar_out(client, org_id) == 100_000


async def test_a_correction_of_the_second_document_reaches_its_own_row(client):
    from app.models.category_override import CategoryOverride
    from app.models.user import User
    from app.services.ledger_correction import apply_category_correction

    headers, org_id, user_id = await kullanici(client, "corr@example.com")
    await _upload(client, org_id, who=SHORT, cents=100_000)
    job2, _ = await _upload(client, org_id, who=SHORT, cents=150_000)
    await _resolve(client, headers, (await _held(client, org_id)).id, "keep")
    async with client._maker() as db:
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job2))).scalars().one()
        user = await db.get(User, user_id)
        result = await apply_category_correction(db, tx, org_id, "rent", user)
        await db.commit()
    assert result["ledger"] == "updated" and "~v" in result["source_record_id"]
    categories = {r.amount_cents: r.category for r in await _rows(client, org_id)}
    assert categories == {100_000: "cogs", 150_000: "rent"}
    async with client._maker() as db:
        kept = (await db.execute(select(CategoryOverride).where(CategoryOverride.org_id == org_id))).scalars().one()
    assert kept.source_record_id == result["source_record_id"]
