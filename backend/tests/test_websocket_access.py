"""WebSocket routes authenticate and stay inside the caller's organisation.

`tests/test_route_access.py` walks every HTTP route and asks whether it checks
who is calling. WebSocket routes have no HTTP method, so that walk skipped them,
and both of the app's sockets were open:

- `/ws/alerts/{org_id}` accepted a connection with no token, and with a token
  never compared the token's organisation with the one in the path — anyone
  could listen to any company's live alerts.
- `/ws/chat` took no token at all and grounded its answer in whatever `job_id`
  and `org_id` the client sent.
"""
from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import ws_auth, ws_stream
from app.main import app
from app.models.analysis_job import AnalysisJob
from app.models.organization import Organization
from app.models.user import User
from app.services.auth import create_access_token, create_refresh_token
from tests.db_helpers import gecici_veritabani

ORG_A = str(uuid.uuid4())
ORG_B = str(uuid.uuid4())


def _flat(routes):
    for r in routes:
        if hasattr(r, "effective_candidates"):
            yield from _flat(r.effective_candidates())
        else:
            yield r


def _websocket_routes() -> list[Any]:
    out = []
    for r in _flat(app.routes):
        original = getattr(r, "original_route", r)
        if type(original).__name__ == "APIWebSocketRoute":
            out.append(original)
    return out


def test_the_websocket_walk_finds_the_sockets() -> None:
    """If the walk finds nothing, the test below passes vacuously."""
    paths = {r.path for r in _websocket_routes()}
    assert {"/ws/alerts/{org_id}", "/ws/chat"} <= paths


def test_every_websocket_route_authenticates() -> None:
    offenders = [
        r.path for r in _websocket_routes()
        if "ws_auth.websocket_caller(" not in inspect.getsource(r.endpoint)
    ]
    assert not offenders, (
        "kimlik doğrulamasız WebSocket rotası — ws_auth.websocket_caller(token) "
        "ile çağıranı çözün:\n  " + "\n  ".join(offenders)
    )


# ── the token rules ──────────────────────────────────────────────────────────

async def _user(maker, *, org_id: str | None, active: bool = True) -> User:
    async with maker() as db:
        if org_id and await db.get(Organization, org_id) is None:
            db.add(Organization(id=org_id, name=f"Org {org_id[:6]}", slug=org_id))
        user = User(
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            full_name="T",
            org_id=org_id,
            is_active=active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_only_an_active_users_access_token_identifies_a_caller() -> None:
    async with gecici_veritabani() as maker:
        user = await _user(maker, org_id=ORG_A)
        inactive = await _user(maker, org_id=ORG_A, active=False)
        async with maker() as db:
            access = create_access_token(user.id, user.email, "analyst")
            assert (await ws_auth.user_for_token(db, access)).id == user.id

            refresh = create_refresh_token(user.id)
            assert await ws_auth.user_for_token(db, refresh) is None
            assert await ws_auth.user_for_token(db, None) is None
            assert await ws_auth.user_for_token(db, "not-a-jwt") is None
            off = create_access_token(inactive.id, inactive.email, "analyst")
            assert await ws_auth.user_for_token(db, off) is None
            ghost = create_access_token(str(uuid.uuid4()), "g@example.com", "analyst")
            assert await ws_auth.user_for_token(db, ghost) is None


# ── the routes ───────────────────────────────────────────────────────────────

def _as(monkeypatch, user: Any) -> None:
    async def _caller(token: str | None, ip: str | None = None) -> Any:
        return user if token else None
    monkeypatch.setattr(ws_auth, "websocket_caller", _caller)


def _refused(path: str) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect(path) as ws:
            ws.receive_text()
    return exc.value.code


def test_alerts_without_a_token_are_refused(monkeypatch) -> None:
    _as(monkeypatch, SimpleNamespace(id="u1", org_id=ORG_A))
    assert _refused(f"/api/v1/ws/alerts/{ORG_A}") == ws_auth.REFUSED


def test_alerts_for_another_organisation_are_refused(monkeypatch) -> None:
    _as(monkeypatch, SimpleNamespace(id="u1", org_id=ORG_A))
    assert _refused(f"/api/v1/ws/alerts/{ORG_B}?token=t") == ws_auth.REFUSED


def test_alerts_for_ones_own_organisation_connect(monkeypatch) -> None:
    _as(monkeypatch, SimpleNamespace(id="u1", org_id=ORG_A))
    with TestClient(app).websocket_connect(f"/api/v1/ws/alerts/{ORG_A}?token=t") as ws:
        assert ws.receive_json()["type"] == "connected"


def test_chat_without_a_token_is_refused(monkeypatch) -> None:
    _as(monkeypatch, SimpleNamespace(id="u1", org_id=ORG_A))
    assert _refused("/api/v1/ws/chat") == ws_auth.REFUSED


@pytest.mark.asyncio
async def test_chat_grounds_only_in_the_callers_own_job(monkeypatch) -> None:
    """Another organisation's job reaches grounding as None; the caller's own passes."""
    async with gecici_veritabani() as maker:
        caller = await _user(maker, org_id=ORG_A)
        other = await _user(maker, org_id=ORG_B)
        async with maker() as db:
            theirs = AnalysisJob(
                user_id=other.id, org_id=ORG_B, filename="b.csv", file_path="b.csv", file_type="csv",
            )
            mine = AnalysisJob(
                user_id=caller.id, org_id=ORG_A, filename="a.csv", file_path="a.csv", file_type="csv",
            )
            db.add_all([theirs, mine])
            await db.commit()

        monkeypatch.setattr("app.database.session_factory", lambda: maker)
        grounded: list[dict[str, Any]] = []

        async def _prepare(**kwargs: Any) -> None:
            grounded.append(kwargs)
            return None

        monkeypatch.setattr("app.services.chat_grounding.prepare_grounded_chat", _prepare)

        await ws_stream._build_chat_prompt("nakit?", theirs.id, ORG_A, caller)
        assert grounded[-1]["job_id"] is None
        assert grounded[-1]["org_id"] == ORG_A

        await ws_stream._build_chat_prompt("nakit?", mine.id, ORG_A, caller)
        assert grounded[-1]["job_id"] == mine.id

        await ws_stream._build_chat_prompt("nakit?", str(uuid.uuid4()), ORG_A, caller)
        assert grounded[-1]["job_id"] is None
