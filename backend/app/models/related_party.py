"""İlişkili taraf sicili — related-party register.

The classic governance failure in a family business is not fraud, it is the
undisclosed ordinary transaction: rent paid to a building the owner's family
owns, a service bought from a brother-in-law's company, a loan to a partner
booked as an expense. Each is legal and each is a related-party transaction that
TFRS 24 / TMS 24 requires to be disclosed, and that a buyer, a bank or an
inheritance dispute will eventually ask about.

`AuthorityRequest.is_related_party` has existed since the delegation matrix
landed, and the default policy escalates such an entry to the owner with a
disclosure requirement. Nothing ever set the flag: `double_entry` reads it off
the transaction dict and no parser or upload path writes it. This table is what
makes the rule able to fire — the org's own list of the parties it is connected
to, matched against the counterparty on each transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# How the party is connected to the company. Kept as plain strings rather than a
# DB enum so an org can be described without a migration.
RELATIONSHIP_TYPES: tuple[str, ...] = (
    "ortak",            # shareholder / partner
    "yonetici",         # director, board member
    "aile",             # family member of an owner or director
    "istirak",          # subsidiary / affiliate the company holds
    "ana_ortaklik",     # parent company
    "kilit_personel",   # key management personnel
    "diger",
)


class RelatedParty(Base):
    """One person or company the org is related to, for disclosure purposes."""

    __tablename__ = "related_parties"
    __table_args__ = (
        Index("ix_related_parties_org_active", "org_id", "active"),
        Index("ix_related_parties_org_norm", "org_id", "normalized_name"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Casefolded, punctuation- and suffix-stripped form used for matching. Stored
    # rather than computed per query so the match is the same everywhere and a
    # rename cannot silently change what a sealed packet was matched against.
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)

    relationship_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="diger"
    )
    # VKN (10 digits) or TCKN (11) — the only unambiguous identifier there is.
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Soft-disable rather than delete: a party that was related during a sealed
    # period must stay explainable afterwards.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "normalized_name": self.normalized_name,
            "relationship_type": self.relationship_type,
            "tax_id": self.tax_id,
            "note": self.note,
            "active": bool(self.active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
