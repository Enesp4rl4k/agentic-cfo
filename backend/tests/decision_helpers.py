"""Shared by the tests that pin a route's decision record."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.models.decision import Decision
from app.services.decisions import DecisionError


async def decisions_of(client: Any, org_id: str, **where: Any) -> list[Decision]:
    """The organisation's decisions, oldest first, filtered by column equality."""
    async with client._maker() as db:
        stmt = select(Decision).where(Decision.org_id == org_id)
        for column, value in where.items():
            stmt = stmt.where(getattr(Decision, column) == value)
        return list((await db.execute(stmt.order_by(Decision.decided_at, Decision.id))).scalars())


def record_fails(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """Make `record_decision` raise inside `module`: the effect it sits beside must not survive."""
    async def refuse(*_a: Any, **_k: Any) -> None:
        raise DecisionError("record refused")

    monkeypatch.setattr(f"{module}.record_decision", refuse)
