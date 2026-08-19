"""
SMMM (Serbest Muhasebeci Mali Müşavir) Portal Model

1 muhasebeci → 30+ müşteri firma yönetimi için multi-tenant model.

DDIA: multi-tenancy = her row'da tenant_id (muhasebeci_id).
Müşteri verisi asla karışmaz — row-level security.

Tablo yapısı:
  SMMMMuhasebeci: Muhasebeci kaydı (platform kullanıcısıyla ilişkili)
  SMMMMusteriKayit: Muhasebecinin yönettiği müşteri firmalar
  SMMMAnalysisSummary: Müşteri başına en son analiz özeti (denormalized cache)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, String, Boolean, DateTime, Text, Float, Integer, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class SMMMMuhasebeci(Base):
    """Platforma kayıtlı muhasebeci."""
    __tablename__ = "smmm_muhasebeci"

    id              = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id         = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    unvan           = Column(String(200), nullable=True)   # "SMMM Ahmet Yılmaz"
    vergi_no        = Column(String(20),  nullable=True)
    oda_no          = Column(String(50),  nullable=True)   # TÜRMOB oda no
    firma_adi       = Column(String(200), nullable=True)
    il              = Column(String(50),  nullable=True)
    telefon         = Column(String(30),  nullable=True)

    # Plan
    plan            = Column(String(20),  nullable=False, default="free")
    # free: max 5 müşteri | pro: max 50 | enterprise: sınırsız
    max_clients     = Column(Integer,     nullable=False, default=5)
    is_active       = Column(Boolean,     nullable=False, default=True)

    created_at      = Column(DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(timezone.utc))
    updated_at      = Column(DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":          self.id,
            "user_id":     self.user_id,
            "unvan":       self.unvan,
            "firma_adi":   self.firma_adi,
            "il":          self.il,
            "plan":        self.plan,
            "max_clients": self.max_clients,
            "is_active":   self.is_active,
        }


class SMMMMusteriKayit(Base):
    """Muhasebecinin yönettiği müşteri firma."""
    __tablename__ = "smmm_musteri_kayit"

    id               = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    muhasebeci_id    = Column(String(36), ForeignKey("smmm_muhasebeci.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    firma_adi        = Column(String(200), nullable=False)
    vergi_no         = Column(String(20),  nullable=True)
    sektor           = Column(String(50),  nullable=True)  # saas|ecommerce|services|retail
    buyukluk         = Column(String(20),  nullable=True)  # startup|smb|enterprise
    il               = Column(String(50),  nullable=True)

    # Platforma erişim (opsiyonel: müşteri kendi hesabına da bakabilir)
    client_org_id    = Column(String(36),  nullable=True)  # organizations.id

    # Son analiz bilgisi (denormalized cache — DDIA derived data)
    last_analysis_at = Column(DateTime(timezone=True), nullable=True)
    last_job_id      = Column(String(36),  nullable=True)
    health_score     = Column(Float,       nullable=True)
    health_label     = Column(String(20),  nullable=True)

    is_active        = Column(Boolean,     nullable=False, default=True)
    notlar           = Column(Text,        nullable=True)

    created_at       = Column(DateTime(timezone=True), nullable=False,
                              default=lambda: datetime.now(timezone.utc))
    updated_at       = Column(DateTime(timezone=True), nullable=False,
                              default=lambda: datetime.now(timezone.utc),
                              onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":               self.id,
            "muhasebeci_id":    self.muhasebeci_id,
            "firma_adi":        self.firma_adi,
            "vergi_no":         self.vergi_no,
            "sektor":           self.sektor,
            "buyukluk":         self.buyukluk,
            "il":               self.il,
            "last_analysis_at": self.last_analysis_at.isoformat() if self.last_analysis_at else None,
            "last_job_id":      self.last_job_id,
            "health_score":     self.health_score,
            "health_label":     self.health_label,
            "is_active":        self.is_active,
            "notlar":           self.notlar,
        }
