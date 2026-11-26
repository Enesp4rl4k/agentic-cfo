"""Build the known-names dictionary of ONE organisation from its own tables.

Sources (all scoped by the organisation's id, never across tenants):

  the company's own name and legal title, its VKN          -> ŞİRKET / VKN
  counterparties and vendors: transaction vendor and counterparty, the single ledger, open items,
  related parties, counterparty aliases, category-rule vendors                -> KARŞI_TARAF
  members and the accountant (users, the accountant's profile and client list) -> KİŞİ

There is no table of bank-account labels in this product: an account is identified by the IBAN or the
"Hesap No" a statement states, which the identifier detectors already catch.

Each source is capped (`_CAP` distinct values). When a cap is hit the dictionary says so (`truncated`),
the audit row says so, and the owner's screen shows it: a name beyond the cap is NOT masked.
A source that fails to read is skipped and logged, never fatal: the call then goes out with fewer names
known, and `complete` is False.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import distinct, select

from app.platform.llm_egress.names import NameDictionary
from app.platform.llm_egress.pseudonymizer import COMPANY, COUNTERPARTY, PERSON

logger = logging.getLogger(__name__)

_CAP = 5000
_TTL_SECONDS = 60.0
_CACHE: dict[str, tuple[float, LoadedDictionary]] = {}


@dataclass
class LoadedDictionary:
    names: NameDictionary
    complete: bool = True  # False when a source could not be read


def forget(org_id: str | None = None) -> None:
    if org_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(org_id, None)


async def _values(db, stmt) -> tuple[list[str], bool]:
    rows = (await db.execute(stmt.limit(_CAP + 1))).scalars().all()
    return [r for r in rows[:_CAP] if r], len(rows) > _CAP


async def _load(org_id: str) -> LoadedDictionary:
    from app import database
    from app.models.analysis_job import AnalysisJob
    from app.models.canonical_transaction import CanonicalTransaction
    from app.models.category_rule import CategoryRule
    from app.models.counterparty_alias import CounterpartyAlias
    from app.models.open_item import OpenItem
    from app.models.organization import Organization, OrgMembership
    from app.models.related_party import RelatedParty
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit
    from app.models.transaction import Transaction
    from app.models.user import User

    names = NameDictionary()
    state = LoadedDictionary(names)

    async def run(source: str, build) -> None:
        try:
            async with database.session_factory()() as db:
                await build(db)
        except Exception as exc:
            state.complete = False
            logger.warning("llm egress dictionary: %s unreadable (%s)", source, type(exc).__name__)

    def add_all(label: str, values: list[str], capped: bool) -> None:
        for v in values:
            names.add(label, v)
        names.truncated = names.truncated or capped

    jobs = select(AnalysisJob.id).where(AnalysisJob.org_id == org_id)

    async def company(db) -> None:
        org = await db.get(Organization, org_id)
        if org is not None:
            names.add(COMPANY, org.name)
            names.add(COMPANY, org.legal_title)
            names.add_identifier(org.vkn)

    async def parties(db) -> None:
        for stmt in (
            select(distinct(Transaction.vendor)).where(Transaction.job_id.in_(jobs)),
            select(distinct(Transaction.counterparty)).where(Transaction.job_id.in_(jobs)),
            select(distinct(CanonicalTransaction.counterparty)).where(CanonicalTransaction.org_id == org_id),
            select(distinct(OpenItem.counterparty)).where(OpenItem.org_id == org_id),
            select(distinct(CategoryRule.vendor_match)).where(CategoryRule.org_id == org_id),
        ):
            add_all(COUNTERPARTY, *(await _values(db, stmt)))

    async def aliases_and_related(db) -> None:
        for col in (CounterpartyAlias.alias_name, CounterpartyAlias.canonical_name):
            add_all(COUNTERPARTY, *(await _values(
                db, select(distinct(col)).where(CounterpartyAlias.org_id == org_id))))
        related = (await db.execute(
            select(RelatedParty.name, RelatedParty.tax_id).where(RelatedParty.org_id == org_id).limit(_CAP)
        )).all()
        for name, tax_id in related:
            names.add(COUNTERPARTY, name)
            names.add_identifier(tax_id)

    async def people(db) -> None:
        member_ids = select(OrgMembership.user_id).where(OrgMembership.org_id == org_id)
        users = (await db.execute(
            select(User.id, User.full_name).where((User.org_id == org_id) | User.id.in_(member_ids)).limit(_CAP)
        )).all()
        for _uid, full_name in users:
            names.add(PERSON, full_name)
        accountants = (await db.execute(
            select(SMMMMuhasebeci.unvan, SMMMMuhasebeci.firma_adi, SMMMMuhasebeci.vergi_no).where(
                SMMMMuhasebeci.user_id.in_([u[0] for u in users])
                | SMMMMuhasebeci.id.in_(select(SMMMMusteriKayit.muhasebeci_id).where(
                    SMMMMusteriKayit.client_org_id == org_id))
            ).limit(_CAP)
        )).all()
        for unvan, firma, vergi in accountants:
            names.add(PERSON, unvan)
            names.add(COUNTERPARTY, firma)
            names.add_identifier(vergi)

    for source, build in (("organization", company), ("counterparties", parties),
                          ("aliases and related parties", aliases_and_related), ("members and accountant", people)):
        await run(source, build)
    return state


async def load(org_id: str) -> LoadedDictionary:
    """The organisation's dictionary, cached for a minute (the books change slowly, the calls do not)."""
    hit = _CACHE.get(org_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    loaded = await _load(org_id)
    _CACHE[org_id] = (time.monotonic() + _TTL_SECONDS, loaded)
    return loaded
