"""
Actions & Execution API

CEO Onay Paneli (Human-in-the-Loop) ve Otonom Eylemleri yöneten API.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.models.user import User
from app.services.execution.action_runner import get_action_runner
from app.services.negotiation.boardroom_memory import get_boardroom_memory

router = APIRouter(tags=["actions"])
logger = logging.getLogger(__name__)


class ActionApproveRequest(BaseModel):
    custom_params: dict[str, Any] | None = None


class ActionRejectRequest(BaseModel):
    reason: str = "CEO tarafından uygun bulunmadı"


@router.get("/actions/pending")
async def get_pending_actions(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CEO onayını bekleyen aksiyon maddelerini listeler."""
    memory = get_boardroom_memory()
    pending = memory.list_pending_actions()
    return {
        "status": "success",
        "count": len(pending),
        "actions": [
            {
                "id": a.id,
                "debate_id": a.debate_id,
                "description": a.description,
                "responsible_agent": a.responsible_agent,
                "status": a.status,
                "created_at": a.created_at,
            }
            for a in pending
        ],
    }


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: str,
    body: ActionApproveRequest | None = None,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CEO'nun aksiyonu onaylayarak ilgili sisteme (ERP, Ads vb.) göndermesini sağlar."""
    runner = get_action_runner()
    params = body.custom_params if body else None
    result = await runner.execute_action(
        action_id=action_id,
        approved_by_user_id=getattr(user, "email", "CEO"),
        custom_params=params,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return {
        "status": "executed",
        "action_id": action_id,
        "result": {
            "message": result.message,
            "target_system": result.target_system,
            "payload": result.payload,
            "timestamp": result.timestamp,
        },
    }


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: str,
    body: ActionRejectRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CEO'nun aksiyonu reddetmesi."""
    runner = get_action_runner()
    success = await runner.reject_action(
        action_id=action_id,
        rejected_by_user_id=getattr(user, "email", "CEO"),
        reason=body.reason,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Aksiyon bulunamadı.")
    return {"status": "rejected", "action_id": action_id, "reason": body.reason}
