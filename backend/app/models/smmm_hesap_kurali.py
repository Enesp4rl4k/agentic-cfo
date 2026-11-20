"""An account an organisation's accountant has corrected a recurring description to.

Learned from the accountant's own single corrections (never from bulk approvals),
used by the accounting agent as a suggestion with a measured track record. See
`app/services/accounting/ogrenilmis_kural.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SMMMHesapKurali(Base):
    __tablename__ = "smmm_hesap_kurallari"
    __table_args__ = (
        UniqueConstraint("org_id", "anahtar", "hesap_kodu", name="uq_smmm_hesap_kurali"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # The normalised vendor or description the accountant corrected.
    anahtar: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    hesap_kodu: Mapped[str] = mapped_column(String(20), nullable=False)
    hesap_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # How many times the accountant corrected this key to this account.
    onay_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
