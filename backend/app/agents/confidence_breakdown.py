"""Confidence decomposition (differentiator #6).

`min_confidence` is one number and the verifier says "held at 0.72" — but not
*which* step dragged it there. This turns the run's `logs` (+ reflection +
reconciliation) into a per-component breakdown so the human knows exactly which
part of the analysis to check.

Pure function, no I/O — safe to call from any node or an API serializer.
"""
from __future__ import annotations

from typing import Any

from app.agents.state import CFOState
from app.platform.policies import (
    CONFIDENCE_AUTO_PROCEED_MIN,
    REFLECTION_WARN_THRESHOLD,
)

# Steps whose `confidence` only echoes the aggregate — not real components.
_ECHO_STEPS = {"verifier", "alert", "report"}


def build_confidence_breakdown(
    state: CFOState, *, threshold: float | None = None
) -> dict[str, Any]:
    thr = CONFIDENCE_AUTO_PROCEED_MIN if threshold is None else float(threshold)

    components: list[dict[str, Any]] = []
    for log in state.get("logs") or []:
        step = getattr(log, "step", None) or (log.get("step") if isinstance(log, dict) else None)
        conf = getattr(log, "confidence", None) if not isinstance(log, dict) else log.get("confidence")
        ok = getattr(log, "ok", True) if not isinstance(log, dict) else log.get("ok", True)
        detail = getattr(log, "detail", None) if not isinstance(log, dict) else log.get("detail")
        if step in _ECHO_STEPS or conf is None:
            continue
        components.append(
            {
                "step": step,
                "confidence": round(float(conf), 3),
                "ok": bool(ok),
                "detail": (detail or "")[:240] or None,
                "kind": "skill",
            }
        )

    # Reflection scores below the warn band are real drags on trust.
    for agent, entry in (state.get("reflection_scores") or {}).items():
        score = (entry or {}).get("overall_score")
        if score is None:
            continue
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        if score_f < REFLECTION_WARN_THRESHOLD:
            components.append(
                {
                    "step": f"reflection:{agent}",
                    "confidence": round(score_f, 3),
                    "ok": False,
                    "detail": f"narrative reflection score {score_f:.2f} < {REFLECTION_WARN_THRESHOLD:.2f}",
                    "kind": "reflection",
                }
            )

    # Reconciliation holding the run is a hard component at low confidence.
    recon = state.get("reconciliation") or {}
    if recon.get("action") and recon["action"] != "proceed":
        failures = recon.get("identity_failures") or recon.get("ungrounded_claims") or []
        components.append(
            {
                "step": "reconciliation",
                "confidence": 0.0 if recon["action"] == "halt" else 0.4,
                "ok": False,
                "detail": ("; ".join(failures))[:240] or recon["action"],
                "kind": "reconciliation",
            }
        )

    if not components:
        aggregate = float(state.get("min_confidence") or 1.0)
        return {
            "aggregate": round(aggregate, 3),
            "threshold": thr,
            "meets_threshold": aggregate >= thr,
            "binding_constraint": None,
            "components": [],
            "narrative": f"Güven {aggregate:.2f} — bileşen kırılımı yok.",
        }

    aggregate = min(c["confidence"] for c in components)
    weakest = min(components, key=lambda c: c["confidence"])
    for c in components:
        c["weakest"] = c is weakest

    gap = ", ".join(
        f"{c['step']} {c['confidence']:.2f}"
        for c in sorted(components, key=lambda c: c["confidence"])[:3]
    )
    meets = aggregate >= thr
    narrative = (
        f"Genel güven {aggregate:.2f} (eşik {thr:.2f}). "
        + ("Eşiği geçiyor. " if meets else "Eşiğin altında — insan onayı. ")
        + f"En zayıf halka: {weakest['step']} ({weakest['confidence']:.2f})"
        + (f" — {weakest['detail']}" if weakest.get("detail") else "")
        + f". Zayıf bileşenler: {gap}."
    )

    return {
        "aggregate": round(aggregate, 3),
        "threshold": thr,
        "meets_threshold": meets,
        "binding_constraint": weakest["step"],
        "components": components,
        "narrative": narrative,
    }
