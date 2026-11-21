"""
Action Execution & Human-in-the-Loop Runner

Yönetim kurulu kararlarından çıkan aksiyon maddelerini sınıflandırır. Hiçbir aksiyon
türü için gerçek bir bağlayıcı (Google Ads, ERP/açık bankacılık, takvim) yoktur; bu
yüzden çalıştırıcı hiçbir şeyi "yaptı" saymaz: sonuç her zaman `not_connected` ya da
bir ret nedenidir, aksiyon kaydı "executed" olmaz ve uydurma kimlik, tutar ya da yüzde
üretilmez. Bağlayıcı eklendiğinde ilgili `_KINDS` girdisi gerçek bir işlev alır.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.negotiation.boardroom_memory import (
    ActionItemRecord,
    get_boardroom_memory,
)

logger = logging.getLogger(__name__)


# Outcomes. Only a real, recorded action may ever be "executed"; none exists yet.
NOT_CONNECTED = "not_connected"
NOT_FOUND = "not_found"
ALREADY_EXECUTED = "already_executed"

NOT_CONNECTED_MESSAGE = "Bu işlem henüz bağlı değil — hiçbir şey yapılmadı."


@dataclass
class ExecutionResult:
    outcome: str
    message: str
    action_kind: str
    timestamp: str
    # Always False today: no action kind has a connector. Kept so a future real
    # connector has one place to say "done"; the API refuses to report success otherwise.
    success: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


def classify(action: ActionItemRecord) -> str:
    """Which kind of action this is (for the message only; nothing is run)."""
    desc = action.description.lower()
    agent = action.responsible_agent.upper()
    if "bütçe" in desc or "ads" in desc or "reklam" in desc or agent == "CMO":
        return "marketing_budget"
    if "vergi" in desc or "ödeme" in desc or "eft" in desc or "fatura" in desc or agent == "CFO":
        return "payment_draft"
    if "toplantı" in desc or "değerlendirme" in desc or "rapor" in desc:
        return "schedule"
    return "generic"


class ActionRunner:
    """Eylem sınıflandırıcı: bağlı olmayan bir eylemi dürüstçe "bağlı değil" diye bildirir."""

    def __init__(self) -> None:
        self.memory = get_boardroom_memory()

    async def execute_action(
        self,
        action_id: str,
        approved_by_user_id: str = "CEO",
        custom_params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Approve an action. With no connector it records nothing and says so."""
        now = datetime.now(UTC).isoformat()
        action = self.memory.get_action_by_id(action_id)
        if not action:
            return ExecutionResult(
                outcome=NOT_FOUND,
                message=f"Action ID '{action_id}' bulunamadı.",
                action_kind="none",
                timestamp=now,
            )
        if action.status == "executed":
            return ExecutionResult(
                outcome=ALREADY_EXECUTED,
                message="Bu eylem daha önce zaten icra edilmiş.",
                action_kind="none",
                timestamp=now,
            )

        kind = classify(action)
        logger.info("Action %s (%s) approved by %s: no connector, nothing executed", action_id, kind, approved_by_user_id)
        # Nothing is written to the action record: it stays pending, not "executed".
        return ExecutionResult(
            outcome=NOT_CONNECTED,
            message=NOT_CONNECTED_MESSAGE,
            action_kind=kind,
            timestamp=now,
        )

    async def reject_action(
        self,
        action_id: str,
        rejected_by_user_id: str = "CEO",
        reason: str = "CEO tarafından reddedildi",
    ) -> bool:
        """CEO tarafından aksiyonun iptal edilmesi."""
        return self.memory.update_action_status(
            action_id=action_id,
            status="rejected",
            execution_result={"rejected_by": rejected_by_user_id, "reason": reason},
        )


_global_action_runner: ActionRunner | None = None


def get_action_runner() -> ActionRunner:
    global _global_action_runner
    if _global_action_runner is None:
        _global_action_runner = ActionRunner()
    return _global_action_runner
