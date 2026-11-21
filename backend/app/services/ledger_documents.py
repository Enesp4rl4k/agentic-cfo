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

from app.core.invoice_identity import (
    document_key,
    key_number,
    key_party,
    lacks_counterparty,
    legal_form,
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
DUPLICATE_WINDOW_DAYS = 3    # as the anomaly agent's duplicate check


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
) -> dict[tuple[int, str, str], list[tuple[date, str, str]]]:
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
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
            money_rows(),
            CanonicalTransaction.transaction_date >= datetime.combine(min(days) - window, time.min, UTC),
            CanonicalTransaction.transaction_date <= datetime.combine(max(days) + window, time.max, UTC),
        )
    )
    found: dict[tuple[int, str, str], list[tuple[date, str, str]]] = defaultdict(list)
    for r in rows:
        if r.source_job_id != job_id:
            found[(r.amount_cents, r.direction, r.basis)].append(
                (day_of(r.transaction_date), r.id, r.source_record_id)
            )
    return found


def other_supplier(record_id: str, other_record_id: str) -> bool:
    """Both rows are invoices of the same side from different counterparties AND different numbers.

    Two suppliers' invoices of the same amount are not one payment seen twice. The same number
    is another matter: "Alfa A.Ş." and "Alfa Gıda San. ve Tic. A.Ş." writing "A-1" for the same
    amount may be one supplier's invoice read twice (`_same_number`), so that is held. Only tokens
    of the same kind (tax number or name) can be told apart: a name against a tax number may be
    the same company, so that stays a suspicion too.
    """
    mine, theirs = key_party(record_id), key_party(other_record_id)
    return bool(
        mine and theirs and mine[0] == theirs[0] and mine[1][0] == theirs[1][0] and mine[1] != theirs[1]
        and key_number(record_id) != key_number(other_record_id)
    )


def repeats(
    others: dict[tuple[int, str, str], list[tuple[date, str, str]]], tx: Transaction, record_id: str,
    same_number: dict[tuple[str, int, str], list[tuple[str, str]]] | None = None,
) -> str | None:
    """The nearest row this one may repeat, if any is close enough, else one that has its number."""
    day = day_of(tx.transaction_date)
    near = [
        (abs((other - day).days), row_id)
        for other, row_id, other_record_id in others.get((tx.amount_kurus, tx.type, basis_of(tx)), [])
        if abs((other - day).days) <= DUPLICATE_WINDOW_DAYS
        and not other_supplier(record_id, other_record_id)
    ]
    if near:
        return min(near)[1]
    # The same free-form number and amount from another counterparty, whatever the dates: one
    # supplier's invoice under two spellings, or two suppliers that happen to agree on both.
    # The machine cannot know; a person decides (and "same" teaches it the alias).
    number = key_number(record_id)
    if same_number and number:
        for row_id, other_record_id in same_number.get((number, tx.amount_kurus, tx.type), []):
            if other_record_id != record_id:
                return row_id
    return None


async def same_number_rows(
    db: AsyncSession, org_id: str, job_id: str, usable: list[tuple[str, Transaction]]
) -> dict[tuple[str, int, str], list[tuple[str, str]]]:
    """Counted rows of other uploads with these free-form numbers: (number, amount, side) -> (id, key)."""
    numbers = sorted({n for rid, _ in usable if (n := key_number(rid))})
    found: dict[tuple[str, int, str], list[tuple[str, str]]] = defaultdict(list)
    for i in range(0, len(numbers), 100):
        rows = await db.execute(
            select(
                CanonicalTransaction.id, CanonicalTransaction.source_record_id,
                CanonicalTransaction.amount_cents, CanonicalTransaction.direction,
                CanonicalTransaction.source_job_id,
            ).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.ledger_status != EXCLUDED,
                money_rows(),
                or_(*[CanonicalTransaction.source_record_id.endswith(f":{n}", autoescape=True)
                      for n in numbers[i:i + 100]]),
            )
        )
        for r in rows:
            number = key_number(r.source_record_id)
            if number and r.source_job_id != job_id:
                found[(number, r.amount_cents, r.direction)].append((r.id, r.source_record_id))
    return found


async def job_transactions(db: AsyncSession, job_id: str) -> list[Transaction]:
    return list((await db.execute(
        select(Transaction).where(Transaction.job_id == job_id).order_by(Transaction.transaction_date)
    )).scalars().all())


async def load_aliases(db: AsyncSession, org_id: str) -> dict[str, str]:
    """This organisation's confirmed counterparty aliases: alias token -> canonical token."""
    rows = await db.execute(
        select(CounterpartyAlias.alias_token, CounterpartyAlias.canonical_token)
        .where(CounterpartyAlias.org_id == org_id)
    )
    return {str(a): str(c) for a, c in rows.all()}


async def variant_of(db: AsyncSession, org_id: str, record_id: str, tx: Transaction) -> str:
    """The key of the row `tx` was written under: its own key, or the variant split from it.

    A document that arrived under a key another document held is stored under `<key>~v<hash>`
    (`split_same_key`); a correction of its transaction must reach that row, not the first one.
    """
    rows = (await db.execute(
        select(CanonicalTransaction.source_record_id, CanonicalTransaction.amount_cents)
        .where(
            CanonicalTransaction.org_id == org_id,
            or_(CanonicalTransaction.source_record_id == record_id,
                CanonicalTransaction.source_record_id.startswith(f"{record_id}~v", autoescape=True)),
            CanonicalTransaction.corrects_id.is_(None),
        )
    )).all()
    if len(rows) < 2:
        return record_id
    same_amount = [r.source_record_id for r in rows if r.amount_cents == tx.amount_kurus]
    if len(same_amount) == 1:
        return same_amount[0]
    day = day_of(tx.transaction_date).isoformat()
    for r in rows:
        if r.source_record_id == variant_key(record_id, tx.amount_kurus, day, tx.counterparty):
            return r.source_record_id
    return record_id


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
) -> tuple[list[tuple[str, Transaction]], set[str]]:
    """Give a document that is not obviously the one already under its key a key of its own.

    Without this the second document goes down the "already" path: only its category is read,
    its amount is ignored, and a payable disappears. It is written as a `possible_duplicate` of
    the row that holds the key (`variants`), so a person sees both versions and decides.
    Another upload only: re-reading the same job never splits.
    """
    cache: dict[str, list[Transaction]] = {}
    out: list[tuple[str, Transaction]] = []
    variants: set[str] = set()
    for record_id, tx in usable:
        row = existing.get(record_id)
        weak = record_id.startswith("inv:") or lacks_counterparty(record_id)
        if row is not None and weak and row.source_job_id != job_id and row.corrects_id is None \
                and await differs(db, org_id, row, tx, record_id, aliases, cache):
            variant = variant_key(
                record_id, tx.amount_kurus, day_of(tx.transaction_date).isoformat(), tx.counterparty
            )
            variants.add(variant)
            found = (await existing_rows(db, org_id, [variant])).get(variant)
            if found is not None:
                existing[variant] = found
            out.append((variant, tx))
            continue
        out.append((record_id, tx))
    return out, variants


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


async def drop_open_item(db: AsyncSession, row: CanonicalTransaction) -> bool:
    """Remove the item of a row a person says repeats another, unless money was matched to it."""
    key = open_item_key(row.source_record_id)
    item = (await db.execute(
        select(OpenItem).where(OpenItem.org_id == row.org_id, OpenItem.document_id == key)
    )).scalar_one_or_none()
    if item is None or item.paid_cents:
        return False
    matched = (await db.execute(
        select(OpenItemMatch.id).where(OpenItemMatch.open_item_id == item.id).limit(1)
    )).first()
    if matched is not None:
        return False
    await db.execute(delete(OpenItem).where(OpenItem.id == item.id))
    return True
