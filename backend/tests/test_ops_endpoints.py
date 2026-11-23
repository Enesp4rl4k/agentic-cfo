"""`/api/v1/ready` and `/api/v1/version`: what an operator and a proxy can ask without signing in.

Required checks (database, schema at head, Redis in production) answer 503; advisory ones (worker, the
outbox pass, the outbox backlog, failed mail) answer 200 with `degraded`. No answer carries an
exception text.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.api import ops
from app.core import heartbeat
from app.models.outbox_message import FAILED, PENDING, OutboxMessage
from tests.api_helpers import bellek_istemcisi


@pytest.fixture(autouse=True)
def _fresh_schema_cache() -> None:
    ops._reset_cache()


def message(key: str, status: str, age: timedelta) -> OutboxMessage:
    return OutboxMessage(
        key=key, org_id="o1", channel="email", recipient="r@example.test", subject="s", body="b",
        source="test", source_ref=key, status=status, created_at=datetime.now(UTC) - age,
    )


async def test_version_names_the_commit_and_the_migration_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("BUILD_TIME", "2026-11-23T10:00:00Z")
    async with bellek_istemcisi() as client:
        res = await client.get("/api/v1/version")
    data = res.json()["data"]
    assert res.status_code == 200
    assert data["commit"] == "abc1234" and data["built_at"] == "2026-11-23T10:00:00Z"
    assert len(data["schema_head"]) == 1


async def test_version_falls_back_to_the_image_tag_then_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("IMAGE_TAG", "9f8e7d6")
    async with bellek_istemcisi() as client:
        assert (await client.get("/api/v1/version")).json()["data"]["commit"] == "9f8e7d6"
        monkeypatch.delenv("IMAGE_TAG")
        assert (await client.get("/api/v1/version")).json()["data"]["commit"] == "unknown"


async def test_ready_on_a_healthy_development_stack_needs_no_login() -> None:
    async with bellek_istemcisi() as client:
        res = await client.get("/api/v1/ready")
    body = res.json()["data"]
    assert res.status_code == 200 and body["status"] == "ready"
    # Anonymous: verdicts only (details are for operators, see test_operator_ops.py).
    assert body["checks"]["database"] == "ok" and body["checks"]["migrations"] == "ok"
    assert body["checks"]["redis"] == "skipped"


async def test_an_overdue_pending_message_and_a_recent_failure_degrade_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from tests.api_helpers import kullanici

    monkeypatch.setattr(get_settings(), "platform_operator_emails", "ops@tiphys.io")
    async with bellek_istemcisi() as client:
        operator, _, _ = await kullanici(client, "ops@tiphys.io", role="analyst")
        async with client._maker() as db:  # type: ignore[attr-defined]
            db.add_all([
                message("old-pending", PENDING, timedelta(minutes=40)),
                message("fresh-pending", PENDING, timedelta(minutes=1)),
                message("failed-today", FAILED, timedelta(hours=2)),
                message("failed-last-week", FAILED, timedelta(days=7)),
            ])
            await db.commit()
        res = await client.get("/api/v1/ready", headers=operator)
        anonymous = (await client.get("/api/v1/ready")).json()["data"]
    outbox = res.json()["data"]["checks"]["outbox"]
    assert anonymous["checks"]["outbox"] == "degraded" and "pending_overdue" not in str(anonymous)
    assert res.status_code == 200  # advisory: the API still serves
    assert res.json()["data"]["status"] == "degraded"
    assert outbox["pending_overdue"] == 1 and outbox["failed_24h"] == 1


async def test_a_failing_database_is_not_ready_and_leaks_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(_db: Any) -> dict[str, Any]:
        raise RuntimeError("password authentication failed for user aicfo at db.internal")

    monkeypatch.setattr(ops, "_database", broken)
    async with bellek_istemcisi() as client:
        res = await client.get("/api/v1/ready")
    assert res.status_code == 503
    assert res.json()["data"]["status"] == "not_ready"
    assert "password" not in res.text and "db.internal" not in res.text
    assert res.json()["data"]["checks"]["migrations"] == "skipped"  # not asked: the database is down


async def test_a_database_behind_the_code_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.preflight import SchemaState

    async def behind(_conn: Any) -> SchemaState:
        return SchemaState("behind", "073_x", ("074_materiality_smmm_brief",))

    monkeypatch.setattr(ops, "schema_state", behind)
    async with bellek_istemcisi() as client:
        res = await client.get("/api/v1/ready")
    assert res.status_code == 503
    assert res.json()["data"]["checks"]["migrations"] == "fail"
    assert "073_x" not in res.text and "074_materiality" not in res.text  # the revision is for operators


def test_only_a_failed_required_check_is_a_503() -> None:
    ok = ops._check(True, required=True, code="ok")
    advisory_down = ops._check(False, required=False, code="x")
    required_down = ops._check(False, required=True, code="x")
    unknown = ops._check(None, required=True, code="x")
    assert ops.summarise({"a": ok}) == ("ready", 200)
    assert ops.summarise({"a": ok, "b": unknown}) == ("ready", 200)
    assert ops.summarise({"a": ok, "b": advisory_down}) == ("degraded", 200)
    assert ops.summarise({"a": required_down, "b": advisory_down}) == ("not_ready", 503)


# ── the broker checks, against a fake Redis ────────────────────────────────────


class FakeRedis:
    def __init__(self, *, alive: bool = True, ping_fails: bool = False, beat_age: float | None = 30.0) -> None:
        self.alive, self.ping_fails = alive, ping_fails
        self.beat = None if beat_age is None else str(time.time() - beat_age)

    async def ping(self) -> bool:
        if self.ping_fails:
            raise ConnectionError("nope")
        return True

    async def exists(self, key: str) -> int:
        return int(self.alive)

    async def get(self, key: str) -> str | None:
        return self.beat if key == f"{heartbeat.KEY_PREFIX}outbox_pass" else None

    async def aclose(self) -> None:
        return None


def use_redis(monkeypatch: pytest.MonkeyPatch, fake: FakeRedis) -> None:
    monkeypatch.setattr(ops, "redis_enabled", lambda: True)
    monkeypatch.setattr(ops, "_redis_client", lambda: fake)


async def test_a_live_worker_and_a_recent_outbox_pass_are_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    use_redis(monkeypatch, FakeRedis())
    checks = await ops._broker_checks(production=True)
    assert checks["redis"]["ok"] and checks["worker"]["ok"] and checks["scheduler"]["ok"]


async def test_a_missing_worker_and_a_stale_pass_are_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    use_redis(monkeypatch, FakeRedis(alive=False, beat_age=3 * 3600))
    checks = await ops._broker_checks(production=True)
    assert checks["worker"] == {**checks["worker"], "ok": False, "required": False, "code": "worker_not_seen"}
    assert checks["scheduler"]["ok"] is False and checks["scheduler"]["required"] is False
    assert ops.summarise({"redis": checks["redis"], "worker": checks["worker"]})[1] == 200


async def test_no_outbox_pass_ever_recorded_is_reported_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    use_redis(monkeypatch, FakeRedis(beat_age=None))
    checks = await ops._broker_checks(production=True)
    assert checks["scheduler"]["ok"] is False and checks["scheduler"]["last_pass_seconds_ago"] is None


async def test_an_unreachable_redis_is_required_in_production_only(monkeypatch: pytest.MonkeyPatch) -> None:
    use_redis(monkeypatch, FakeRedis(ping_fails=True))
    checks = await ops._broker_checks(production=True)
    assert checks["redis"]["ok"] is False and checks["redis"]["required"] is True
    assert checks["worker"]["ok"] is None  # not judged without a broker


async def test_the_beat_round_trips_through_age_seconds() -> None:
    store: dict[str, str] = {}

    class Client:
        async def get(self, key: str) -> str | None:
            return store.get(key)

    assert await heartbeat.age_seconds(Client(), "x") is None
    store[f"{heartbeat.KEY_PREFIX}x"] = str(int(time.time()) - 90)
    age = await heartbeat.age_seconds(Client(), "x")
    assert age is not None and 89 <= age <= 95


async def test_beat_without_a_broker_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none() -> None:
        return None

    monkeypatch.setattr("app.core.redis_client.get_redis", none)
    await heartbeat.beat("outbox_pass")


async def test_beat_records_a_timestamp_with_a_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []

    class Client:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    async def client() -> Client:
        return Client()

    monkeypatch.setattr("app.core.redis_client.get_redis", client)
    await heartbeat.beat("outbox_pass")
    (args, kwargs), = calls
    assert args[0] == f"{heartbeat.KEY_PREFIX}outbox_pass" and kwargs["ex"] == heartbeat.TTL_SECONDS
    assert SimpleNamespace(v=int(args[1])).v > 0
