"""What a cascade alert says about its basis, and how severe it may be.

Only a proven basis (cash and burn measured, nothing assumed, no open account-identity question) may be
critical, and only it may be called "kanıtlı": the same rule as the runway's own level. Anything else is
capped at `high` and states the runway's own assumption sentence.
"""
from __future__ import annotations

from typing import Any

from app.services.cascade_inputs import RunwayBasis


def cascade_alert_text(cascade: Any, basis: RunwayBasis | None, risk_score: float) -> tuple[str, str]:
    """The alert body (summary, actions, basis sentence) and its severity."""
    body = cascade.executive_summary + "\n\n**Acil Aksiyonlar:**\n"
    for action in cascade.immediate_actions[:3]:
        body += f"• {action}\n"
    body += "\n" + (basis.sentence() if basis is not None else "Dayanak: kasa bakiyesi bilinmiyor.")
    body += " Çalışan sayısı veya maaş verisi yoksa o kısımlar hesaba katılmadı."
    severity = "critical" if risk_score > 70 else "high"
    if basis is None or not basis.proven:
        severity = "high"
    return body, severity
