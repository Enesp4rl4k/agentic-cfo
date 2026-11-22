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

from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.decision_log import DecisionLog
from app.services import decisions
from app.services.briefing_held import held_caveat, held_only_sentence
from app.services.briefing_numbers import _date_parts, verify_narrative_numbers
from app.services.cash_radar import _fmt, compute_cash_radar
from app.services.runway import runway_line


class BriefingNeedsAnalysis(Exception):
    """The organisation has no completed analysis for a decision to belong to."""


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
    # The text shown is always verified: a candidate the gate rejects is replaced by
    # the deterministic template, and `fallback_used` says that happened.
    verified: bool = True
    fallback_used: bool = False
    # Whether the bank balance is a proven figure. Without it the briefing says so
    # instead of stating a balance.
    balance_known: bool = True
    # Whether there is anything to say. A company with no balance and no items gets
    # no briefing rather than a made-up calm week.
    has_data: bool = True
    # Which statement the balance comes from and whether it is too old to call "now".
    balance_as_of: str | None = None
    balance_age_days: int = 0
    balance_stale: bool = False
    # The measured runway (`app.services.runway`, the forecast's own computation), or that there is none:
    # `runway_line` is the sentence the briefing carries (a critical one is its first); `runway_months` is
    # None unless the runway was measured; `runway_basis` is "assumed" when it rests on an assumption.
    runway_status: str = "no_balance"
    runway_months: float | None = None
    runway_level: str | None = None
    runway_basis: str | None = None
    runway_line: str = ""
    # A digest of everything above. The owner answers the briefing they saw; the
    # answer carries this back, and a briefing whose figures moved in between
    # (a new upload, a settled invoice) is not the one they answered.
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def briefing_fingerprint(briefing: MondayBriefing) -> str:
    import hashlib
    import json

    shown = {k: v for k, v in asdict(briefing).items() if k != "fingerprint"}
    payload = json.dumps(shown, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


OWNER_STATED_DONE_LABEL = "Yaptım (sahibi yaptığını bildirdi)"
_STATEMENT_OUTCOME = {"done": "reported_done", "deferred": "deferred", "dismissed": "dismissed"}


class BriefingChanged(Exception):
    """The briefing's figures are not the ones the owner answered."""


# More than this share of the inflow resting on estimates is "mostly estimated".
ESTIMATED_MAJORITY = 0.5

_MONTHS_TR = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)  # fmt: skip


def _tr_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {_MONTHS_TR[d.month - 1]}"


def _inflow_estimated_share(splits: list[Any]) -> float:
    """The part of the money coming in that rests on an estimate or an assumption."""
    total = sum(x.known_cents + x.estimated_cents + x.assumed_cents for x in splits)
    if total <= 0:
        return 0.0
    return sum(x.estimated_cents + x.assumed_cents for x in splits) / total


def _balance_note(as_of: str | None, age_days: int, stale: bool) -> str:
    """Where the balance comes from; a stale one says it may no longer be true."""
    if as_of is None:
        return ""
    if stale:
        return (
            f"{_tr_date(as_of)} tarihli ekstreye göre, {age_days} gün önceki bakiye; "
            "güncel kasanız farklı olabilir"
        )
    return f"{_tr_date(as_of)} ekstresine göre"


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
    not_included: list[str] | None = None,
    balance_as_of: str | None = None,
    balance_age_days: int = 0,
    balance_stale: bool = False,
    week_estimated_share: float = 0.0,
    horizon_estimated_share: float = 0.0,
    held_caveat: str = "",
    currency: str | None = None,
) -> tuple[str, str, str]:
    """Build the canonical 3-sentence briefing from verified radar facts."""
    balance_known = starting_cash_cents is not None

    # Sentence 1: Radar Net Change. Without a proven starting balance the radar only
    # knows the movement, so no balance is stated.
    if net_change_cents > 0:
        move = f"{_fmt(net_change_cents, currency)} tutarında net giriş beklenmektedir"
    elif net_change_cents < 0:
        move = f"{_fmt(abs(net_change_cents), currency)} tutarında net çıkış beklenmektedir"
    else:
        move = None
    note = _balance_note(balance_as_of, balance_age_days, balance_stale)
    note = f"; {note}" if note else ""
    if balance_known and move:
        sentence_1 = (
            f"Bu hafta net nakit pozisyonunuzda {move} "
            f"(tahmini hafta sonu bakiyesi: {_fmt(end_balance_cents, currency)}{note})."
        )
    elif balance_known:
        label = "son bilinen bakiye" if balance_stale else "bakiye"
        sentence_1 = (
            f"Bu hafta nakit pozisyonunuzda önemli bir net hareket beklenmemektedir "
            f"({label}: {_fmt(end_balance_cents, currency)}{note})."
        )
    elif move:
        sentence_1 = (
            f"Bu hafta radarda {move}; başlangıç bakiyeniz bilinmiyor, "
            f"bu yüzden hafta sonu bakiyesi hesaplanamadı."
        )
    else:
        sentence_1 = (
            "Bu hafta radarda net bir nakit hareketi görünmüyor; başlangıç bakiyeniz bilinmiyor."
        )

    if balance_known and week_estimated_share > ESTIMATED_MAJORITY:
        sentence_1 += " Bu haftaki girişlerin çoğu tahmini tarihlere dayanıyor."
    # Held documents are in no radar figure above: a material queue is said in the headline.
    sentence_1 += held_caveat

    # Sentence 2: Approaching Critical Liability
    if approaching_amount_cents > 0 and approaching_date:
        sentence_2 = (
            f"Bu haftanın en kritik yükümlülüğü, {approaching_date} vadeli "
            f"{_fmt(approaching_amount_cents, currency)} tutarındaki {approaching_title} ödemesidir."
        )
    else:
        sentence_2 = (
            "Radarda bu hafta vadesi gelen bir vergi veya kritik tedarikçi ödemesi görünmüyor."
        )

    # Sentence 3: Single Most Important Action
    if action_amount_cents > 0 and action_title:
        sentence_3 = f"Bu haftanın en önemli tek eylemi: {action_title} ({action_detail})."
    elif not balance_known:
        sentence_3 = (
            "Başlangıç bakiyesi bilinmediği için nakit açığı hesaplanamadı; "
            "son banka ekstrenizi yükleyin."
        )
    else:
        sentence_3 = "Radarda görünen kalemlerle bu hafta acil bir nakit açığı eylemi gerekmiyor."
        if balance_stale:
            sentence_3 += (
                " Ancak bu, güncel olmayabilecek eski bir ekstre bakiyesine dayanıyor; "
                "yeni ekstre yükleyin."
            )
        if horizon_estimated_share > ESTIMATED_MAJORITY:
            sentence_3 += " Beklenen girişlerin çoğu tahmine dayandığı için bu kesin değildir."
        if not_included:
            sentence_3 += f" Radara dahil değil: {', '.join(x.lower() for x in not_included)}."

    return sentence_1, sentence_2, sentence_3


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
        action_detail = f"{_fmt(top_rec['amount_cents'], radar.currency)} tutarındaki alacağın zamanında tahsilatını teyit edin."
        action_amount = top_rec["amount_cents"]
    else:
        action_type = "monitor"
        action_title = "Nakit takibi"
        action_detail = "Bu hafta nakit durumu dengeli seyrediyor."
        action_amount = 0

    opening = radar.opening_cash
    caveat = held_caveat(radar, week_1.outflow_cents if week_1 else 0)
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
        not_included=radar.not_included,
        balance_as_of=opening.as_of if opening else None,
        balance_age_days=opening.age_days if opening else 0,
        balance_stale=opening.stale if opening else False,
        week_estimated_share=_inflow_estimated_share([week_1.inflow_basis] if week_1 else []),
        horizon_estimated_share=_inflow_estimated_share([w.inflow_basis for w in radar.weeks]),
        held_caveat=caveat,
        currency=radar.currency,
    )
    # A company whose every document is held has an empty radar for a reason a person can fix:
    # saying "nothing to report" (or sending no briefing at all) would hide the queue.
    has_radar_data = (
        starting_cash is not None
        or any(w.receivables or w.payables for w in radar.weeks)
        or bool(radar.overdue_receivables)
        or radar.overdue_payables_cents > 0
        or radar.undated_receivables_cents > 0
        or radar.undated_payables_cents > 0
    )
    held_only = radar.held_documents is not None and not has_radar_data
    if held_only and radar.held_documents is not None:
        s1 = held_only_sentence(radar.held_documents, radar.currency)
    deterministic_full_text = f"{s1} {s2} {s3}"

    # If candidate narrative is provided (e.g. from LLM), run the anti-hallucination gate
    verified = True
    fallback_used = False
    final_text = deterministic_full_text

    if candidate_narrative and not held_only:  # a queue to answer is not narrated around
        allowed_amounts = {
            abs(net_change),
            abs(end_balance),
            abs(starting_cash) if starting_cash is not None else 0,
            approaching_amount,
            action_amount,
        }
        is_grounded = verify_narrative_numbers(
            candidate_narrative,
            allowed_amounts,
            allowed_plain=_date_parts(week_start, week_end, approaching_date),
        )
        if is_grounded:
            final_text = candidate_narrative.strip()
            # A narrative cannot lose the caveats the template would have carried.
            if opening and opening.stale:
                final_text += (
                    f" Not: bakiye {_tr_date(opening.as_of)} tarihli ekstreye dayanıyor "
                    f"({opening.age_days} gün önce); güncel olmayabilir."
                )
            if _inflow_estimated_share([w.inflow_basis for w in radar.weeks]) > ESTIMATED_MAJORITY:
                final_text += " Not: beklenen girişlerin çoğu tahmine dayanıyor."
            final_text += caveat
        else:
            # Rejection: fall back to the deterministic template.
            fallback_used = True
            final_text = deterministic_full_text

    runway = radar.runway
    runway_text = runway_line(runway) if runway else ""
    if runway_text and runway and runway["level"] == "critical":
        final_text = f"{runway_text} {final_text}"  # cash running out is the first thing said
    elif runway_text:
        final_text += f" {runway_text}"

    from app.services.awaiting_decisions import closing_note

    final_text += await closing_note(db, org_id, radar, bool(caveat) or held_only)
    has_data = has_radar_data or held_only

    briefing_id = f"brief_{org_id}_{anchor.strftime('%Y%W')}"

    briefing = MondayBriefing(
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
        balance_known=starting_cash is not None,
        has_data=has_data,
        balance_as_of=opening.as_of if opening else None,
        balance_age_days=opening.age_days if opening else 0,
        balance_stale=opening.stale if opening else False,
        runway_status=runway["status"] if runway else "no_balance",
        runway_months=runway["runway_months"] if runway else None,
        runway_level=runway["level"] if runway else None,
        runway_basis=runway["basis"] if runway else None,
        runway_line=runway_text,
    )
    return replace(briefing, fingerprint=briefing_fingerprint(briefing))


async def record_briefing_response(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    briefing: MondayBriefing,
    response: str,  # "done" | "deferred" | "dismissed"
    seen_fingerprint: str,
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
    if seen_fingerprint != briefing.fingerprint:
        raise BriefingChanged(
            "Bülten siz gördükten sonra değişti (yeni veri geldi). "
            "Güncel bülteni okuyup yeniden yanıtlayın."
        )

    # "Yaptım" is the owner's word, not a verified fact: nothing here has seen the payment.
    # The label says so wherever it is read, until a bank-statement line confirms it.
    response_labels = {
        "done": OWNER_STATED_DONE_LABEL,
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

    if job is None:
        raise BriefingNeedsAnalysis(
            "Bu bülten için kayıt açılamıyor: şirketin tamamlanmış bir analizi yok."
        )
    job_id = job.id

    # One decision per briefing: answering again changes the answer, it does not add a row.
    earlier = (
        (
            await db.execute(
                select(DecisionLog)
                .where(DecisionLog.org_id == org_id)
                .order_by(DecisionLog.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    existing = next(
        (
            d
            for d in earlier
            if isinstance(d.expected, dict)
            and d.expected.get("source") == "monday_briefing"
            and d.expected.get("briefing_id") == briefing.briefing_id
        ),
        None,
    )

    expected = {
        "source": "monday_briefing",
        "briefing_id": briefing.briefing_id,
        "week_start": briefing.week_start,
        "action_type": briefing.action_type,
        "expected_amount_cents": briefing.action_amount_cents,
        "approaching_obligation_amount_cents": briefing.approaching_amount_cents,
        # What the owner was shown when they answered.
        "fingerprint": briefing.fingerprint,
        "shown_text": briefing.full_text,
        "briefing_created_at": datetime.now(UTC).isoformat(),
    }

    actual = {
        "owner_response": response,
        "owner_response_label": response_labels[response],
        "responded_at": datetime.now(UTC).isoformat(),
        "note": note,
        # A statement by the owner until a bank-statement line confirms it.
        "verification": "owner_stated" if response == "done" else None,
    }

    decision_status = "open" if response == "deferred" else "closed"

    if existing is not None:
        # `expected` stays as first snapshotted: what was expected is never rewritten.
        existing.chosen_option_id = f"briefing_{response}"
        existing.chosen_option_label = response_labels[response]
        existing.rationale = note
        existing.actual = actual
        existing.status = decision_status
        existing.outcome_note = note
        await db.flush()
        await _record_statement(db, org_id, user_id, briefing, response, note)
        return existing

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
    await _record_statement(db, org_id, user_id, briefing, response, note)
    return decision


async def _record_statement(
    db: AsyncSession, org_id: str, user_id: str, briefing: MondayBriefing, response: str,
    note: str | None,
) -> None:
    """The owner's answer as a human statement in the decision record (same transaction).

    Answering again supersedes the earlier statement, so the record reads as a line."""
    standing, _ = await decisions.list_decisions(
        db, org_id, kind=DecisionKind.OWNER_STATEMENT.value, target_type="briefing",
        target_id=briefing.briefing_id, current_only=True, limit=1,
    )
    await decisions.record_decision(
        db, org_id=org_id, kind=DecisionKind.OWNER_STATEMENT, target_type="briefing",
        target_id=briefing.briefing_id, outcome=_STATEMENT_OUTCOME[response],
        decided_via=DecidedVia.HUMAN, decided_by=user_id, reason=note,
        evidence_refs=[
            {"type": "briefing", "id": briefing.briefing_id},
            {"type": "fingerprint", "id": briefing.fingerprint},
        ],
        after={
            "action_type": briefing.action_type, "action_title": briefing.action_title[:200],
            "action_amount_cents": briefing.action_amount_cents,
            "verification": "owner_stated" if response == "done" else None,
        },
        supersedes_id=standing[0].id if standing else None,
    )
