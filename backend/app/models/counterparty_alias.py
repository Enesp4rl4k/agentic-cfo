"""Two spellings of one supplier, as a person confirmed them (plan v10 G23).

An invoice number is keyed with a token for its counterparty (app/core/invoice_identity.py), so
"Alfa Gıda San. ve Tic. A.Ş." and "Alfa Gıda A.Ş." are two tokens. When the same invoice arrives under
both, the second is held as a possible duplicate; a person who says "same document" also says these
are one supplier, and that is recorded here: from now on `alias_token` is read as `canonical_token`
at ingest, so the supplier does not split again next month.

Per organisation (tokens are salted with it), one row per alias, never a chain (a canonical token is
itself never an alias), and linked to the human decision that made it (`decisions`, append-only).
Holds hashes only, so it carries no name or tax number.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CounterpartyAlias(Base):
    __tablename__ = "counterparty_aliases"
    __table_args__ = (UniqueConstraint("org_id", "alias_token", name="uq_counterparty_alias_org_token"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    alias_token: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_token: Mapped[str] = mapped_column(String(16), nullable=False)
    # The human decision that made it. No foreign key: decisions outlive erasure of the people.
    decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
