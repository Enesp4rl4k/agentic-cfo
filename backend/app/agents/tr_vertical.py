"""
TR accounting vertical — the one flow taken to depth level L3 ("autopilot").

Chains the existing building blocks into a single unattended run:

    file (e-Fatura / bank statement / CSV / XLSX)
      → CFO pipeline      (P&L · cash flow · forecast · anomaly · reconciliation · verifier)
      → TR accounting     (THP classification · double-entry · trial balance)
      → board deck PDF

L3 means the chain runs end-to-end without a human in the loop *between* stages —
but it always stops at a single consolidated approval gate. It never
auto-approves: `approval_required` is surfaced for the UI / caller to hold on.

Every other C-suite role stays at its current depth (see
`app.platform.policies.PLATFORM_DEPTH`); only this vertical is L3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig, CFOState

logger = logging.getLogger(__name__)

TR_VERTICAL_DEPTH_LEVEL = 3


@dataclass
class TRVerticalResult:
    job_id: str
    stage: str                         # ingest | cfo | accounting | board_deck | done
    approval_required: bool = False
    approval_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cfo: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] | None = None
    accounting: dict[str, Any] | None = None
    accounting_journal: list[dict[str, Any]] | None = None  # full journal, not serialized
    board_deck_pdf_bytes: bytes | None = None
    board_deck_pdf_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "approval_required": self.approval_required,
            "approval_reasons": self.approval_reasons,
            "errors": self.errors,
            "cfo": self.cfo,
            "reconciliation": self.reconciliation,
            "accounting": self.accounting,
            "board_deck_pdf_size": len(self.board_deck_pdf_bytes or b""),
            "board_deck_pdf_path": self.board_deck_pdf_path,
        }


def _trim_cfo_state(state: CFOState) -> dict[str, Any]:
    """Keep the board-relevant slice of the CFO state; drop bulky raw fields."""
    return {
        "halted": state.get("halted", False),
        "awaiting_review": state.get("awaiting_review", False),
        "error": state.get("error"),
        "min_confidence": state.get("min_confidence"),
        "pnl": state.get("pnl"),
        "cashflow": state.get("cashflow"),
        "forecast": state.get("forecast"),
        "anomalies": state.get("anomalies") or [],
        "verifier_verdict": state.get("verifier_verdict"),
        "confidence_breakdown": state.get("confidence_breakdown"),
        "transaction_count": len(state.get("transactions") or []),
    }


def _board_deck_from(
    company_name: str,
    period: str,
    cfo: CFOState,
    accounting: dict[str, Any] | None,
) -> dict[str, Any]:
    pnl = cfo.get("pnl") or {}
    forecast = cfo.get("forecast") or {}
    anomalies = cfo.get("anomalies") or []
    runway = (forecast.get("scenarios", {}).get("base", {}) or {}).get("runway_months")

    net_margin = pnl.get("net_margin", 0) or 0
    health = 50
    if net_margin > 0.10:
        health = 80
    elif net_margin > 0:
        health = 65
    elif net_margin < -0.10:
        health = 30

    insights: list[dict[str, Any]] = []
    for a in anomalies[:5]:
        insights.append(
            {
                "title": a.get("title") or a.get("type") or "Anomali",
                "severity": a.get("severity", "medium"),
                "description": a.get("description") or a.get("message") or "",
            }
        )
    if accounting and not accounting.get("dengeli", True):
        insights.append(
            {
                "title": "Yevmiye dengesizliği",
                "severity": "high",
                "description": "; ".join(accounting.get("denge_hatalari") or [])[:400],
            }
        )
    if accounting and accounting.get("onay_bekleyen"):
        insights.append(
            {
                "title": "Onay bekleyen kayıtlar",
                "severity": "medium",
                "description": f"{accounting['onay_bekleyen']} yevmiye kaydı manuel onay bekliyor.",
            }
        )

    return {
        "company_name": company_name,
        "period": period,
        "health_score": health,
        "health_label": "healthy" if health >= 65 else ("watch" if health >= 45 else "at_risk"),
        "executive_summary": (pnl.get("narrative") or "")[:600] or "Dönem finansal özeti.",
        "top_priorities": [
            a.get("action")
            for a in (pnl.get("actions") or [])
            if isinstance(a, dict) and a.get("action")
        ][:4],
        "insights": insights,
        "cfo_data": {"pnl": pnl, "runway_months": runway},
        "kri_posture": {
            "kri_score": round(cfo.get("min_confidence", 1.0) * 10, 1),
            "counts": {
                "red": sum(1 for a in anomalies if a.get("severity") in ("critical", "high")),
                "amber": sum(1 for a in anomalies if a.get("severity") == "medium"),
                "green": 0,
            },
            "red_kris": [],
        },
    }


async def run_tr_vertical(
    *,
    job_id: str,
    file_path: str,
    file_type: str,
    org_id: str | None = None,
    period: str | None = None,
    company_name: str | None = None,
    run_config: AgentRunConfig | None = None,
    build_board_deck: bool = True,
    authority_rules: list[dict[str, Any]] | None = None,
) -> TRVerticalResult:
    """Run the full TR accounting vertical end-to-end and stop at the approval gate."""
    company = company_name or "Şirket"
    donem = period or job_id[:7]
    res = TRVerticalResult(job_id=job_id, stage="cfo")

    # ── 1. CFO pipeline (includes reconciliation + verifier) ─────────────────
    cfo_state = await run_cfo_pipeline(
        job_id=job_id,
        file_path=file_path,
        file_type=file_type,
        run_config=run_config,
        org_id=org_id,
        period=donem,
    )
    res.cfo = _trim_cfo_state(cfo_state)
    res.reconciliation = cfo_state.get("reconciliation")

    if cfo_state.get("halted"):
        res.stage = "cfo"
        res.errors.append(cfo_state.get("error") or "CFO pipeline halted")
        return res

    if cfo_state.get("awaiting_review"):
        res.approval_required = True
        res.approval_reasons.append("CFO pipeline flagged awaiting_review")
    recon = cfo_state.get("reconciliation") or {}
    if recon.get("action") == "hold_for_review":
        res.approval_required = True
        res.approval_reasons.append(
            "reconciliation hold: " + ", ".join(recon.get("ungrounded_claims") or [])
        )

    # ── 2. TR accounting (THP + double-entry) ───────────────────────────────
    res.stage = "accounting"
    transactions = cfo_state.get("transactions") or []
    try:
        from app.agents.accounting.orchestrator import run_muhasebe_pipeline

        acc = await run_muhasebe_pipeline(
            job_id=job_id,
            transactions=transactions,
            company_name=company,
            donem=donem,
            regional_packs=["tr"],
            include_full_journal=True,
            authority_rules=authority_rules,
        )
        # Keep the trimmed view on the result; hand the full journal to the caller.
        res.accounting_journal = acc.pop("yevmiye_kayitlari", None)
        res.accounting = acc
        if acc.get("hata"):
            res.errors.append(str(acc["hata"]))
        if not acc.get("dengeli", True):
            res.approval_required = True
            res.approval_reasons.append("yevmiye dengesiz (double-entry imbalance)")
        if acc.get("onay_bekleyen", 0):
            res.approval_required = True
            res.approval_reasons.append(
                f"{acc['onay_bekleyen']} yevmiye kaydı onay bekliyor"
            )
    except Exception as exc:  # accounting failure must not lose the CFO result
        logger.exception("TR vertical: accounting stage failed for job=%s", job_id)
        res.errors.append(f"accounting stage error: {exc}")

    # ── 3. Board deck PDF ──────────────────────────────────────────────────
    if build_board_deck:
        res.stage = "board_deck"
        try:
            from app.services.board_deck_pdf import BoardDeckPDFBuilder

            deck = _board_deck_from(company, donem, cfo_state, res.accounting)
            res.board_deck_pdf_bytes = BoardDeckPDFBuilder().build_pdf(deck)

            # Persist to disk so the API can hand it back on a later GET
            # (same pattern as report_agent.py writing the xlsx report).
            from pathlib import Path

            from app.config import get_settings

            out = Path(get_settings().storage_local_path) / "board_decks" / f"{job_id}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(res.board_deck_pdf_bytes)
            res.board_deck_pdf_path = str(out)
        except Exception as exc:
            logger.exception("TR vertical: board deck stage failed for job=%s", job_id)
            res.errors.append(f"board deck stage error: {exc}")

    res.stage = "done"
    logger.info(
        "TR vertical done: job=%s approval_required=%s reasons=%s errors=%d",
        job_id, res.approval_required, res.approval_reasons, len(res.errors),
    )
    return res
