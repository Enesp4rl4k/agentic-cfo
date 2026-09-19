"""Assemble the SMMM Defensibility Packet (differentiator #4).

One hash-sealed record per (org, job/period) that answers, for every journal
entry: what was the basis, how did the AI classify it and how sure was it, did a
human review it (approve / correct / reject) or did the AI auto-post it, and
what did the independent reconciliation say. Draft is regenerable; `finalize`
freezes the payload and locks `content_hash`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.defensibility_packet import DefensibilityPacket
from app.models.report import Report, ReportFormat
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi

_JOURNAL_REPORT = "tr_muhasebe_journal"

# per-entry decision provenance
DS_AI_AUTO = "ai_auto_posted"          # AI classified, no review required
DS_HUMAN_OK = "human_approved"         # went to queue, SMMM approved as-is
DS_HUMAN_FIX = "human_corrected"       # SMMM changed the account code
DS_REJECTED = "rejected"               # SMMM rejected
DS_PENDING = "pending_review"          # queued, not yet actioned


class DefensibilityError(RuntimeError):
    pass


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _decision_source(entry: dict[str, Any], onay: SMMMOnayKaydi | None) -> str:
    if not entry.get("onay_gerekli"):
        return DS_AI_AUTO
    if onay is None:
        return DS_PENDING
    return {
        OnayDurumu.ONAYLANDI.value: DS_HUMAN_OK,
        OnayDurumu.DUZELTILDI.value: DS_HUMAN_FIX,
        OnayDurumu.REDDEDILDI.value: DS_REJECTED,
        OnayDurumu.BEKLIYOR.value: DS_PENDING,
    }.get(str(onay.durum), DS_PENDING)


def _item(entry: dict[str, Any], onay: SMMMOnayKaydi | None) -> dict[str, Any]:
    source = _decision_source(entry, onay)
    review: dict[str, Any] | None = None
    if onay is not None:
        review = {
            "status": onay.durum,
            "by_user_id": onay.onaylayan_user_id,
            "at": onay.onay_zamani.isoformat() if onay.onay_zamani else None,
            "note": onay.onay_notu,
            "corrected_account": onay.duzeltilmis_hesap_kodu,
            "corrected_account_name": onay.duzeltilmis_hesap_adi,
            "original_account": onay.otomatik_hesap_kodu or entry.get("thp_hesap_kodu"),
        }
    return {
        "kayit_id": entry.get("kayit_id"),
        "date": entry.get("tarih"),
        "description": entry.get("aciklama"),
        "amount_kurus": entry.get("toplam_borc"),
        "balanced": entry.get("dengeli"),
        "account_code": entry.get("thp_hesap_kodu"),
        "classification_confidence": entry.get("confidence"),
        "review_required": bool(entry.get("onay_gerekli")),
        "review_reason": entry.get("onay_neden") or None,
        "decision_source": source,
        "review": review,
        "source_transaction_id": entry.get("kaynak_islem_id"),
        "lines": entry.get("satirlar") or [],
    }


async def _load_journal(db: AsyncSession, job_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            select(Report)
            .where(
                Report.job_id == job_id,
                Report.report_type == _JOURNAL_REPORT,
                Report.report_format == ReportFormat.JSON,
            )
            .order_by(desc(Report.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not row.data:
        raise DefensibilityError(
            "Bu iş için muhasebe yevmiyesi bulunamadı — önce muhasebe analizi çalıştırın."
        )
    return row.data


async def build_packet(
    *, db: AsyncSession, job_id: str, org_id: str | None, period: str | None
) -> DefensibilityPacket:
    journal = await _load_journal(db, job_id)
    entries: list[dict[str, Any]] = journal.get("yevmiye_kayitlari") or []

    onay_rows = (
        await db.execute(
            select(SMMMOnayKaydi).where(SMMMOnayKaydi.job_id == job_id)
        )
    ).scalars().all()
    onay_by_kayit = {o.kayit_id: o for o in onay_rows}

    run = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.job_id == job_id)
            .order_by(desc(AgentRun.started_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    run_ref = (run.result_ref or {}) if run else {}

    items = [_item(e, onay_by_kayit.get(str(e.get("kayit_id") or ""))) for e in entries]
    counts: dict[str, int] = {}
    for it in items:
        counts[it["decision_source"]] = counts.get(it["decision_source"], 0) + 1

    total_amount = sum(int(it["amount_kurus"] or 0) for it in items)
    human_touched = counts.get(DS_HUMAN_OK, 0) + counts.get(DS_HUMAN_FIX, 0)

    summary = {
        "period": period,
        "job_id": job_id,
        "entry_count": len(items),
        "total_amount_kurus": total_amount,
        "by_decision_source": counts,
        "human_reviewed": human_touched,
        "ai_auto_posted": counts.get(DS_AI_AUTO, 0),
        "rejected": counts.get(DS_REJECTED, 0),
        "pending_review": counts.get(DS_PENDING, 0),
        "balanced": journal.get("dengeli"),
        "balance_errors": journal.get("denge_hatalari") or [],
        "avg_classification_confidence": journal.get("ortalama_confidence"),
        "reconciliation": run_ref.get("reconciliation"),
        "confidence_breakdown": run_ref.get("confidence_breakdown"),
        "min_confidence": run_ref.get("min_confidence"),
        "run": {
            "id": run.id if run else None,
            "status": run.status if run else None,
            "attempt": run.attempt if run else None,
            "latency_ms": run.latency_ms if run else None,
            "cost_usd": run.cost_usd if run else None,
        },
        "defensible": human_touched + counts.get(DS_AI_AUTO, 0) == len(items) and not counts.get(DS_PENDING),
    }
    payload = {"summary": summary, "entries": items, "thp_dagilim": journal.get("thp_dagilim") or {}}

    existing = (
        await db.execute(
            select(DefensibilityPacket).where(
                DefensibilityPacket.job_id == job_id,
                DefensibilityPacket.org_id == org_id,
            )
        )
    ).scalar_one_or_none()

    if existing and existing.status == "finalized":
        raise DefensibilityError("Bu dönem paketi zaten kesinleştirildi; yeniden üretilemez.")

    packet = existing or DefensibilityPacket(org_id=org_id, job_id=job_id)
    packet.period = period
    packet.status = "draft"
    packet.summary = summary
    packet.payload = payload
    packet.content_hash = content_hash(payload)
    if existing is None:
        db.add(packet)
    await db.commit()
    return packet


async def finalize_packet(
    *, db: AsyncSession, packet_id: str, user_id: str, statement: str
) -> DefensibilityPacket:
    packet = await db.get(DefensibilityPacket, packet_id)
    if packet is None:
        raise DefensibilityError("Paket bulunamadı.")
    if packet.status == "finalized":
        raise DefensibilityError("Paket zaten kesinleştirilmiş.")
    if not (statement or "").strip():
        raise DefensibilityError("Kesinleştirme için mali müşavir beyanı zorunludur.")
    pending = (packet.summary or {}).get("pending_review", 0)
    if pending:
        raise DefensibilityError(
            f"{pending} kayıt hâlâ onay bekliyor — kesinleştirmeden önce kuyruğu bitirin."
        )

    packet.smmm_statement = statement.strip()
    packet.finalized_by_user_id = user_id
    packet.finalized_at = datetime.now(UTC)
    packet.status = "finalized"
    # Re-hash the frozen payload + the statement so the seal covers the sign-off.
    packet.content_hash = content_hash(
        {"payload": packet.payload, "statement": packet.smmm_statement,
         "finalized_by": user_id}
    )
    await db.commit()
    return packet
