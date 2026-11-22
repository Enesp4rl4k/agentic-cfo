"""The ledger's document layer: what makes a row the same document, and what waits for a person.

Split out of `ledger.py` (plan v11 F2, the 600-line ceiling). Identity of an invoice is
`app/core/invoice_identity.py`; here is what the ledger does with it:

- the duplicate window and the same-number check (`repeats`): a row that may repeat money or an
  invoice already held is kept as `possible_duplicate`, out of the totals and out of the radar;
- a document that arrives under a key another document holds is split off, not absorbed
  (`split_same_key`): amount, date or legal form differ, so it is held for a person with both versions;
- confirmed counterparty aliases (`load_aliases`), read at ingest;
- open items: a held row opens none (the radar reads items, not ledger statuses), and
  `open_item_for_row` / `drop_open_item` settle them when a person answers
  (`services/duplicate_resolution.py`).
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import normalise, same_currency
from app.core.invoice_identity import (
    document_key,
    is_unique_id,
    key_number,
    key_party,
    lacks_counterparty,
    legal_form,
    names_agree,
    open_item_key,
    party_token,
    variant_key,
)
from app.models.canonical_transaction import CanonicalTransaction, money_rows
from app.models.counterparty_alias import CounterpartyAlias
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

ACTIVE = "active"
POSSIBLE_DUPLICATE = "possible_duplicate"
EXCLUDED = "excluded"

BOOK = "book"
DOCUMENT = "document"
CASH = "cash"

_CHUNK = 500
# One named window for "the same money seen twice": how far apart two ledger dates may be for a
# bank line and its invoice, or one document read from two files, to be one thing (a January file's
# invoice sat a day from the ledger's; plan v9 K1). 3 days is the anomaly agent's duplicate check,
# kept so both detectors agree. It is NOT used to pair two invoices that have document numbers: those
# are told apart by their numbers (`repeats`). It also bounds how far a re-read of the same number may
# move before it is another document (`differs`).
DUPLICATE_WINDOW_DAYS = 3
# The same free-form number and amount from another counterparty is one supplier's invoice read twice
# only if the dates also agree: e-invoice numbering restarts per supplier, so two suppliers meet on
# "A-1" and an amount by chance far more often than a re-export lands a month away. 31 days = a
# monthly file reaching the ledger a month late.
SAME_NUMBER_DATE_WINDOW_DAYS = 31
# A key that keeps meeting documents that are not it (OCR noise, a reused number): past this many
# variants every further document is still held, and the list says why ("çok sayıda sürüm").
MAX_VARIANTS = 5


def day_of(when: datetime) -> date:
    """The UTC day: SQLite hands back naive datetimes, Postgres aware ones."""
    return when.astimezone(UTC).date() if when.tzinfo else when.date()


def basis_of(tx: Transaction) -> str:
    if tx.account_code:
        return BOOK
    return DOCUMENT if tx.document_id else CASH


async def existing_rows(db: AsyncSession, org_id: str, ids: list[str]) -> dict[str, CanonicalTransaction]:
    found: dict[str, CanonicalTransaction] = {}
    for i in range(0, len(ids), _CHUNK):
        rows = await db.execute(
            select(CanonicalTransaction).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.source_record_id.in_(ids[i:i + _CHUNK]),
            )
        )
        found.update({r.source_record_id: r for r in rows.scalars()})
    return found


async def others_by_money(
    db: AsyncSession, org_id: str, job_id: str, days: list[date]
) -> dict[tuple[int, str, str], list[tuple[date, str, str, str]]]:
    """Rows from other uploads around these dates: what a new row might repeat."""
    window = timedelta(days=DUPLICATE_WINDOW_DAYS)
    rows = await db.execute(
        select(
            CanonicalTransaction.id,
            CanonicalTransaction.source_record_id,
            CanonicalTransaction.transaction_date,
            CanonicalTransaction.amount_cents,
            CanonicalTransaction.direction,
            CanonicalTransaction.source_job_id,
            CanonicalTransaction.basis,
            CanonicalTransaction.currency,
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
            money_rows(),
            CanonicalTransaction.transaction_date >= datetime.combine(min(days) - window, time.min, UTC),
            CanonicalTransaction.transaction_date <= datetime.combine(max(days) + window, time.max, UTC),
        )
    )
    found: dict[tuple[int, str, str], list[tuple[date, str, str, str]]] = defaultdict(list)
    for r in rows:
        if r.source_job_id != job_id:
            found[(r.amount_cents, r.direction, r.basis)].append(
                (day_of(r.transaction_date), r.id, r.source_record_id, normalise(r.currency))
            )
    return found


def _is_document_key(record_id: str) -> bool:
    return record_id.startswith(("doc:", "inv:"))


def repeats(
    others: dict[tuple[int, str, str], list[tuple[date, str, str, str]]], tx: Transaction, record_id: str
) -> str | None:
    """The nearest row this one may repeat in the duplicate window, if any is close enough.

    Only for money that has no document number to tell it apart: a bank line and the line another
    upload already wrote. Two invoices with numbers (a UUID, a GİB number, a free-form number) are
    different documents when their numbers differ, however alike their amounts and dates: instalments,
    identical recurring invoices and batch billing would otherwise all be held. The same number is
    `same_number_match`'s question.
    """
    day = day_of(tx.transaction_date)
    near = [
        (abs((other - day).days), row_id)
        for other, row_id, other_record_id, other_currency in others.get((tx.amount_kurus, tx.type, basis_of(tx)), [])
        if abs((other - day).days) <= DUPLICATE_WINDOW_DAYS
        and not (_is_document_key(record_id) and _is_document_key(other_record_id))
        and same_currency(tx.currency, other_currency)
    ]
    return min(near)[1] if near else None


async def same_number_rows(
    db: AsyncSession, org_id: str, job_id: str, usable: list[tuple[str, Transaction]]
) -> dict[tuple[str, int, str], list[CanonicalTransaction]]:
    """Counted rows of other uploads with these free-form numbers: (number, amount, side) -> rows."""
    numbers = sorted({n for rid, _ in usable if (n := key_number(rid))})
    found: dict[tuple[str, int, str, str], list[CanonicalTransaction]] = defaultdict(list)
    for i in range(0, len(numbers), 100):
        rows = await db.execute(
            select(CanonicalTransaction).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.ledger_status != EXCLUDED,
                money_rows(),
                or_(*[CanonicalTransaction.source_record_id.endswith(f":{n}", autoescape=True)
                      for n in numbers[i:i + 100]]),
            )
        )
        for r in rows.scalars():
            number = key_number(r.source_record_id)
            if number and r.source_job_id != job_id:
                found[(number, r.amount_cents, r.direction)].append(r)
    return found


async def same_number_match(
    db: AsyncSession, org_id: str, tx: Transaction, record_id: str,
    candidates: dict[tuple[str, int, str, str], list[CanonicalTransaction]],
    aliases: dict[str, str], cache: dict[str, list[Transaction]],
) -> str | None:
    """A row with this number and amount under another counterparty, close in date: held for a person.

    Number and amount alone are not enough (suppliers' numbers collide), so the dates must be within
    `SAME_NUMBER_DATE_WINDOW_DAYS`. The counterparties are NOT a gate: one name inside the other
    ("Alfa Gıda" in "Alfa Gıda San. ve Tic.") is the likely re-spelling, but "Alfa Gıda" against
    "Alfa Gıdacılık", or an OCR typo in the name, are the same invoice just as often, and a missed
    one is a payable counted twice with no flag. Both are held; `hold_reason` tells the person which
    it is ("aynı numara ve tutar, farklı unvan" when the names do not agree).
    """
    number = key_number(record_id)
    if not number:
        return None
    day = day_of(tx.transaction_date)
    for row in candidates.get((number, tx.amount_kurus, tx.type), []):
        if row.source_record_id == record_id or not same_currency(tx.currency, row.currency):
            continue
        if abs((day_of(row.asil_tarih or row.transaction_date) - day).days) > SAME_NUMBER_DATE_WINDOW_DAYS:
            continue
        return str(row.id)
    return None


def _is_unique_document_key(record_id: str) -> bool:
    """`doc:` + a UUID (ETTN) or GİB number: a name the document carries whoever issued it."""
    return record_id.startswith("doc:") and is_unique_id(base_key(record_id)[4:])


async def same_document_other_id(
    db: AsyncSession, tx: Transaction, record_id: str,
    others: dict[tuple[int, str, str], list[tuple[date, str, str, str]]],
    aliases: dict[str, str], cache: dict[str, list[Transaction]],
) -> str | None:
    """The row this document may be, when it was read under a different kind of identity.

    `repeats` never pairs two documents that carry numbers (instalments, recurring invoices and batch
    billing share amounts and dates). The hole: one invoice read once with its ETTN/GİB number
    (`doc:<uuid>`) and once with a free-form number (`inv:...` or a bare `doc:A-1`) has two keys and
    no number to compare. Only that mixed pair is compared here, on what the two readings share:
    amount, side, a date within the duplicate window, and a counterparty that is known on both and
    agrees (`names_agree`). Two UUID-keyed invoices, or two free-form ones, are told apart by their
    numbers as before.
    """
    if not _is_document_key(record_id):
        return None
    mine_unique = _is_unique_document_key(record_id)
    day = day_of(tx.transaction_date)
    for other_day, row_id, other_record_id, other_currency in others.get(
        (tx.amount_kurus, tx.type, basis_of(tx)), []
    ):
        if (
            abs((other_day - day).days) > DUPLICATE_WINDOW_DAYS
            or not _is_document_key(other_record_id)
            or _is_unique_document_key(other_record_id) == mine_unique
            or not same_currency(tx.currency, other_currency)
        ):
            continue
        row = await db.get(CanonicalTransaction, row_id)
        old = await source_transaction(db, row, aliases, cache) if row is not None else None
        if old and old.counterparty and tx.counterparty and names_agree(old.counterparty, tx.counterparty):
            return row_id
    return None


# Why a row is held, in words the screen can show.
HOLD_REASONS_TR = {
    "many_versions": "çok sayıda sürüm",
    "same_number_different_name": "aynı numara ve tutar, farklı unvan",
    "same_document_different_id": "aynı belge farklı kimlikle okunmuş olabilir",
    "same_number_may_be_a_different_document": "aynı numara, farklı belge olabilir",
    "same_amount_close_in_time": "aynı tutar, yakın tarih",
}


async def hold_reason(
    db: AsyncSession, row: CanonicalTransaction, aliases: dict[str, str],
    cache: dict[str, list[Transaction]] | None = None,
) -> str:
    """Why this row is held as a possible duplicate: one of `HOLD_REASONS_TR`'s keys."""
    org_id = str(row.org_id)
    siblings = (await variant_rows(db, org_id, [base_key(row.source_record_id)])).get(
        base_key(row.source_record_id), [])
    if len(siblings) - 1 >= MAX_VARIANTS:
        return "many_versions"
    match = await db.get(CanonicalTransaction, row.duplicate_of) if row.duplicate_of else None
    if match is not None and str(match.org_id) != org_id:
        match = None
    if match is None:
        return "same_amount_close_in_time"
    number = key_number(row.source_record_id)
    if number and number == key_number(match.source_record_id):
        if base_key(row.source_record_id) != base_key(match.source_record_id) and match.amount_cents == row.amount_cents:
            mine = await source_transaction(db, row, aliases, cache)
            old = await source_transaction(db, match, aliases, cache)
            if mine and old and not names_agree(old.counterparty, mine.counterparty):
                return "same_number_different_name"
        return "same_number_may_be_a_different_document"
    if _is_document_key(row.source_record_id) and _is_document_key(match.source_record_id):
        return "same_document_different_id"
    return "same_amount_close_in_time"


async def job_transactions(db: AsyncSession, job_id: str) -> list[Transaction]:
    return list((await db.execute(
        select(Transaction).where(Transaction.job_id == job_id).order_by(Transaction.transaction_date)
    )).scalars().all())


async def load_aliases(db: AsyncSession, org_id: str) -> dict[str, str]:
    """This organisation's confirmed counterparty aliases: alias token -> canonical token."""
    rows = await db.execute(
        select(CounterpartyAlias.alias_token, CounterpartyAlias.canonical_token)
        .where(CounterpartyAlias.org_id == org_id, CounterpartyAlias.revoked_at.is_(None))
    )
    return {str(a): str(c) for a, c in rows.all()}


async def variant_rows(
    db: AsyncSession, org_id: str, record_ids: list[str]
) -> dict[str, list[tuple[str, int]]]:
    """For each key: its own row and the variants split from it, as (key, amount), oldest first."""
    found: dict[str, list[tuple[str, int]]] = defaultdict(list)
    wanted = sorted({r for r in record_ids if r.startswith(("doc:", "inv:"))})
    for i in range(0, len(wanted), 100):
        chunk = wanted[i:i + 100]
        rows = await db.execute(
            select(CanonicalTransaction.source_record_id, CanonicalTransaction.amount_cents)
            .where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.corrects_id.is_(None),
                or_(CanonicalTransaction.source_record_id.in_(chunk),
                    *[CanonicalTransaction.source_record_id.startswith(f"{k}~v", autoescape=True) for k in chunk]),
            ).order_by(CanonicalTransaction.created_at, CanonicalTransaction.id)
        )
        for key, amount in rows:
            base = base_key(key)
            if base in chunk:
                found[base].append((key, amount))
    return found


def pick_variant(rows: list[tuple[str, int]], record_id: str, tx: Transaction) -> str:
    """The key of the row `tx` was written under, among a key and its variants."""
    if len(rows) < 2:
        return record_id
    same_amount = [k for k, amount in rows if amount == tx.amount_kurus]
    if len(same_amount) == 1:
        return same_amount[0]
    exact = variant_key(record_id, tx.amount_kurus, day_of(tx.transaction_date).isoformat(), tx.counterparty)
    return exact if any(k == exact for k, _ in rows) else record_id


async def variant_of(db: AsyncSession, org_id: str, record_id: str, tx: Transaction) -> str:
    """The key of the row `tx` was written under: its own key, or the variant split from it.

    A document that arrived under a key another document held is stored under `<key>~v<hash>`
    (`split_same_key`); a correction of its transaction must reach that row, not the first one.
    """
    rows = (await variant_rows(db, org_id, [record_id])).get(record_id, [])
    return pick_variant(rows, record_id, tx)


def base_key(record_id: str) -> str:
    return record_id.split("~v", 1)[0]


async def source_transaction(
    db: AsyncSession, row: CanonicalTransaction, aliases: dict[str, str],
    cache: dict[str, list[Transaction]] | None = None,
) -> Transaction | None:
    """The upload's own transaction a ledger row was written from (raw counterparty, due date, ...)."""
    if not row.source_job_id or not row.source_record_id.startswith(("doc:", "inv:")):
        return None
    job = row.source_job_id
    if cache is not None and job in cache:
        txs = cache[job]
    else:
        txs = await job_transactions(db, job)
        if cache is not None:
            cache[job] = txs
    org_id, base = str(row.org_id), base_key(row.source_record_id)
    for tx in txs:
        if tx.document_id and tx.amount_kurus == row.amount_cents and base in (
            document_key(org_id, tx.document_id, tx.counterparty, tx.type),
            document_key(org_id, tx.document_id, tx.counterparty, tx.type, aliases),
        ):
            return tx
    return None


async def differs(
    db: AsyncSession, org_id: str, row: CanonicalTransaction, tx: Transaction, record_id: str,
    aliases: dict[str, str], cache: dict[str, list[Transaction]],
) -> bool:
    """Is this the same number as the row we hold, but not obviously the same document?

    A different amount, a date more than the duplicate window away, or (for a name-keyed
    counterparty) a different legal form after the name ("Alfa A.Ş." against "Alfa Ltd."),
    which the key deliberately ignores.
    """
    if row.amount_cents != tx.amount_kurus:
        return True
    first_day = day_of(row.asil_tarih or row.transaction_date)
    if abs((day_of(tx.transaction_date) - first_day).days) > DUPLICATE_WINDOW_DAYS:
        return True
    party = key_party(record_id)
    if party is None or party[1][0] != "n" or party_token(org_id, tx.counterparty) in aliases:
        return False  # a tax number is authoritative; an alias a person confirmed is not asked twice
    old = await source_transaction(db, row, aliases, cache)
    if old is None:
        return False
    before, now = legal_form(old.counterparty), legal_form(tx.counterparty)
    return bool(before and now and before != now)


async def split_same_key(
    db: AsyncSession, org_id: str, job_id: str, usable: list[tuple[str, Transaction]],
    existing: dict[str, CanonicalTransaction], aliases: dict[str, str],
) -> tuple[list[tuple[str, Transaction]], set[str], int]:
    """Give a document that is not obviously the one already under its key a key of its own.

    Without this the second document goes down the "already" path: only its category is read,
    its amount is ignored, and a payable disappears. It is written as a `possible_duplicate` of
    the row that holds the key (`variants`), so a person sees both versions and decides.

    Deterministic per file: the same job read again maps to the variant it wrote before (OCR noise
    in the amount on a re-read never spawns another). Past `MAX_VARIANTS` a document is still held
    under a key of its own, never merged into the nearest version (its amount would then be in no
    total and in no list): it is counted as `many_versions` and the held list says "çok sayıda sürüm".
    Another upload only: the job that wrote the row under the key is never split from it.
    """
    cache: dict[str, list[Transaction]] = {}
    out: list[tuple[str, Transaction]] = []
    variants: set[str] = set()
    many = 0
    for record_id, tx in usable:
        row = existing.get(record_id)
        weak = record_id.startswith("inv:") or lacks_counterparty(record_id)
        if not (row is not None and weak and row.source_job_id != job_id and row.corrects_id is None
                and await differs(db, org_id, row, tx, record_id, aliases, cache)):
            out.append((record_id, tx))
            continue
        siblings = [r for r in (await variant_rows(db, org_id, [record_id])).get(record_id, [])
                    if r[0] != record_id]
        key = variant_key(record_id, tx.amount_kurus, day_of(tx.transaction_date).isoformat(), tx.counterparty)
        own = (await _variant_of_job(db, org_id, record_id, job_id))
        if own is not None:
            key = own                       # the file's own version, whatever its amount reads now
        elif key not in {k for k, _ in siblings} and len(siblings) >= MAX_VARIANTS:
            many += 1   # beyond the cap: still held under a key of its own (never merged into a version)
        found = (await existing_rows(db, org_id, [key])).get(key)
        if found is not None:
            existing[key] = found
        variants.add(key)
        out.append((key, tx))
    return out, variants, many


async def _variant_of_job(db: AsyncSession, org_id: str, record_id: str, job_id: str) -> str | None:
    """The variant of this key that this job's file wrote, if it wrote one."""
    return (await db.execute(
        select(CanonicalTransaction.source_record_id).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.source_job_id == job_id,
            CanonicalTransaction.corrects_id.is_(None),
            CanonicalTransaction.source_record_id.startswith(f"{record_id}~v", autoescape=True),
        ).order_by(CanonicalTransaction.created_at).limit(1)
    )).scalar_one_or_none()


async def override_keys(
    db: AsyncSession, org_id: str, job_id: str, usable: list[tuple[str, Transaction]]
) -> dict[str, str]:
    """Transaction id -> the ledger key its row (and so its remembered override) lives under.

    The key itself, unless a variant was split from it: then the variant this job wrote, else the
    one that matches by amount (`pick_variant`).
    """
    variants = await variant_rows(db, org_id, [rid for rid, _ in usable])
    written = (await db.execute(
        select(CanonicalTransaction.source_record_id).where(
            CanonicalTransaction.org_id == org_id, CanonicalTransaction.source_job_id == job_id,
            CanonicalTransaction.source_record_id.contains("~v", autoescape=True),
            CanonicalTransaction.corrects_id.is_(None),
        )
    )).scalars().all()
    own = {base_key(k): k for k in written}
    return {
        tx.id: own.get(rid) or pick_variant(variants.get(rid, []), rid, tx) for rid, tx in usable
    }


def base_row_id(existing: dict[str, CanonicalTransaction], variant: str) -> str | None:
    """The row that holds the key a variant was split from."""
    base = existing.get(base_key(variant))
    return base.id if base is not None else None


async def open_items(
    db: AsyncSession, org_id: str, job_id: str, usable: list[tuple[str, Transaction]]
) -> None:
    """A document whose side we know opens an item; the same one twice does not.

    The item is keyed as the ledger row is (`open_item_key`), so two suppliers' "A-001" are
    two items under the unique (organisation, document) index. A row held as a possible
    duplicate opens none (the caller leaves it out): the radar reads items, not ledger
    statuses, so an item for a held row would put the same payable in twice. `open_item_for_row`
    opens it when a person says the document is separate.
    """
    for record_id, tx in usable:
        await insert_open_item(db, org_id, job_id, record_id, tx)


async def insert_open_item(
    db: AsyncSession, org_id: str, job_id: str | None, record_id: str, tx: Transaction
) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    if not (tx.document_id and tx.counterparty):
        return
    if tx.amount_kurus <= 0:
        # A return (iade) is signed negative. It would be a negative receivable or
        # payable; netting it against the invoice it returns is not modelled yet,
        # so it opens no item (its ledger row still counts, signed).
        return
    await db.execute(
        insert(OpenItem).values(
            id=str(uuid.uuid4()),
            org_id=org_id,
            direction="receivable" if tx.type == "income" else "payable",
            instrument="invoice",
            document_id=open_item_key(record_id),
            source_job_id=job_id,
            counterparty=tx.counterparty,
            description=tx.description,
            amount_cents=tx.amount_kurus,
            paid_cents=0,
            currency=tx.currency,
            issue_date=day_of(tx.transaction_date),
            due_date=tx.due_date,
            payment_note=tx.payment_note,
            status="open",
            created_at=datetime.now(UTC),
        ).on_conflict_do_nothing(index_elements=["org_id", "document_id"])
    )


async def open_item_for_row(db: AsyncSession, row: CanonicalTransaction) -> bool:
    """Open the item of a row a person has just released from `possible_duplicate`. True if written."""
    org_id = str(row.org_id)
    tx = await source_transaction(db, row, await load_aliases(db, org_id))
    if tx is None:
        logger.warning("ledger: no source transaction to open an item for row %s", row.id)
        return False
    await insert_open_item(db, org_id, row.source_job_id, row.source_record_id, tx)
    return True


class MatchedMoney(Exception):
    """The item holds money a person (or the matcher) confirmed: the document cannot just disappear."""

    def __init__(self, match_ids: list[str]) -> None:
        super().__init__("confirmed matches: " + ", ".join(match_ids))
        self.match_ids = match_ids


async def drop_open_item(db: AsyncSession, row: CanonicalTransaction, decided_by: str) -> tuple[str, list[str]]:
    """Take the item of a row a person says repeats another out of the books. (outcome, match ids).

    - no item: `("none", [])`;
    - only proposals (or nothing) against it: each proposal is rejected (the bank line goes back to
      being its own money, as when a person answers "no" to it), then the item and its matches are
      removed: `("removed", rejected ids)`;
    - money confirmed against it (a bank movement settled this document): `MatchedMoney`. Nothing is
      changed; the caller refuses the answer until the match is undone
      (`POST /ledger/settlements/{id}/undo`), so money never stays matched to an excluded document
      without a visible state.
    """
    key = open_item_key(row.source_record_id)
    item = (await db.execute(
        select(OpenItem).where(OpenItem.org_id == row.org_id, OpenItem.document_id == key)
    )).scalar_one_or_none()
    if item is None:
        return "none", []
    matches = (await db.execute(
        select(OpenItemMatch).where(OpenItemMatch.open_item_id == item.id)
    )).scalars().all()
    confirmed = [m.id for m in matches if m.status == "confirmed"]
    if confirmed or item.paid_cents:
        raise MatchedMoney(confirmed)
    rejected = [m.id for m in matches if m.status == "proposed"]
    for m in matches:
        if m.status == "proposed":
            m.status, m.decided_by = "rejected", decided_by
    await db.flush()
    await db.execute(delete(OpenItemMatch).where(OpenItemMatch.open_item_id == item.id))
    await db.execute(delete(OpenItem).where(OpenItem.id == item.id))
    return "removed", rejected
