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

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services import outbox

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

    def __init__(self, db: Any = None, redis: Any = None, slot: str | None = None) -> None:
        self.db    = db
        self.redis = redis
        # The scheduled slot (ledger period): alert ids derive from it, so a repeated slot repeats no alert.
        self.slot, self.save_failures = slot, 0

    def _alert_id(self, *key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join((self.slot, *key)))) if self.slot else str(uuid.uuid4())

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

            # Sirayla tara: orglar tek AsyncSession'i paylasir ve outbox yazimlari
            # eszamanli islem kabul etmez.
            results: list[Any] = []
            for oid in org_ids:
                try:
                    results.append(await self.scan_and_alert(oid))
                except Exception as exc:
                    results.append(exc)

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
        """KRIs the organisation has actually measured: CFO report + uploaded KRI file.

        This read `ctx.get("agent_results")` — CompanyContext is a dataclass with
        no such method — so it raised, was swallowed, and no org ever got a KRI
        alert. Had it worked, the alerts would have come from the risk kernel's
        invented indicators.
        """
        try:
            from app.agents.risk.gercek_kri import gercek_kri
            from app.services.company_context import get_company_context

            ctx = await get_company_context(org_id, self.db)
            cfo = getattr(ctx, "last_cfo_result", None) or {}
            kris, posture = gercek_kri(
                cfo.get("pnl"), cfo.get("forecast"), getattr(ctx, "last_risk_result", None)
            )
            if not kris:
                return None
            return {"kris": kris, "posture": posture}
        except Exception as exc:
            logger.warning("KRI hesaplama hatasi: org=%s err=%s", org_id, exc)
            return None

    # ── Alert olusturma ────────────────────────────────────────────────────────

    async def _create_kri_alert(
        self, org_id: str, kri: dict[str, Any], severity: str
    ) -> AlertEvent | None:
        name  = kri.get("name", "Bilinmeyen KRI")
        val   = kri.get("current_value", 0)
        unit  = kri.get("unit", "")
        ev    = kri.get("evidence", "")

        # A KRI that rests on an assumed balance (or an open account-identity question) is capped below critical
        # and says so, in the runway's own words.
        unproven = kri.get("basis") not in (None, "known") or bool(kri.get("identity_uncertain"))
        if unproven:
            severity = "high" if severity == "critical" else severity
        title = f"🚨 {name}: {val} {unit} — Kırmızı Eşik Aşıldı"
        body  = (
            f"**{name}** metrigi kritik seviyeye ulasti.\n\n"
            f"Mevcut Deger: **{val} {unit}**\n"
            f"Kanit: {ev}\n\n"
        )
        if unproven and kri.get("basis_note"):
            body += f"Dayanak sınırı: {kri['basis_note']}\n\n"

        # Mitigasyon onerileri
        mitigations = kri.get("mitigations") or []
        if mitigations:
            body += "**Onerileri Aksiyonlar:**\n"
            for i, m in enumerate(mitigations[:3], 1):
                body += f"{i}. {m}\n"

        return AlertEvent(
            alert_id   = self._alert_id(org_id, "kri_breach", name),
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
        """KRI icin cascade simulasyonu calistir, alert olustur.

        An alert is raised only from measured inputs. When the simulation lacks one the scan records
        "skipped: missing <inputs>" (visible to owner/admin in the alert history) and sends nothing.
        """
        try:
            from app.services.cascade_inputs import measured_baseline_with_basis
            from app.services.cascade_simulator import (
                CascadeInputsMissing,
                TriggerType,
                get_cascade_simulator,
            )
            trigger_str = kri.get("cascade_trigger", "")
            try:
                trigger = TriggerType(trigger_str)
            except ValueError:
                return None

            from app.services.company_context import get_company_context
            ctx = await get_company_context(org_id, self.db)
            cfo_r = (getattr(ctx, "last_cfo_result", None) or {}) if ctx else {}
            cfo_r = cfo_r.get("dashboard") or cfo_r
            baseline: dict[str, Any] = {}
            basis = None
            if self.db is not None:
                baseline, basis = await measured_baseline_with_basis(self.db, org_id)
            sim = get_cascade_simulator(
                pnl      = cfo_r.get("pnl"),
                cashflow = cfo_r.get("cashflow"),
                forecast = cfo_r.get("forecast"),
                chro_data = getattr(ctx, "last_chro_result", None) if ctx else None,
                cto_data  = getattr(ctx, "last_cto_result", None) if ctx else None,
                cmo_data  = getattr(ctx, "last_cmo_result", None) if ctx else None,
                coo_data  = getattr(ctx, "last_coo_result", None) if ctx else None,
                **baseline,
            )
            params = kri.get("cascade_params") or {}
            try:
                cascade = sim.simulate(trigger, **params)
            except CascadeInputsMissing as exc:
                await self._record_skipped(org_id, kri, exc.missing)
                return None
            base_sc = cascade.base_scenario

            if base_sc.overall_risk_score < 40:
                return None  # Dusuk risk → alert olusturma

            title = f"⚡ Zincirleme Risk: {kri.get('name', '')} → {', '.join(cascade.affected_domains[:3])}"
            from app.services.alert_basis import cascade_alert_text

            body, severity = cascade_alert_text(cascade, basis, base_sc.overall_risk_score)

            return AlertEvent(
                alert_id   = self._alert_id(org_id, "cascade_risk", str(kri.get("name", ""))),
                org_id     = org_id,
                trigger    = "cascade_risk",
                severity   = severity,
                title      = title,
                body       = body,
                metadata   = {
                    "basis":         basis.to_dict() if basis is not None else None,
                    "kri":           kri,
                    "cascade_score": base_sc.overall_risk_score,
                    "affected":      cascade.affected_domains,
                },
                channels   = await self._get_alert_channels(org_id, "high"),
                created_at = time.time(),
            )
        except Exception as exc:
            logger.warning("Cascade alert olusturma hatasi: %s", exc)
            return None

    async def _record_skipped(self, org_id: str, kri: dict[str, Any], missing: list[str]) -> None:
        """Log "skipped: missing <inputs>" (owner/admin see it in the alert history). Nothing is sent."""
        if self.db:
            from app.services.scan_skips import record_skipped

            await record_skipped(self.db, org_id, str(kri.get("name", "")), missing)

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
            alert_id   = self._alert_id(org_id, "kri_upcoming", name),
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
        """Alert'i tum kanallara ilet. Disa giden kanallar outbox'a yazilir (ADR 0003).

        Hicbir sey burada gonderilmez: Slack ve e-posta outbox satiri olur, teslimi ve
        yeniden denemeyi outbox gondericisi yapar. Bir kanal yazilamazsa hata
        `dispatch_errors`ta kalir ve `dispatched` dogru olmaz; sessizce yutulmaz.
        """
        senders = {
            "in_app": self._dispatch_in_app,
            "slack": self._dispatch_slack,
            "email": self._dispatch_email,
        }
        # One after another: the channels share one AsyncSession, which does not allow
        # concurrent operations (gather made the second outbox write fail).
        for channel in alert.channels:
            send = senders.get(channel)
            if send is None:
                continue
            try:
                await send(alert)
            except Exception as exc:
                alert.dispatch_errors.append(f"{channel}: {exc}")
                logger.warning(
                    "Alert dispatch hatasi: alert=%s channel=%s err=%s", alert.alert_id, channel, exc
                )

        alert.dispatched = not alert.dispatch_errors
        await self._save_alert(alert)
        await self._set_cooldown(alert.org_id, alert.metadata.get("kri", {}).get("name", ""))

    async def _dispatch_in_app(self, alert: AlertEvent) -> None:
        """In-app notification: one `InAppNotification` row (the bell). Failure goes up; `_dispatch_alert` records it."""
        if not self.db:
            raise RuntimeError("in_app: veritabani yok, bildirim yazilamadi")
        from app.models.in_app_notification import InAppNotification
        from app.models.proactive_alert import ProactiveAlert

        if await self.db.get(ProactiveAlert, alert.alert_id) is not None:
            return  # redelivery of an alert already logged: the bell has it

        level = {"critical": "critical", "high": "warning"}.get(alert.severity, "info")
        self.db.add(InAppNotification(
            org_id=alert.org_id,
            level=level,
            domain="cfo",
            source="proactive_alert",
            message=f"{alert.title}: {alert.body}"[:2000],
            action="escalate" if level == "critical" else "route",
            priority_score=1.0 if level == "critical" else 0.7 if level == "warning" else 0.5,
        ))
        await self.db.flush()

    async def _dispatch_slack(self, alert: AlertEvent) -> None:
        """Slack mesajini outbox'a yaz (webhook'u org tercihinden)."""
        if not self.db:
            raise RuntimeError("slack: veritabani yok, outbox'a yazilamadi")
        webhook_url = await self._get_slack_webhook(alert.org_id)
        if not webhook_url:
            raise RuntimeError("slack: org icin webhook tanimli degil")
        await outbox.enqueue_slack(
            self.db,
            key=f"proactive_alert:{alert.alert_id}:slack",
            org_id=alert.org_id,
            webhook_url=webhook_url,
            title=alert.title,
            message=f"*{alert.title}*\n{alert.body[:500]}",
            severity=alert.severity,
            source="proactive_alert",
            source_ref=alert.alert_id,
        )

    async def _dispatch_email(self, alert: AlertEvent) -> None:
        """E-postayi alici basina outbox'a yaz (en fazla 3 alici, eskisi gibi)."""
        if not self.db:
            raise RuntimeError("email: veritabani yok, outbox'a yazilamadi")
        for address in (await self._get_alert_emails(alert.org_id))[:3]:
            await outbox.enqueue(
                self.db,
                key=f"proactive_alert:{alert.alert_id}:email:{address}",
                org_id=alert.org_id,
                channel="email",
                recipient=address,
                subject=alert.title,
                body=alert.body,
                source="proactive_alert",
                source_ref=alert.alert_id,
            )

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

    async def _preference(self, org_id: str) -> Any:
        """The org's AlertPreference row, or None. A failed read is logged, not hidden."""
        if not self.db:
            return None
        from sqlalchemy import select

        from app.models.alert_preference import AlertPreference

        try:
            stmt = select(AlertPreference).where(AlertPreference.org_id == org_id)
            return (await self.db.execute(stmt)).scalar_one_or_none()
        except Exception as exc:
            logger.warning("Alert tercihi okunamadi: org=%s err=%s", org_id, exc)
            return None

    async def _get_alert_channels(self, org_id: str, severity: str) -> list[str]:
        """Org'un alert kanallarini getir (tercihte tanimli hedefler)."""
        channels = ["in_app"]  # Her zaman in-app
        pref = await self._preference(org_id)
        if pref:
            if pref.slack_webhook_url and severity in ("critical", "high"):
                channels.append("slack")
            if pref.email_recipients and severity in ("critical", "high", "medium"):
                channels.append("email")
        return channels

    async def _get_slack_webhook(self, org_id: str) -> str | None:
        pref = await self._preference(org_id)
        return pref.slack_webhook_url if pref else None

    async def _get_alert_emails(self, org_id: str) -> list[str]:
        pref = await self._preference(org_id)
        if not pref or not pref.email_recipients:
            return []
        try:
            addrs = json.loads(pref.email_recipients)  # stored as a JSON array
        except ValueError:
            addrs = str(pref.email_recipients).split(",")
        if not isinstance(addrs, list):
            return []
        return [str(a).strip() for a in addrs if str(a).strip()]

    async def _get_active_orgs(self) -> list[str]:
        """Orgs with an analysis or an agent job in the last 24 hours.

        This was raw SQL (CLAUDE.md law 4) in Postgres-only syntax
        (`NOW() - INTERVAL`): on SQLite it raised into an `except: pass` and
        the hourly scan covered no organisation at all. It also read only
        `agent_jobs`, so an org that only ran CFO analyses was never scanned
        (plan v6 §S0).
        """
        if not self.db:
            return []
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from app.models.agent_job import AgentJob
        from app.models.analysis_job import AnalysisJob

        since = datetime.now(UTC) - timedelta(hours=24)
        try:
            orgs: set[str] = set()
            for model in (AnalysisJob, AgentJob):
                rows = await self.db.execute(
                    select(model.org_id)
                    .where(model.created_at > since, model.org_id.isnot(None))
                    .distinct()
                )
                orgs.update(str(o) for o in rows.scalars())
            return sorted(orgs)[:100]
        except Exception as exc:
            logger.warning("Proactive scan: active-org query failed: %s", exc)
            return []

    async def _save_alert(self, alert: AlertEvent) -> None:
        """Persist the alert (durable log). Idempotent on `alert_id`."""
        if not self.db:
            return
        from app.models.proactive_alert import ProactiveAlert

        try:
            if await self.db.get(ProactiveAlert, alert.alert_id) is not None:
                return
            self.db.add(ProactiveAlert(
                alert_id=alert.alert_id,
                org_id=alert.org_id,
                trigger=alert.trigger,
                severity=alert.severity,
                title=alert.title,
                body=alert.body,
                metadata_json=json.dumps(alert.metadata),
                channels=json.dumps(alert.channels),
                created_at=alert.created_at,
                dispatched=alert.dispatched,
            ))
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            self.save_failures += 1
            logger.warning("Proactive alert not saved (alert_id=%s): %s", alert.alert_id, exc)


# ── Public factory ─────────────────────────────────────────────────────────────

def get_proactive_orchestrator(
    db:    Any = None,
    redis: Any = None, slot: str | None = None,
) -> ProactiveAlertOrchestrator:
    return ProactiveAlertOrchestrator(db=db, redis=redis, slot=slot)
