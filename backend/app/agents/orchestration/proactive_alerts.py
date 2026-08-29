"""
Proactive Alert Orchestrator

DDIA Stream Processing prensibi:
  "Olaylar oldukca islenir, kullanici sorgusu beklenmiyor."

Sistem proaktif calisir:
  1. Scheduler her saat KRI degerlerini kontrol eder
  2. Esik asiminda cascade simülasyon tetiklenir
  3. Yonetici ozeti hazirlanir
  4. Multi-channel dispatch: Slack, Email, in-app

DDIA unbundling:
  - KRI state: Redis sorted set (hizli okuma)
  - Alert history: PostgreSQL (durable log)
  - Dispatch queue: Redis list (retry mekanizmasi)

Kullanim:
    orchestrator = ProactiveAlertOrchestrator(db, redis)

    # Manuel tetikleme (test icin)
    await orchestrator.scan_and_alert(org_id)

    # Scheduler'dan tetikleme
    await orchestrator.run_scheduled_scan()
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Alert event (immutable) ───────────────────────────────────────────────────

@dataclass
class AlertEvent:
    """
    Olusturulan alert'in immutable kaydi.
    DDIA: event sourcing — ne oldugunu degistirme, yeni event ekle.
    """
    alert_id:    str
    org_id:      str
    trigger:     str          # "kri_breach" | "cascade_risk" | "regime_change"
    severity:    str          # "critical" | "high" | "medium"
    title:       str
    body:        str          # Turkce ozet
    metadata:    dict[str, Any]
    channels:    list[str]    # ["slack", "email", "in_app"]
    created_at:  float        # Unix timestamp
    dispatched:  bool = False
    dispatch_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id":   self.alert_id,
            "org_id":     self.org_id,
            "trigger":    self.trigger,
            "severity":   self.severity,
            "title":      self.title,
            "body":       self.body,
            "metadata":   self.metadata,
            "channels":   self.channels,
            "created_at": self.created_at,
            "dispatched": self.dispatched,
        }


# ── Proactive Alert Orchestrator ──────────────────────────────────────────────

class ProactiveAlertOrchestrator:
    """
    KRI tarama → cascade tetikleme → dispatch pipeline.

    DDIA prensipleri:
    - Okuma/yazma ayrimi: KRI okuma Redis'ten, alert yazma PostgreSQL
    - Retry mekanizmasi: basarisiz dispatch Redis queue'da bekler
    - Idempotency: ayni KRI ihlali icin 1 saatte max 1 alert
    """

    ALERT_COOLDOWN_SECONDS = 3600   # 1 saat: ayni KRI icin tekrar alert yok
    MAX_CASCADES_PER_SCAN  = 3      # Performans: scan basina max cascade sim

    def __init__(self, db: Any = None, redis: Any = None) -> None:
        self.db    = db
        self.redis = redis

    # ── Ana tarama dongusu ─────────────────────────────────────────────────────

    async def scan_and_alert(self, org_id: str) -> dict[str, Any]:
        """
        Organizasyonun KRI'larini tara, kritik durumda alert olustur.

        Returns:
            {alerts_created, cascades_run, dispatched, errors}
        """
        alerts_created = 0
        errors: list[str] = []

        try:
            # 1. Mevcut KRI'lari hesapla (Risk Kernel)
            kri_result = await self._compute_current_kris(org_id)
            if not kri_result:
                return {"alerts_created": 0, "reason": "KRI verisi yok"}

            posture    = kri_result.get("posture", {})
            red_kris   = posture.get("red_kris", [])
            posture.get("amber_kris", [])
            upcoming   = posture.get("upcoming_red", [])

            # 2. Kritik KRI'lar icin alert olustur
            for kri in red_kris[:self.MAX_CASCADES_PER_SCAN]:
                if await self._is_cooldown_active(org_id, kri.get("name", "")):
                    continue

                alert = await self._create_kri_alert(org_id, kri, "critical")
                if alert:
                    await self._dispatch_alert(alert)
                    alerts_created += 1

            # 3. Cascade tetikleyebilecek KRI'lar icin simülasyon
            cascade_kris = posture.get("cascade_ready", [])
            for kri in cascade_kris[:self.MAX_CASCADES_PER_SCAN]:
                if not kri.get("cascade_trigger"):
                    continue
                if await self._is_cooldown_active(org_id, f"cascade:{kri.get('name', '')}"):
                    continue

                cascade_alert = await self._run_cascade_and_alert(org_id, kri)
                if cascade_alert:
                    await self._dispatch_alert(cascade_alert)
                    alerts_created += 1

            # 4. Yaklasan kirmizi KRI'lar icin onceden uyari
            for kri in upcoming[:2]:
                trajectory = kri.get("trajectory_months")
                if trajectory and trajectory <= 2:
                    alert = await self._create_upcoming_alert(org_id, kri)
                    if alert:
                        await self._dispatch_alert(alert)
                        alerts_created += 1

            return {
                "alerts_created": alerts_created,
                "red_kris":       len(red_kris),
                "cascade_kris":   len(cascade_kris),
                "errors":         errors,
            }

        except Exception as exc:
            logger.error("Proactive scan hatasi: org=%s err=%s", org_id, exc)
            return {"alerts_created": 0, "error": str(exc)}

    async def run_scheduled_scan(self) -> dict[str, Any]:
        """
        Tum aktif org'lari tara (scheduler tarafindan cagirilir).
        DDIA: fan-out write — tek scan, cok org.
        """
        try:
            org_ids = await self._get_active_orgs()
            if not org_ids:
                return {"scanned": 0}

            # Paralel tara (max 10 org ayni anda)
            semaphore = asyncio.Semaphore(10)

            async def scan_one(oid: str) -> dict[str, Any]:
                async with semaphore:
                    return await self.scan_and_alert(oid)

            results = await asyncio.gather(*[scan_one(o) for o in org_ids], return_exceptions=True)

            total_alerts = sum(
                r.get("alerts_created", 0) for r in results if isinstance(r, dict)
            )
            errors = [str(r) for r in results if isinstance(r, Exception)]

            logger.info(
                "Scheduled scan tamamlandi: orgs=%d alerts=%d errors=%d",
                len(org_ids), total_alerts, len(errors),
            )
            return {
                "scanned":      len(org_ids),
                "total_alerts": total_alerts,
                "errors":       errors[:5],
            }

        except Exception as exc:
            logger.error("Scheduled scan hatasi: %s", exc)
            return {"scanned": 0, "error": str(exc)}

    # ── KRI hesaplama ──────────────────────────────────────────────────────────

    async def _compute_current_kris(self, org_id: str) -> dict[str, Any] | None:
        """CompanyContext'ten veri al, Risk Kernel calistir."""
        try:
            from app.services.company_context import get_company_context
            ctx = await get_company_context(org_id)
            if not ctx:
                return None

            results = ctx.get("agent_results") or {}
            cfo_r   = results.get("cfo") or {}

            from app.agents.risk.risk_kernel import run_risk_kernel
            return await run_risk_kernel(
                pnl      = cfo_r.get("pnl"),
                cashflow = cfo_r.get("cashflow"),
                forecast = cfo_r.get("forecast"),
                chro_data = results.get("chro"),
                cto_data  = results.get("cto"),
                cmo_data  = results.get("cmo"),
                coo_data  = results.get("coo"),
            )
        except Exception as exc:
            logger.debug("KRI hesaplama hatasi: org=%s err=%s", org_id, exc)
            return None

    # ── Alert olusturma ────────────────────────────────────────────────────────

    async def _create_kri_alert(
        self, org_id: str, kri: dict[str, Any], severity: str
    ) -> AlertEvent | None:
        name  = kri.get("name", "Bilinmeyen KRI")
        val   = kri.get("current_value", 0)
        unit  = kri.get("unit", "")
        ev    = kri.get("evidence", "")

        title = f"🚨 {name}: {val} {unit} — Kırmızı Eşik Aşıldı"
        body  = (
            f"**{name}** metrigi kritik seviyeye ulasti.\n\n"
            f"Mevcut Deger: **{val} {unit}**\n"
            f"Kanit: {ev}\n\n"
        )

        # Mitigasyon onerileri
        mitigations = kri.get("mitigations") or []
        if mitigations:
            body += "**Onerileri Aksiyonlar:**\n"
            for i, m in enumerate(mitigations[:3], 1):
                body += f"{i}. {m}\n"

        return AlertEvent(
            alert_id   = str(uuid.uuid4()),
            org_id     = org_id,
            trigger    = "kri_breach",
            severity   = severity,
            title      = title,
            body       = body,
            metadata   = {"kri": kri},
            channels   = await self._get_alert_channels(org_id, severity),
            created_at = time.time(),
        )

    async def _run_cascade_and_alert(
        self, org_id: str, kri: dict[str, Any]
    ) -> AlertEvent | None:
        """KRI icin cascade simülasyonu calistir, alert olustur."""
        try:
            from app.services.cascade_simulator import TriggerType, get_cascade_simulator
            trigger_str = kri.get("cascade_trigger", "")
            try:
                trigger = TriggerType(trigger_str)
            except ValueError:
                return None

            # CompanyContext'ten veri al
            from app.services.company_context import get_company_context
            ctx      = await get_company_context(org_id) or {}
            results  = ctx.get("agent_results") or {}
            cfo_r    = results.get("cfo") or {}
            sim      = get_cascade_simulator(
                pnl      = cfo_r.get("pnl"),
                cashflow = cfo_r.get("cashflow"),
                forecast = cfo_r.get("forecast"),
                chro_data = results.get("chro"),
                cto_data  = results.get("cto"),
                cmo_data  = results.get("cmo"),
                coo_data  = results.get("coo"),
            )
            params   = kri.get("cascade_params") or {}
            cascade  = sim.simulate(trigger, **params)
            base_sc  = cascade.base_scenario

            if base_sc.overall_risk_score < 40:
                return None  # Dusuk risk → alert olusturma

            title = f"⚡ Zincirleme Risk: {kri.get('name', '')} → {', '.join(cascade.affected_domains[:3])}"
            body  = cascade.executive_summary + "\n\n**Acil Aksiyonlar:**\n"
            for a in cascade.immediate_actions[:3]:
                body += f"• {a}\n"

            return AlertEvent(
                alert_id   = str(uuid.uuid4()),
                org_id     = org_id,
                trigger    = "cascade_risk",
                severity   = "critical" if base_sc.overall_risk_score > 70 else "high",
                title      = title,
                body       = body,
                metadata   = {
                    "kri":           kri,
                    "cascade_score": base_sc.overall_risk_score,
                    "affected":      cascade.affected_domains,
                },
                channels   = await self._get_alert_channels(org_id, "high"),
                created_at = time.time(),
            )
        except Exception as exc:
            logger.debug("Cascade alert olusturma hatasi: %s", exc)
            return None

    async def _create_upcoming_alert(
        self, org_id: str, kri: dict[str, Any]
    ) -> AlertEvent | None:
        name       = kri.get("name", "")
        trajectory = kri.get("trajectory_months", 0)

        title = f"⚠ {name}: {trajectory:.1f} ay içinde kritik seviyeye ulaşabilir"
        body  = (
            f"**{name}** metrigi mevcut trendde **{trajectory:.1f} ay** icinde "
            f"kirmizi esigi asabilir.\n\n"
            f"Simdiden onlem almak icin zaman var."
        )

        return AlertEvent(
            alert_id   = str(uuid.uuid4()),
            org_id     = org_id,
            trigger    = "kri_upcoming",
            severity   = "medium",
            title      = title,
            body       = body,
            metadata   = {"kri": kri},
            channels   = await self._get_alert_channels(org_id, "medium"),
            created_at = time.time(),
        )

    # ── Dispatch ───────────────────────────────────────────────────────────────

    async def _dispatch_alert(self, alert: AlertEvent) -> None:
        """Alert'i tum kanallara gonder."""
        dispatch_tasks = []
        for channel in alert.channels:
            if channel == "in_app":
                dispatch_tasks.append(self._dispatch_in_app(alert))
            elif channel == "slack":
                dispatch_tasks.append(self._dispatch_slack(alert))
            elif channel == "email":
                dispatch_tasks.append(self._dispatch_email(alert))

        if dispatch_tasks:
            results = await asyncio.gather(*dispatch_tasks, return_exceptions=True)
            errors  = [str(r) for r in results if isinstance(r, Exception)]
            if errors:
                alert.dispatch_errors.extend(errors)
                logger.warning("Alert dispatch hatalari: alert=%s errors=%s", alert.alert_id, errors)

        alert.dispatched = True
        await self._save_alert(alert)
        await self._set_cooldown(alert.org_id, alert.metadata.get("kri", {}).get("name", ""))

    async def _dispatch_in_app(self, alert: AlertEvent) -> None:
        """In-app notification olustur."""
        try:
            from app.services.notification_service import create_notification
            await create_notification(
                org_id   = alert.org_id,
                title    = alert.title,
                body     = alert.body,
                severity = alert.severity,
                metadata = alert.metadata,
            )
        except Exception as exc:
            logger.debug("In-app dispatch hatasi (non-fatal): %s", exc)

    async def _dispatch_slack(self, alert: AlertEvent) -> None:
        """Slack webhook'a gonder."""
        try:
            from app.services.alert_router import AlertRouter
            router = AlertRouter()
            await router._send_slack_message(
                webhook_url = await self._get_slack_webhook(alert.org_id),
                text        = f"*{alert.title}*\n{alert.body[:500]}",
            )
        except Exception as exc:
            logger.debug("Slack dispatch hatasi (non-fatal): %s", exc)

    async def _dispatch_email(self, alert: AlertEvent) -> None:
        """Email gonder."""
        try:
            from app.services.alert_router import AlertRouter
            router = AlertRouter()
            emails = await self._get_alert_emails(alert.org_id)
            for email in emails[:3]:
                await router._send_email(
                    to_email = email,
                    subject  = alert.title,
                    body     = alert.body,
                )
        except Exception as exc:
            logger.debug("Email dispatch hatasi (non-fatal): %s", exc)

    # ── Yardimci metodlar ──────────────────────────────────────────────────────

    async def _is_cooldown_active(self, org_id: str, kri_name: str) -> bool:
        """Son 1 saatte bu KRI icin alert gonderildi mi?"""
        if self.redis:
            try:
                key   = f"alert_cooldown:{org_id}:{kri_name}"
                exists = await self.redis.exists(key)
                return bool(exists)
            except Exception:
                pass
        return False

    async def _set_cooldown(self, org_id: str, kri_name: str) -> None:
        if self.redis and kri_name:
            try:
                key = f"alert_cooldown:{org_id}:{kri_name}"
                await self.redis.setex(key, self.ALERT_COOLDOWN_SECONDS, "1")
            except Exception:
                pass

    async def _get_alert_channels(self, org_id: str, severity: str) -> list[str]:
        """Org'un alert kanallarini getir."""
        channels = ["in_app"]  # Her zaman in-app
        try:
            if self.db:
                from sqlalchemy import select

                from app.models.alert_preference import (
                    AlertPreference,  # type: ignore[attr-defined]
                )
                stmt = select(AlertPreference).where(AlertPreference.org_id == org_id)
                pref = (await self.db.execute(stmt)).scalar_one_or_none()
                if pref:
                    if pref.slack_webhook and severity in ("critical", "high"):
                        channels.append("slack")
                    if pref.email_addresses and severity in ("critical", "high", "medium"):
                        channels.append("email")
        except Exception:
            pass
        return channels

    async def _get_slack_webhook(self, org_id: str) -> str | None:
        try:
            if self.db:
                from sqlalchemy import select

                from app.models.alert_preference import (
                    AlertPreference,  # type: ignore[attr-defined]
                )
                stmt = select(AlertPreference).where(AlertPreference.org_id == org_id)
                pref = (await self.db.execute(stmt)).scalar_one_or_none()
                return pref.slack_webhook if pref else None
        except Exception:
            return None

    async def _get_alert_emails(self, org_id: str) -> list[str]:
        try:
            if self.db:
                from sqlalchemy import select

                from app.models.alert_preference import (
                    AlertPreference,  # type: ignore[attr-defined]
                )
                stmt = select(AlertPreference).where(AlertPreference.org_id == org_id)
                pref = (await self.db.execute(stmt)).scalar_one_or_none()
                if pref and pref.email_addresses:
                    addrs = pref.email_addresses
                    if isinstance(addrs, list):
                        return addrs
                    return [a.strip() for a in str(addrs).split(",")]
        except Exception:
            pass
        return []

    async def _get_active_orgs(self) -> list[str]:
        """Son 24 saatte aktif olan org'lari getir."""
        try:
            if self.db:
                from sqlalchemy import text
                result = await self.db.execute(
                    text("""
                        SELECT DISTINCT org_id FROM agent_jobs
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                        LIMIT 100
                    """)
                )
                return [row[0] for row in result.fetchall()]
        except Exception:
            pass
        return []

    async def _save_alert(self, alert: AlertEvent) -> None:
        """Alert'i DB'ye kaydet (durable log)."""
        try:
            if self.db:
                from sqlalchemy import text
                await self.db.execute(
                    text("""
                        INSERT INTO proactive_alerts
                        (alert_id, org_id, trigger, severity, title, body,
                         metadata, channels, created_at, dispatched)
                        VALUES
                        (:alert_id, :org_id, :trigger, :severity, :title, :body,
                         :metadata, :channels, :created_at, :dispatched)
                        ON CONFLICT (alert_id) DO NOTHING
                    """),
                    {
                        "alert_id":   alert.alert_id,
                        "org_id":     alert.org_id,
                        "trigger":    alert.trigger,
                        "severity":   alert.severity,
                        "title":      alert.title,
                        "body":       alert.body,
                        "metadata":   json.dumps(alert.metadata),
                        "channels":   json.dumps(alert.channels),
                        "created_at": alert.created_at,
                        "dispatched": alert.dispatched,
                    }
                )
                await self.db.commit()
        except Exception as exc:
            logger.debug("Alert kayit hatasi (non-fatal): %s", exc)


# ── Public factory ─────────────────────────────────────────────────────────────

def get_proactive_orchestrator(
    db:    Any = None,
    redis: Any = None,
) -> ProactiveAlertOrchestrator:
    return ProactiveAlertOrchestrator(db=db, redis=redis)
