"""Matching transactions against the related-party register.

Deliberately conservative in one direction. A false positive sends an ordinary
entry to the owner for approval — irritating, and visible. A false negative
leaves an undisclosed related-party transaction in the books, which is the exact
thing the register exists to prevent and which nobody notices until an audit or
a sale. So matching errs toward flagging, and every match records *why* it
matched so a human can dismiss it with the evidence in front of them.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.related_party import RelatedParty

# Turkish company-form suffixes carry no identifying information: "Demir A.Ş."
# and "Demir Anonim Şirketi" are the same counterparty. Stripping them stops a
# register entry from missing a statement line that spells the form differently.
_LEGAL_SUFFIXES = (
    "anonim sirketi", "limited sirketi", "kollektif sirketi",
    "a s", "as", "ltd sti", "ltd", "sti", "san tic", "sanayi ve ticaret",
    "sanayi", "ticaret", "insaat", "holding", "gmbh", "inc", "llc", "co",
)

_TR_MAP = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iIgGuUsSoOcC")

# Below this many characters a name is too generic to match on containment:
# "Ata" would hit "Atasehir Kirasi". Exact and tax-id matches still apply.
_MIN_CONTAINMENT_LEN = 5


def normalize_name(raw: str | None) -> str:
    """Casefold, de-accent and strip legal forms and punctuation."""
    if not raw:
        return ""
    text = raw.translate(_TR_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Strip suffixes repeatedly: "demir insaat sanayi ve ticaret ltd sti".
    changed = True
    while changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
    return text


def normalize_tax_id(raw: str | None) -> str:
    """Digits only. VKN is 10, TCKN 11; anything else is not an identifier."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) in (10, 11) else ""


@dataclass(frozen=True)
class RelatedPartyMatch:
    party_id: str
    party_name: str
    relationship_type: str
    # "tax_id" | "exact_name" | "name_in_text" — recorded so a reviewer can see
    # what the machine keyed on rather than being told only that it matched.
    matched_on: str
    matched_value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "party_id": self.party_id,
            "party_name": self.party_name,
            "relationship_type": self.relationship_type,
            "matched_on": self.matched_on,
            "matched_value": self.matched_value,
        }


async def load_active_parties(org_id: str, db: AsyncSession) -> list[RelatedParty]:
    rows = await db.execute(
        select(RelatedParty).where(
            RelatedParty.org_id == org_id,
            RelatedParty.active.is_(True),
        )
    )
    return list(rows.scalars().all())


def match_transaction(
    transaction: dict[str, Any],
    parties: list[RelatedParty],
) -> RelatedPartyMatch | None:
    """Return the first party this transaction appears to involve, or None.

    Checked in order of how much the signal is worth: a tax id is an identity, a
    whole-name match on the counterparty is strong, and the party's name inside
    the free-text description is weakest but still worth escalating — a rent
    payment rarely names the landlord in a structured field.
    """
    if not parties:
        return None

    vendor_norm = normalize_name(
        transaction.get("vendor") or transaction.get("counterparty")
    )
    desc_norm = normalize_name(transaction.get("description"))
    tx_tax_id = normalize_tax_id(
        transaction.get("tax_id") or transaction.get("vkn") or transaction.get("counterparty_tax_id")
    )

    for party in parties:
        party_tax = normalize_tax_id(party.tax_id)
        if tx_tax_id and party_tax and tx_tax_id == party_tax:
            return RelatedPartyMatch(
                party.id, party.name, party.relationship_type, "tax_id", tx_tax_id
            )

    for party in parties:
        pn = (party.normalized_name or "").strip()
        if pn and vendor_norm and pn == vendor_norm:
            return RelatedPartyMatch(
                party.id, party.name, party.relationship_type, "exact_name", vendor_norm
            )

    for party in parties:
        pn = (party.normalized_name or "").strip()
        if len(pn) < _MIN_CONTAINMENT_LEN:
            continue
        haystack = f" {vendor_norm} {desc_norm} "
        if f" {pn} " in haystack or pn in haystack.replace("  ", " "):
            return RelatedPartyMatch(
                party.id, party.name, party.relationship_type, "name_in_text", pn
            )

    return None


def annotate_transactions(
    transactions: list[dict[str, Any]],
    parties: list[RelatedParty],
) -> int:
    """Set `is_related_party` (and the evidence) on each matching transaction.

    Mutates in place, because this runs immediately before the entries are
    built and the flag has to reach `AuthorityRequest`. Returns how many were
    flagged so the caller can log and report it.
    """
    flagged = 0
    for tx in transactions:
        match = match_transaction(tx, parties)
        if match is None:
            continue
        tx["is_related_party"] = True
        tx["related_party"] = match.to_dict()
        flagged += 1
    return flagged
