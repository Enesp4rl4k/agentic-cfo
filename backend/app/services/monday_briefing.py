"""Pazartesi Bülteni (Monday Morning Briefing) & Anti-Hallucination Gate.

Plan v10 §4 (O4) & Plan v11 Faz 3:
1. Deterministik 3 cümlelik kural:
   - Cümle 1: Radardaki net değişim ve hafta sonu bakiye tahmini.
   - Cümle 2: Bu haftanın en kritik yaklaşan yükümlülüğü (vergi, çek, büyük tedarikçi).
   - Cümle 3: En önemli tek eylem (tahsilatı öne çek, ödeme ertele, finansman).
2. Uydurma Sayı = 0 Doğrulayıcı Katmanı:
   - Sayılar defter ve radardan deterministik çıkarılır.
   - LLM anlatısı üretilirse bağımsız doğrulayıcı her sayıyı kaynakla denetler.
   - Uyuşmayan tek bir sayı bile varsa LLM metni reddedilir, deterministik şablon devreye girer.
3. Bültenden Aksiyona Karar Kaydı:
   - Patronun "Yaptım / Ertele / Gerek Yok" yanıtı DecisionLog modeline makinece doğrulanabilir
     beklenti ve sonuç alanlarıyla işlenir.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_log import DecisionLog
from app.services.cash_radar import _fmt, compute_cash_radar
from app.services.rag.grounding_validator import extract_numeric_claims


@dataclass(frozen=True)
class MondayBriefing:
    briefing_id: str
    org_id: str
    week_start: str
    week_end: str
    starting_cash_cents: int | None
    net_change_cents: int
    end_balance_cents: int
    approaching_title: str
    approaching_amount_cents: int
    approaching_date: str | None
    action_type: str
    action_title: str
    action_detail: str
    action_amount_cents: int
    sentence_radar: str
    sentence_obligation: str
    sentence_action: str
    full_text: str
    verified: bool = True
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _generate_deterministic_sentences(
    net_change_cents: int,
    end_balance_cents: int,
    starting_cash_cents: int | None,
    approaching_title: str,
    approaching_amount_cents: int,
    approaching_date: str | None,
    action_title: str,
    action_detail: str,
    action_amount_cents: int,
) -> tuple[str, str, str]:
    """Build the canonical 3-sentence briefing from verified radar facts."""
    # Sentence 1: Radar Net Change
    if net_change_cents > 0:
        sentence_1 = (
            f"Bu hafta net nakit pozisyonunuzda {_fmt(net_change_cents)} tutarında net giriş beklenmektedir "
            f"(tahmini hafta sonu bakiyesi: {_fmt(end_balance_cents)})."
        )
    elif net_change_cents < 0:
        sentence_1 = (
            f"Bu hafta net nakit pozisyonunuzda {_fmt(abs(net_change_cents))} tutarında net çıkış beklenmektedir "
            f"(tahmini hafta sonu bakiyesi: {_fmt(end_balance_cents)})."
        )
    else:
        sentence_1 = (
            f"Bu hafta nakit pozisyonunuzda önemli bir net hareket beklenmemektedir "
            f"(mevcut bakiye: {_fmt(end_balance_cents)})."
        )

    # Sentence 2: Approaching Critical Liability
    if approaching_amount_cents > 0 and approaching_date:
        sentence_2 = (
            f"Bu haftanın en kritik yükümlülüğü, {approaching_date} vadeli "
            f"{_fmt(approaching_amount_cents)} tutarındaki {approaching_title} ödemesidir."
        )
    else:
        sentence_2 = (
            "Bu hafta vadesi gelen acil bir vergi veya kritik tedarikçi ödemesi bulunmamaktadır."
        )

    # Sentence 3: Single Most Important Action
    if action_amount_cents > 0 and action_title:
        sentence_3 = f"Bu haftanın en önemli tek eylemi: {action_title} ({action_detail})."
    else:
        sentence_3 = "Bu hafta için acil bir nakit açığı eylemi gerekmemektedir; operasyonel akış normal seyretmektedir."

    return sentence_1, sentence_2, sentence_3


def verify_narrative_numbers(
    narrative: str,
    allowed_cents: set[int],
    *,
    rel_tol: float = 0.02,
) -> bool:
    """Anti-hallucination gate: Every numeric claim in narrative must map to a verified factual amount."""
    claims = extract_numeric_claims(narrative)
    if not claims:
        return True

    # Build allowed numbers in Lira (decimal)
    allowed_liras = {cents / 100.0 for cents in allowed_cents if cents is not None}
    # Also add absolute values
    allowed_liras.update({abs(l) for l in allowed_liras})

    for claim in claims:
        # Check if this claim matches any allowed lira figure within tolerance
        matched = any(
            abs(claim - allowed) <= max(1.0, allowed * rel_tol) for allowed in allowed_liras
        )
        if not matched:
            return False

    return True


async def assemble_monday_briefing(
    db: AsyncSession,
    org_id: str,
    anchor_date: date | None = None,
    candidate_narrative: str | None = None,
) -> MondayBriefing:
    """Assemble a deterministic 3-sentence Monday morning briefing from the company's ledger and radar."""
    anchor = anchor_date or datetime.now(UTC).date()
    radar = await compute_cash_radar(db, org_id, anchor_date=anchor)

    week_1 = radar.weeks[0] if radar.weeks else None
    week_start = week_1.start_date if week_1 else anchor.isoformat()
    week_end = week_1.end_date if week_1 else (anchor + timedelta(days=6)).isoformat()
    starting_cash = radar.starting_cash_cents
    net_change = week_1.net_cents if week_1 else 0
    end_balance = week_1.end_balance_cents if week_1 else (starting_cash or 0)

    # Find most critical approaching liability in week 1
    payables = week_1.payables if week_1 else []
    top_payable = max(payables, key=lambda p: p["amount_cents"]) if payables else None

    if top_payable:
        approaching_title = (
            top_payable.get("counterparty") or top_payable.get("description") or "Ödeme"
        )
        approaching_amount = top_payable["amount_cents"]
        approaching_date = top_payable.get("expected_date") or top_payable.get("due_date")
    else:
        approaching_title = ""
        approaching_amount = 0
        approaching_date = None

    # Top single action
    if radar.shortfall and radar.shortfall.actions:
        top_act = radar.shortfall.actions[0]
        action_type = top_act.get("type", "shortfall_action")
        action_title = top_act.get("title", "Nakit açığı önlemi")
        action_detail = top_act.get("detail", "")
        action_amount = top_act.get("amount_cents", radar.shortfall.shortfall_cents)
    elif week_1 and week_1.receivables:
        top_rec = max(week_1.receivables, key=lambda r: r["amount_cents"])
        action_type = "collection_followup"
        action_title = f"Tahsilat takibi: {top_rec.get('counterparty') or 'Müşteri'}"
        action_detail = f"{_fmt(top_rec['amount_cents'])} tutarındaki alacağın zamanında tahsilatını teyit edin."
        action_amount = top_rec["amount_cents"]
    else:
        action_type = "monitor"
        action_title = "Nakit takibi"
        action_detail = "Bu hafta nakit durumu dengeli seyrediyor."
        action_amount = 0

    s1, s2, s3 = _generate_deterministic_sentences(
        net_change_cents=net_change,
        end_balance_cents=end_balance,
        starting_cash_cents=starting_cash,
        approaching_title=approaching_title,
        approaching_amount_cents=approaching_amount,
        approaching_date=approaching_date,
        action_title=action_title,
        action_detail=action_detail,
        action_amount_cents=action_amount,
    )
    deterministic_full_text = f"{s1} {s2} {s3}"

    # If candidate narrative is provided (e.g. from LLM), run the anti-hallucination gate
    verified = True
    fallback_used = False
    final_text = deterministic_full_text

    if candidate_narrative:
        allowed_amounts = {
            abs(net_change),
            abs(end_balance),
            abs(starting_cash) if starting_cash is not None else 0,
            approaching_amount,
            action_amount,
        }
        is_grounded = verify_narrative_numbers(candidate_narrative, allowed_amounts)
        if is_grounded:
            final_text = candidate_narrative.strip()
        else:
            # Rejection: Fall back to deterministic template!
            fallback_used = True
            final_text = deterministic_full_text

    briefing_id = f"brief_{org_id}_{anchor.strftime('%Y%W')}"

    return MondayBriefing(
        briefing_id=briefing_id,
        org_id=org_id,
        week_start=week_start,
        week_end=week_end,
        starting_cash_cents=starting_cash,
        net_change_cents=net_change,
        end_balance_cents=end_balance,
        approaching_title=approaching_title,
        approaching_amount_cents=approaching_amount,
        approaching_date=approaching_date,
        action_type=action_type,
        action_title=action_title,
        action_detail=action_detail,
        action_amount_cents=action_amount,
        sentence_radar=s1,
        sentence_obligation=s2,
        sentence_action=s3,
        full_text=final_text,
        verified=verified,
        fallback_used=fallback_used,
    )


async def record_briefing_response(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    briefing: MondayBriefing,
    response: str,  # "done" | "deferred" | "dismissed"
    note: str | None = None,
) -> DecisionLog:
    """Record owner's response to the Monday briefing into the DecisionLog.

    Responses:
    - 'done': Yaptım (action taken, e.g. collection accelerated or payment deferred)
    - 'deferred': Ertele (delayed action, decision stays open for tracking)
    - 'dismissed': Gerek Yok (action rejected by human owner)
    """
    valid_responses = {"done", "deferred", "dismissed"}
    if response not in valid_responses:
        raise ValueError(f"response must be one of {valid_responses}, got: {response}")

    response_labels = {
        "done": "Yaptım",
        "deferred": "Ertele",
        "dismissed": "Gerek Yok",
    }

    # Find newest completed job for FK
    from app.models.analysis_job import AnalysisJob, JobStatus

    job = (
        await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.status == JobStatus.COMPLETED,
            )
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    job_id = job.id if job else str(uuid.uuid4())

    expected = {
        "source": "monday_briefing",
        "briefing_id": briefing.briefing_id,
        "week_start": briefing.week_start,
        "action_type": briefing.action_type,
        "expected_amount_cents": briefing.action_amount_cents,
        "approaching_obligation_amount_cents": briefing.approaching_amount_cents,
        "briefing_created_at": datetime.now(UTC).isoformat(),
    }

    actual = {
        "owner_response": response,
        "owner_response_label": response_labels[response],
        "responded_at": datetime.now(UTC).isoformat(),
        "note": note,
    }

    decision_status = "open" if response == "deferred" else "closed"

    decision = DecisionLog(
        org_id=org_id,
        job_id=job_id,
        topic=f"Pazartesi Bülteni: {briefing.action_title}",
        chosen_option_id=f"briefing_{response}",
        chosen_option_label=response_labels[response],
        rationale=note,
        expected=expected,
        actual=actual,
        status=decision_status,
        outcome_note=note,
        created_by=user_id,
    )
    db.add(decision)
    await db.flush()
    return decision
