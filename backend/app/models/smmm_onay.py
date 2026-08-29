"""
SMMM Onay Workflow Modeli — MUHASEBE-4

Serbest Muhasebeci Mali Müşavir (SMMM) onay akışı için DB modeli.

Her muhasebe kaydı (YevmiyeKaydi) SMMM tarafından:
  - onaylanabilir (APPROVED)
  - düzeltilebilir (CORRECTED) — yeni hesap kodu + açıklama
  - reddedilebilir (REJECTED)

Onay gerektiren durumlar (double_entry.py'de belirlenir):
  - Confidence < 0.6
  - Tutar > 100.000 TRY
  - Otomatik sınıflandırılamadı
  - Duran varlık alımı
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OnayDurumu(StrEnum):
    BEKLIYOR  = "bekliyor"
    ONAYLANDI = "onaylandi"
    DUZELTILDI = "duzeltildi"
    REDDEDILDI = "reddedildi"


class SMMMOnayKaydi(Base):
    """
    SMMM onay kuyruğu.

    Her kayıt bir yevmiye kaydına karşılık gelir.
    SMMM onaylar, düzeltir veya reddeder.
    """
    __tablename__ = "smmm_onay_kayitlari"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # İlgili analiz iş kimliği
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Org ve kullanıcı
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Yevmiye kaydı kimliği (UUID, DB'de ayrı tablo yok — JSON olarak saklanıyor)
    kayit_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # Orijinal yevmiye kaydı (JSON)
    orijinal_kayit: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Onay durumu
    durum: Mapped[str] = mapped_column(
        String(20), default=OnayDurumu.BEKLIYOR, nullable=False, index=True
    )

    # Onaylayan SMMM bilgisi
    onaylayan_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    onay_zamani: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onay_notu: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Düzeltme (SMMM hesap kodunu değiştirirse)
    duzeltilmis_hesap_kodu: Mapped[str | None] = mapped_column(String(10), nullable=True)
    duzeltilmis_hesap_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duzeltme_aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Orijinal otomatik sınıflandırma meta verisi
    otomatik_hesap_kodu: Mapped[str | None] = mapped_column(String(10), nullable=True)
    otomatik_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    otomatik_yontem: Mapped[str | None] = mapped_column(String(20), nullable=True)  # kural|llm|varsayılan
    onay_neden: Mapped[str | None] = mapped_column(Text, nullable=True)

    # İşlem bilgileri (hızlı görüntüleme için)
    tx_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tx_amount_try: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    tx_tarih: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Zaman damgaları
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
