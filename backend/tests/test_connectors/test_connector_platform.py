"""Connector Platform (Faz 13) — adapter, runner idempotency, and the CTO flip."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401  — force full model registration for create_all
from app.connectors import registry
from app.connectors.base import (
    CanonicalRow,
    ConnectorHealth,
    ConnectorPayload,
    Watermark,
)
from app.connectors.crypto import decrypt_secret, encrypt_secret
from app.connectors.runner import run_connector_sync
from app.database import Base
from app.models.canonical_eng_signal import CanonicalEngSignal
from app.models.connector_connection import ConnectorConnection

pytestmark = pytest.mark.connectors


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


class _StubConnector:
    name = "stub"
    domain = "engineering"
    kernel_role = None

    def __init__(self) -> None:
        self.calls: list[Watermark] = []
        self.rows: list[CanonicalRow] = []

    async def health(self, *, config: Mapping[str, Any], secret: Mapping[str, Any]) -> ConnectorHealth:
        return ConnectorHealth(ok=True, detail="stub ok", account="stub/acct")

    async def fetch(self, *, org_id, config, secret, since: Watermark, **_) -> ConnectorPayload:
        self.calls.append(since)
        return ConnectorPayload(rows=list(self.rows), next_watermark=Watermark(since=datetime.now(UTC)))


@pytest.fixture
def stub_connector():
    conn = _StubConnector()
    registry._CONNECTORS["stub"] = conn  # type: ignore[assignment]
    try:
        yield conn
    finally:
        registry._CONNECTORS.pop("stub", None)


async def _seed_connection(db, org_id="org-1", connector="stub") -> ConnectorConnection:
    row = ConnectorConnection(
        org_id=org_id, connector=connector, status="active",
        secret_enc=encrypt_secret('{"token": "x"}'), config_json="{}",
    )
    db.add(row)
    await db.commit()
    return row


# ── registry + crypto ───────────────────────────────────────────────────────

def test_registry_has_github():
    assert registry.has_connector("github")
    gh = registry.get_connector("github")
    assert gh.domain == "engineering"
    assert gh.kernel_role == "cto"


def test_crypto_roundtrip():
    blob = '{"token": "ghp_secret_value"}'
    enc = encrypt_secret(blob)
    assert enc != blob
    assert decrypt_secret(enc) == blob


def test_crypto_rejects_garbage():
    with pytest.raises(ValueError):
        decrypt_secret("not-a-fernet-token")


# ── github adapter normalisation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_github_adapter_normalizes(monkeypatch):
    from app.connectors.github import GitHubConnector

    class _FakeCommit:
        sha = "abc123"; message = "fix: thing"; author = "dev"; date = "2026-08-01T10:00:00Z"
        files_changed = 2; additions = 10; deletions = 3

    class _FakePR:
        number = 7; title = "feat: x"; author = "dev"; state = "closed"
        created_at = "2026-08-01T00:00:00Z"; merged_at = "2026-08-02T00:00:00Z"
        review_count = 1; comments = 2; additions = 5; deletions = 1; files_changed = 1

    class _FakeIssue:
        number = 9; title = "prod down"; state = "open"; labels = ["bug", "critical"]
        created_at = "2026-08-03T00:00:00Z"; closed_at = None; comments = 4

    class _FakeData:
        error = None
        commits = [_FakeCommit()]
        pull_requests = [_FakePR()]
        issues = [_FakeIssue()]

    class _FakeApi:
        def __init__(self, *a, **k): ...
        async def fetch(self, **k): return _FakeData()

    monkeypatch.setattr("app.services.github_connector.GitHubConnector", _FakeApi)

    payload = await GitHubConnector().fetch(
        org_id="org-1",
        config={"owner": "acme", "repo": "api"},
        secret={"token": "ghp_x"},
        since=Watermark(),
    )
    by_type = {r.signal_type: r for r in payload.rows}
    assert by_type["commit"].source_record_id == "commit:abc123"
    assert by_type["commit"].magnitude == 13
    assert by_type["pull_request"].source_record_id == "pr:7"
    assert by_type["pull_request"].magnitude == 24  # 24h cycle time
    assert by_type["incident"].source_record_id == "issue:9"  # bug+critical → incident
    assert payload.next_watermark.since is not None


# ── runner: idempotency + bookkeeping ──────────────────────────────────────

@pytest.mark.asyncio
async def test_runner_upsert_is_idempotent(db, stub_connector):
    await _seed_connection(db)
    stub_connector.rows = [
        CanonicalRow(source_record_id="commit:1", signal_type="commit",
                     occurred_at=datetime.now(UTC), magnitude=5),
        CanonicalRow(source_record_id="pr:1", signal_type="pull_request",
                     occurred_at=datetime.now(UTC), magnitude=12),
    ]

    r1 = await run_connector_sync(connector_name="stub", org_id="org-1", db=db)
    assert r1.ok and r1.records_written == 2

    # second run, same records → still 2 rows total, not 4
    r2 = await run_connector_sync(connector_name="stub", org_id="org-1", db=db)
    assert r2.ok

    count = len(
        (await db.execute(
            CanonicalEngSignal.__table__.select().where(CanonicalEngSignal.org_id == "org-1")
        )).all()
    )
    assert count == 2
    # watermark advanced → second fetch got a non-empty `since`
    assert stub_connector.calls[0].is_empty
    assert not stub_connector.calls[1].is_empty


@pytest.mark.asyncio
async def test_runner_records_fetch_failure(db, stub_connector):
    await _seed_connection(db)

    async def _boom(**_):
        raise RuntimeError("api exploded")

    stub_connector.fetch = _boom  # type: ignore[assignment]
    result = await run_connector_sync(connector_name="stub", org_id="org-1", db=db)
    assert result.ok is False
    assert "exploded" in (result.error or "")

    row = (await db.execute(
        ConnectorConnection.__table__.select().where(ConnectorConnection.org_id == "org-1")
    )).first()
    assert row.last_status == "error"


@pytest.mark.asyncio
async def test_runner_errors_without_connection(db, stub_connector):
    result = await run_connector_sync(connector_name="stub", org_id="org-nope", db=db)
    assert result.ok is False
    assert "no connection" in (result.error or "")


# ── the CTO provenance flip ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eng_signals_flip_cto_kernel_to_real(db):
    from app.agents.cto.cto_kernel import run_cto_kernel
    from app.services.eng_signals import (
        cto_existing_data_from_signals,
        summarize_eng_signals,
    )

    now = datetime.now(UTC)
    for i in range(12):
        db.add(CanonicalEngSignal(
            org_id="org-1", source="github", source_record_id=f"commit:{i}",
            signal_type="commit", occurred_at=now - timedelta(days=i),
            actor="dev", magnitude=40,
        ))
    db.add(CanonicalEngSignal(
        org_id="org-1", source="github", source_record_id="pr:1",
        signal_type="pull_request", occurred_at=now - timedelta(days=1),
        magnitude=18, attributes={"merged": True},
    ))
    db.add(CanonicalEngSignal(
        org_id="org-1", source="github", source_record_id="issue:1",
        signal_type="incident", occurred_at=now - timedelta(days=2), magnitude=3,
    ))
    await db.commit()

    summary = await summarize_eng_signals("org-1", db)
    assert summary is not None
    assert summary["commit_count"] == 12
    assert summary["pr_merged_count"] == 1
    assert summary["incident_count"] == 1

    existing = await cto_existing_data_from_signals("org-1", db)
    assert existing is not None and existing["_source"] == "github"

    out = await run_cto_kernel(
        pnl={"revenue": 12_000_000_00}, existing_cto_data=existing
    )
    assert out["output"]["data_source"] == "real"
    assert out["provenance"]["synthetic"] is False
    assert "github" in out["output"]["narrative"]


@pytest.mark.asyncio
async def test_no_signals_leaves_cto_kernel_synthetic(db):
    from app.agents.cto.cto_kernel import run_cto_kernel
    from app.services.eng_signals import cto_existing_data_from_signals

    existing = await cto_existing_data_from_signals("org-empty", db)
    assert existing is None

    out = await run_cto_kernel(pnl={"revenue": 12_000_000_00}, existing_cto_data=existing)
    assert out["provenance"]["synthetic"] is True
