"""Kurumsallaşma Endeksi — score a family business's institutionalisation 0–100
from signals the platform already produces. No new instrumentation: this reads
authority policies, the SMMM review queue, the run ledger, defensibility packets,
analysis history and semantic snapshots.

Each dimension returns (score 0–100, why, [recommendations]). The overall score
is the weighted mean. Stored per computation so the trend is real.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.analysis_job import AnalysisJob
from app.models.authority_policy import AuthorityPolicy
from app.models.defensibility_packet import DefensibilityPacket
from app.models.report import Report, ReportFormat
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi

_JOURNAL_REPORT = "tr_muhasebe_journal"

WEIGHTS = {
    "financial_discipline": 0.20,
    "delegated_authority": 0.20,
    "decision_traceability": 0.20,
    "human_oversight": 0.15,
    "process_cadence": 0.15,
    "key_person_risk": 0.10,
}
LABELS = {
    "financial_discipline": "Finansal disiplin",
    "delegated_authority": "Delege edilmiş yetki",
    "decision_traceability": "Karar izlenebilirliği",
    "human_oversight": "İnsan gözetimi",
    "process_cadence": "Süreç ritmi",
    "key_person_risk": "Kilit-kişi riski (düşük = iyi)",
}


def _clamp(x: float) -> int:
    return max(0, min(100, round(x)))


def _grade(score: int) -> str:
    return "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "E"


async def _journal_payloads(org_id: str, db: AsyncSession) -> list[dict[str, Any]]:
    job_ids = (
        await db.execute(select(AnalysisJob.id).where(AnalysisJob.org_id == org_id))
    ).scalars().all()
    if not job_ids:
        return []
    rows = (
        await db.execute(
            select(Report).where(
                Report.job_id.in_(job_ids),
                Report.report_type == _JOURNAL_REPORT,
                Report.report_format == ReportFormat.JSON,
            )
        )
    ).scalars().all()
    return [r.data for r in rows if r.data]


# ── Dimensions ─────────────────────────────────────────────────────────────

async def _financial_discipline(org_id: str, db: AsyncSession, sig: dict) -> tuple[int, str, list[str]]:
    payloads = await _journal_payloads(org_id, db)
    sig["journal_reports"] = len(payloads)
    if not payloads:
        return 20, "Henüz muhasebe yevmiyesi işlenmemiş.", [
            "İlk dönemin işlemlerini yükleyip TR muhasebe analizini çalıştırın."
        ]
    balanced = sum(1 for p in payloads if p.get("dengeli"))
    confs = [float(p["ortalama_confidence"]) for p in payloads if p.get("ortalama_confidence") is not None]
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    entries = [e for p in payloads for e in (p.get("yevmiye_kayitlari") or [])]
    sig["journal_entries"] = len(entries)
    default_acct = sum(1 for e in entries if str(e.get("thp_hesap_kodu", "")).startswith("770")) if entries else 0
    generic_ratio = (default_acct / len(entries)) if entries else 1.0

    score = 100 * (0.4 * (balanced / len(payloads)) + 0.4 * min(1.0, avg_conf / 0.9) + 0.2 * (1 - generic_ratio))
    recs: list[str] = []
    if balanced < len(payloads):
        recs.append("Dengesiz dönem(ler) var — yevmiye denge hatalarını kapatın.")
    if generic_ratio > 0.5:
        recs.append("Giderlerin çoğu genel hesaba (770) düşüyor — hesap planı eşlemesini derinleştirin.")
    if avg_conf < 0.75:
        recs.append("Sınıflandırma güveni düşük — kategori kurallarını netleştirin.")
    return _clamp(score), f"{balanced}/{len(payloads)} dönem dengeli, ort. güven {avg_conf:.2f}.", recs


async def _delegated_authority(org_id: str, db: AsyncSession, sig: dict) -> tuple[int, str, list[str]]:
    policy = (
        await db.execute(
            select(AuthorityPolicy)
            .where(AuthorityPolicy.org_id == org_id, AuthorityPolicy.active.is_(True))
            .order_by(AuthorityPolicy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    sig["has_custom_authority_policy"] = policy is not None
    if policy is None:
        return 25, "Varsayılan yetki matrisi kullanılıyor — org'a özel delegasyon tanımlanmamış.", [
            "Yetki Matrisi'ni düzenleyin: harcama bantlarına göre onaylayıcıları (finans, sahip) tanımlayın."
        ]
    rules = policy.rules or []
    roles = {a.get("role") for r in rules for a in (r.get("approvals") or [])}
    sig["authority_rule_count"] = len(rules)
    sig["authority_distinct_roles"] = len(roles)

    payloads = await _journal_payloads(org_id, db)
    entries = [e for p in payloads for e in (p.get("yevmiye_kayitlari") or [])]
    escalated_no_rule = sum(
        1 for e in entries
        if (e.get("authority") or {}).get("outcome") == "needs_approval"
        and (e.get("authority") or {}).get("matched_rule_id") is None
    )
    unmatched_ratio = (escalated_no_rule / len(entries)) if entries else 0.0

    score = 40 + min(20, len(rules) * 4) + min(20, len(roles) * 10) + 20 * (1 - unmatched_ratio)
    recs = []
    if len(roles) < 2:
        recs.append("Tek onaylayıcı rolü var — en az bir ara kademe (ör. finans müdürü) ekleyin.")
    if unmatched_ratio > 0.1:
        recs.append(f"Kayıtların %{unmatched_ratio*100:.0f}'i hiçbir kurala uymadan yükseldi — matrisi genişletin.")
    return _clamp(score), f"{len(rules)} kural, {len(roles)} onay rolü tanımlı.", recs


async def _decision_traceability(org_id: str, db: AsyncSession, sig: dict) -> tuple[int, str, list[str]]:
    job_count = (
        await db.execute(
            select(func.count()).select_from(AnalysisJob).where(AnalysisJob.org_id == org_id)
        )
    ).scalar_one()
    run_count = (
        await db.execute(
            select(func.count()).select_from(AgentRun).where(AgentRun.org_id == org_id)
        )
    ).scalar_one()
    packets = (
        await db.execute(
            select(DefensibilityPacket).where(DefensibilityPacket.org_id == org_id)
        )
    ).scalars().all()
    finalized = sum(1 for p in packets if p.status == "finalized")
    sig.update(analysis_jobs=job_count, agent_runs=run_count,
               defensibility_packets=len(packets), finalized_packets=finalized)

    if job_count == 0:
        return 15, "Henüz analiz çalıştırılmamış.", ["İlk analiz işini çalıştırın."]
    ledger_cov = min(1.0, run_count / max(1, job_count))
    packet_cov = min(1.0, len(packets) / max(1, job_count))
    final_bonus = min(1.0, finalized / max(1, len(packets))) if packets else 0.0
    score = 100 * (0.45 * ledger_cov + 0.35 * packet_cov + 0.20 * final_bonus)
    recs = []
    if packet_cov < 0.5:
        recs.append("Dönemlerin çoğu için Savunulabilirlik Paketi üretilmemiş — her kapanışta oluşturun.")
    if packets and finalized == 0:
        recs.append("Hiçbir paket kesinleştirilmemiş — mali müşavir beyanıyla mühürleyin.")
    return _clamp(score), f"{run_count}/{job_count} çalışma defterde, {finalized} paket mühürlü.", recs


async def _human_oversight(org_id: str, db: AsyncSession, sig: dict) -> tuple[int, str, list[str]]:
    rows = (
        await db.execute(select(SMMMOnayKaydi).where(SMMMOnayKaydi.org_id == org_id))
    ).scalars().all()
    sig["review_queue_total"] = len(rows)
    if not rows:
        return 50, "Onay kuyruğunda kayıt yok — henüz insan incelemesi gereken işlem oluşmadı.", []
    actioned = [r for r in rows if r.durum != OnayDurumu.BEKLIYOR]
    pending = len(rows) - len(actioned)
    sig["review_pending"] = pending
    latencies = [
        (r.onay_zamani - r.created_at).total_seconds() / 3600
        for r in actioned
        if r.onay_zamani and r.created_at
    ]
    avg_h = sum(latencies) / len(latencies) if latencies else None

    throughput = len(actioned) / len(rows)
    latency_score = 1.0 if avg_h is None else max(0.0, 1 - avg_h / 168)  # 1 week → 0
    score = 100 * (0.7 * throughput + 0.3 * latency_score)
    recs = []
    if pending:
        recs.append(f"{pending} kayıt onay bekliyor — kuyruğu düzenli boşaltın.")
    if avg_h is not None and avg_h > 72:
        recs.append(f"Ortalama inceleme süresi {avg_h:.0f} saat — 48 saatin altına indirin.")
    return _clamp(score), f"{len(actioned)}/{len(rows)} kayıt karara bağlanmış.", recs


async def _process_cadence(org_id: str, db: AsyncSession, sig: dict) -> tuple[int, str, list[str]]:
    since = datetime.now(UTC) - timedelta(days=365)
    jobs = (
        await db.execute(
            select(AnalysisJob.created_at).where(
                AnalysisJob.org_id == org_id, AnalysisJob.created_at >= since
            )
        )
    ).scalars().all()
    months = {d.strftime("%Y-%m") for d in jobs if d}
    sig["active_months_12m"] = len(months)
    if not months:
        return 10, "Son 12 ayda analiz çalışması yok.", [
            "Aylık bir kapanış ritmi kurun — her ay verileri yükleyip analiz çalıştırın."
        ]
    score = min(100, len(months) / 12 * 100)
    recs = []
    if len(months) < 6:
        recs.append(f"Son 12 ayın yalnızca {len(months)} ayında aktivite var — aylık ritme geçin.")
    return _clamp(score), f"Son 12 ayın {len(months)} ayında analiz yapılmış.", recs


async def _key_person_risk(org_id: str, db: AsyncSession, sig: dict) -> tuple[int, str, list[str]]:
    approvers = (
        await db.execute(
            select(SMMMOnayKaydi.onaylayan_user_id).where(
                SMMMOnayKaydi.org_id == org_id,
                SMMMOnayKaydi.onaylayan_user_id.is_not(None),
            )
        )
    ).scalars().all()
    counts = Counter(a for a in approvers if a)
    sig["distinct_approvers"] = len(counts)
    if not counts:
        return 45, "Henüz onay geçmişi yok — dağılım ölçülemiyor.", [
            "Onayları birden fazla kişiye dağıtın; tek imza noktası kilit-kişi riskidir."
        ]
    total = sum(counts.values())
    top_share = max(counts.values()) / total
    sig["top_approver_share"] = round(top_share, 3)
    score = 100 * (min(1.0, (len(counts) - 1) / 2) * 0.5 + (1 - top_share) * 0.5)
    recs = []
    if len(counts) < 2:
        recs.append("Tüm onaylar tek kişide — en az bir yedek onaylayıcı yetkilendirin.")
    elif top_share > 0.8:
        recs.append(f"Onayların %{top_share*100:.0f}'i tek kişide toplanıyor — dağıtın.")
    return _clamp(score), f"{len(counts)} farklı onaylayıcı, en yoğun kişi %{top_share*100:.0f}.", recs


_DIMS = {
    "financial_discipline": _financial_discipline,
    "delegated_authority": _delegated_authority,
    "decision_traceability": _decision_traceability,
    "human_oversight": _human_oversight,
    "process_cadence": _process_cadence,
    "key_person_risk": _key_person_risk,
}


async def compute_index(org_id: str, db: AsyncSession) -> dict[str, Any]:
    signals: dict[str, Any] = {}
    dimensions: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    for key, fn in _DIMS.items():
        score, why, recs = await fn(org_id, db, signals)
        dimensions.append({
            "key": key, "label": LABELS[key], "score": score,
            "weight": WEIGHTS[key], "why": why,
        })
        for text in recs:
            recommendations.append({"dimension": key, "text": text})

    overall = _clamp(sum(d["score"] * d["weight"] for d in dimensions))
    # surface the weakest dimensions' recs first
    order = {d["key"]: d["score"] for d in dimensions}
    recommendations.sort(key=lambda r: order.get(r["dimension"], 100))

    return {
        "overall_score": overall,
        "grade": _grade(overall),
        "dimensions": dimensions,
        "recommendations": recommendations,
        "signals": signals,
        "computed_at": datetime.now(UTC).isoformat(),
    }
