"""
Logo Tiger ERP Connector

Logo Tiger CSV export dosyalarini isler.
Logo Tiger API olmadigi icin doğrudan CSV upload akisi kullanilir.

Akis:
  1. Kullanici Logo Tiger'dan CSV export alir (Fiş Listesi / Hesap Hareketleri)
  2. CSV'yi platforma yukler (multipart/form-data)
  3. LogoTigerParser CSV'yi isler
  4. Islemler normalize edilip SyncBatch olusturulur
  5. CFO pipeline'a beslenir

Desteklenen export tipleri:
  - Fis Listesi (Tarih;Fis No;Aciklama;Borc;Alacak;Bakiye)
  - Hesap Hareketleri (Tarih;Belge Turu;Belge No;Hesap Kodu;Aciklama;Borc;Alacak)
  - Mizan Raporu (Hesap Kodu;Hesap Adi;Borc;Alacak;Borc Bakiye;Alacak Bakiye)
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class LogoTigerConnector:
    """
    Logo Tiger CSV upload ve sync yoneticisi.

    Kullanim:
        connector = LogoTigerConnector(db)
        # Entegrasyon kaydi olustur:
        integration = await connector.create_integration(org_id, display_name)
        # CSV yukle ve sync et:
        result = await connector.sync_from_csv(integration_id, csv_content, filename)
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    async def create_or_update_integration(
        self,
        org_id:       str,
        display_name: str = "Logo Tiger",
    ) -> dict[str, Any]:
        """
        Logo Tiger entegrasyonu olustur veya guncelle.
        OAuth gerektirmez — CSV upload tabanli.
        """
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration

        stmt = (
            select(ERPIntegration)
            .where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "logo_tiger")
        )
        integration = (await self.db.execute(stmt)).scalar_one_or_none()

        if not integration:
            integration = ERPIntegration(
                org_id       = org_id,
                provider     = "logo_tiger",
                display_name = display_name,
                status       = "active",  # CSV-based = her zaman hazir
                connected_at = datetime.now(UTC),
            )
            self.db.add(integration)
            await self.db.commit()
            await self.db.refresh(integration)
            logger.info("Logo Tiger entegrasyon olusturuldu: org=%s", org_id)

        return integration.to_summary()

    async def sync_from_csv(
        self,
        org_id:      str,
        csv_content: str,
        filename:    str = "logo_tiger_export.csv",
    ) -> dict[str, Any]:
        """
        CSV icerigini parse et, SyncBatch olustur.

        Returns:
            {ok, transactions, sync_count, parse_errors, integration_id}
        """
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration, ERPSyncLog
        from app.parsers.accounting.logo_tiger import LogoTigerParser

        start = time.time()

        # Entegrasyon bul veya olustur
        stmt = (
            select(ERPIntegration)
            .where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "logo_tiger")
        )
        integration = (await self.db.execute(stmt)).scalar_one_or_none()
        if not integration:
            await self.create_or_update_integration(org_id)
            integration = (await self.db.execute(stmt)).scalar_one_or_none()

        # Sync log olustur
        log = ERPSyncLog(
            integration_id = integration.id,
            org_id         = org_id,
            provider       = "logo_tiger",
            status         = "running",
            started_at     = datetime.now(UTC),
        )
        self.db.add(log)
        await self.db.commit()

        parse_errors: list[str] = []

        try:
            # Parse
            parser = LogoTigerParser()

            # can_parse kontrolu
            if not LogoTigerParser.can_parse(csv_content):
                # Relaxed mod -- Logo Tiger olabilir ama marker yok
                logger.warning("Logo Tiger parser marker bulunamadi, zorla calistirilıyor: %s", filename)

            statement = parser.parse(csv_content, file_path=filename)
            transactions = statement.transactions

            # Normalize: ParsedTransaction -> dict (CFO pipeline formati)
            normalized: list[dict[str, Any]] = []
            skipped = 0
            for tx in transactions:
                try:
                    if tx.amount_cents == 0:
                        skipped += 1
                        continue
                    normalized.append({
                        "date":        tx.date.isoformat() if tx.date else None,
                        "amount_cents": abs(tx.amount_cents),
                        "type":        tx.tx_type or "expense",
                        "description": tx.description or "",
                        "category":    tx.category or "other",
                        "source":      "logo_tiger",
                        "reference":   tx.reference or "",
                    })
                except Exception as ex:
                    parse_errors.append(str(ex))
                    skipped += 1

            tx_count = len(normalized)

            # Integration guncelle
            integration.last_sync_at     = datetime.now(UTC)
            integration.last_sync_status = "success"
            integration.last_sync_count  = tx_count
            integration.last_error       = None

            log.status                = "success"
            log.transactions_synced   = tx_count
            log.transactions_skipped  = skipped
            log.finished_at           = datetime.now(UTC)
            log.duration_seconds      = int(time.time() - start)

            await self.db.commit()

            logger.info(
                "Logo Tiger sync tamamlandi: org=%s txn=%d skipped=%d",
                org_id, tx_count, skipped,
            )

            return {
                "ok":             True,
                "integration_id": integration.id,
                "transactions":   normalized,
                "sync_count":     tx_count,
                "skipped":        skipped,
                "parse_errors":   parse_errors,
                "statement_info": {
                    "bank_name":     statement.bank_name,
                    "account_number": statement.account_number,
                    "period_start":  statement.period_start.isoformat() if statement.period_start else None,
                    "period_end":    statement.period_end.isoformat() if statement.period_end else None,
                },
            }

        except Exception as exc:
            err_msg = str(exc)
            integration.last_sync_at     = datetime.now(UTC)
            integration.last_sync_status = "error"
            integration.last_error       = err_msg[:500]

            log.status        = "error"
            log.error_message = err_msg[:500]
            log.finished_at   = datetime.now(UTC)
            log.duration_seconds = int(time.time() - start)

            await self.db.commit()
            logger.error("Logo Tiger sync hatasi: org=%s err=%s", org_id, exc)
            raise

    async def get_sync_history(
        self,
        org_id: str,
        limit:  int = 10,
    ) -> list[dict[str, Any]]:
        """Son sync loglarini getir."""
        from sqlalchemy import desc, select

        from app.models.erp_integration import ERPSyncLog

        stmt = (
            select(ERPSyncLog)
            .where(ERPSyncLog.org_id == org_id, ERPSyncLog.provider == "logo_tiger")
            .order_by(desc(ERPSyncLog.started_at))
            .limit(limit)
        )
        logs = (await self.db.execute(stmt)).scalars().all()
        return [log.to_dict() for log in logs]


# ── Mikro ERP connector (CSV-based, Logo Tiger ile ayni pattern) ──────────────

class MikroConnector:
    """
    Mikro ERP CSV upload connector.
    Logo Tiger ile ayni akis, farkli parser.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    async def sync_from_csv(
        self,
        org_id:      str,
        csv_content: str,
        filename:    str = "mikro_export.csv",
    ) -> dict[str, Any]:
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration, ERPSyncLog
        from app.parsers.accounting.mikro import MikroParser  # type: ignore[attr-defined]

        start = time.time()
        stmt  = (
            select(ERPIntegration)
            .where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "mikro")
        )
        integration = (await self.db.execute(stmt)).scalar_one_or_none()
        if not integration:
            integration = ERPIntegration(
                org_id="mikro", provider="mikro", display_name="Mikro ERP",
                status="active", connected_at=datetime.now(UTC),
            )
            self.db.add(integration)
            await self.db.commit()
            await self.db.refresh(integration)

        log = ERPSyncLog(
            integration_id=integration.id, org_id=org_id,
            provider="mikro", status="running",
            started_at=datetime.now(UTC),
        )
        self.db.add(log)
        await self.db.commit()

        try:
            parser    = MikroParser()
            statement = parser.parse(csv_content, file_path=filename)
            txns      = [
                {
                    "date":         tx.date.isoformat() if tx.date else None,
                    "amount_cents": abs(tx.amount_cents),
                    "type":         tx.tx_type or "expense",
                    "description":  tx.description or "",
                    "category":     tx.category or "other",
                    "source":       "mikro",
                }
                for tx in statement.transactions if tx.amount_cents != 0
            ]
            integration.last_sync_at     = datetime.now(UTC)
            integration.last_sync_status = "success"
            integration.last_sync_count  = len(txns)
            log.status              = "success"
            log.transactions_synced = len(txns)
            log.finished_at         = datetime.now(UTC)
            log.duration_seconds    = int(time.time() - start)
            await self.db.commit()
            return {"ok": True, "transactions": txns, "sync_count": len(txns)}
        except Exception as exc:
            integration.last_sync_status = "error"
            integration.last_error = str(exc)[:500]
            log.status = "error"
            log.error_message = str(exc)[:500]
            log.finished_at = datetime.now(UTC)
            await self.db.commit()
            raise
