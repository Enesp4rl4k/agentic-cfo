"""
ERP Integration Model

Desteklenen entegrasyonlar:
  - parasut   : Paraşüt OAuth2 API (cloud muhasebe)
  - logo_tiger: Logo Tiger CSV/FTP upload
  - mikro     : Mikro ERP CSV import
  - netsis    : Netsis CSV scheduled import

Credential'lar Fernet ile şifreli saklanır.
Token yenileme durumları ve sync geçmişi burada tutulur.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.database import Base


class ERPIntegration(Base):
    """Bir organizasyonun ERP/muhasebe yazılımı bağlantısı."""

    __tablename__ = "erp_integrations"

    id              = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id          = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider        = Column(String(50),  nullable=False)  # parasut | logo_tiger | mikro | netsis
    display_name    = Column(String(100), nullable=True)   # "Şirketim - Paraşüt"

    # Bağlantı durumu
    status          = Column(String(20),  nullable=False, default="pending")
    # pending | active | error | disconnected | expired

    # OAuth2 token'ları (Fernet şifreli)
    access_token_enc  = Column(Text, nullable=True)   # şifreli access token
    refresh_token_enc = Column(Text, nullable=True)   # şifreli refresh token
    token_expires_at  = Column(DateTime(timezone=True), nullable=True)
    scopes            = Column(Text, nullable=True)   # space-separated

    # Bağlantı parametreleri (Fernet şifreli JSON)
    config_enc        = Column(Text, nullable=True)
    # Logo Tiger: {"ftp_host": ..., "ftp_user": ..., "ftp_pass": ...}
    # Paraşüt:    {"company_id": ..., "client_id": ..., "client_secret": ...}

    # Sync istatistikleri
    last_sync_at      = Column(DateTime(timezone=True), nullable=True)
    last_sync_status  = Column(String(20), nullable=True)   # success | error | partial
    last_sync_count   = Column(Integer, nullable=True)       # kac islem sync edildi
    last_error        = Column(Text, nullable=True)          # son hata mesaji
    next_sync_at      = Column(DateTime(timezone=True), nullable=True)

    # Sync ayarları
    auto_sync_enabled = Column(Boolean, nullable=False, default=True)
    sync_interval_hours = Column(Integer, nullable=False, default=24)

    # Timestamps
    connected_at    = Column(DateTime(timezone=True), nullable=True)
    disconnected_at = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(UTC))
    updated_at      = Column(DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(UTC),
                             onupdate=lambda: datetime.now(UTC))

    def is_token_expired(self) -> bool:
        if not self.token_expires_at:
            return False
        return bool(datetime.now(UTC) >= self.token_expires_at)

    def is_active(self) -> bool:
        return bool(self.status == "active")

    def to_summary(self) -> dict[str, Any]:
        """Credential içermeyen özet dict (API response için)."""
        return {
            "id":                  self.id,
            "org_id":              self.org_id,
            "provider":            self.provider,
            "display_name":        self.display_name or self.provider,
            "status":              self.status,
            "last_sync_at":        self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_sync_status":    self.last_sync_status,
            "last_sync_count":     self.last_sync_count,
            "last_error":          self.last_error,
            "next_sync_at":        self.next_sync_at.isoformat() if self.next_sync_at else None,
            "auto_sync_enabled":   self.auto_sync_enabled,
            "sync_interval_hours": self.sync_interval_hours,
            "connected_at":        self.connected_at.isoformat() if self.connected_at else None,
            "token_expires_at":    self.token_expires_at.isoformat() if self.token_expires_at else None,
            "token_expired":       self.is_token_expired(),
        }


class ERPSyncLog(Base):
    """Her sync işleminin detaylı logu."""

    __tablename__ = "erp_sync_logs"

    id              = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    integration_id  = Column(String(36), ForeignKey("erp_integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id          = Column(String(36), nullable=False, index=True)
    provider        = Column(String(50), nullable=False)

    # Sonuç
    status          = Column(String(20), nullable=False)   # success | error | partial
    transactions_synced = Column(Integer, nullable=False, default=0)
    transactions_skipped = Column(Integer, nullable=False, default=0)
    error_message   = Column(Text, nullable=True)

    # CFO job ile bağlantı
    triggered_cfo_job_id = Column(String(36), nullable=True)

    # Timing
    started_at      = Column(DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(UTC))
    finished_at     = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":                   self.id,
            "integration_id":       self.integration_id,
            "provider":             self.provider,
            "status":               self.status,
            "transactions_synced":  self.transactions_synced,
            "transactions_skipped": self.transactions_skipped,
            "error_message":        self.error_message,
            "triggered_cfo_job_id": self.triggered_cfo_job_id,
            "started_at":           self.started_at.isoformat() if self.started_at else None,
            "finished_at":          self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds":     self.duration_seconds,
        }
