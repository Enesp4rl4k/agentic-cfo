"""After an organisation is erased, no registry-listed personal data is readable ANYWHERE for it.

`tests/test_org_erasure.py` proves the database. This proves the rest: files on the volume (every layout the code
writes), Redis keys, the in-process fallbacks, and the agent's episodic memory, which lives in a table the ORM
does not know. A second organisation's copies of all of them must survive.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from app.services import agent_memory as am
from app.services import conversation_memory as conv
from app.services import org_erasure as svc
from app.services.cache_service import get_cache_service
from tests.db_helpers import gecici_veritabani
from tests.test_org_erasure import _two_orgs


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def scan_iter(self, match: str = "*", count: int = 100) -> AsyncIterator[str]:
        import fnmatch

        for key in list(self.data):
            if fnmatch.fnmatch(key, match):
                yield key

    async def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self.data.pop(k, None) is not None)


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        yield m


@pytest.fixture
def redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()

    async def _get() -> FakeRedis:
        return fake

    monkeypatch.setattr("app.core.redis_client.get_redis", _get)
    return fake


@pytest.fixture
def memory(monkeypatch) -> am.AgentMemoryStore:
    store = am.AgentMemoryStore(backend="memory")
    monkeypatch.setattr(am, "_default_store", store)
    return store


def _episode(org: str) -> am.EpisodeRecord:
    return am.EpisodeRecord(org_id=org, agent="pnl_agent", period="2026-Q3", summary={"net": 1},
                            narrative=f"narrative about {org}")


def _plant_redis(r: FakeRedis, org: dict[str, Any], tag: str) -> list[str]:
    job, uid, oid = org["analysis_jobs"], org["users"][0], org["org"]
    keys = [f"conv:{uid}:{uid}:2026-11-20", f"company_context:{oid}", f"semantic:{oid}:2026-10",
            f"morning_brief:{oid}", f"monday_briefing:{oid}", f"temporal:{oid}:pnl_agent",
            f"cache:analytics:{oid}:kpis", f"ceo:{job}", f"ack:{job}:fp1"]
    for k in keys:
        r.data[k] = tag
    return keys


def _plant_files(root: Path, org: dict[str, Any]) -> list[Path]:
    job = org["analysis_jobs"]
    paths = [root / "uploads" / job / "statement.pdf", root / "uploads" / job / "datasources" / "hr" / "x.csv",
             root / "reports" / job / "report.pdf", root / "board_decks" / f"{job}.pdf",
             root / f"{job}_logo_tiger_2024_demo.csv"]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("ZZPIIA statement text")
    return paths


async def test_nothing_of_the_organisation_survives_outside_the_tables(
    maker, tmp_path: Path, redis: FakeRedis, memory: am.AgentMemoryStore
) -> None:
    async with maker() as db:
        a, b, _ = await _two_orgs(db)
    a_files, b_files = _plant_files(tmp_path, a), _plant_files(tmp_path, b)
    a_keys, b_keys = _plant_redis(redis, a, "a"), _plant_redis(redis, b, "b")
    memory.save(_episode(a["org"]))
    memory.save(_episode(b["org"]))
    conv._fallback_store[f"conv:{a['users'][1]}:s"] = [{"role": "user", "content": "ZZPIIA"}]
    conv._fallback_store[f"conv:{b['users'][1]}:s"] = [{"role": "user", "content": "ZZPIIB"}]
    cache = get_cache_service()
    cache._memory_cache[f"cache:x:{a['org']}"] = (9e12, {"v": "ZZPIIA"})
    cache._memory_cache[f"cache:x:{b['org']}"] = (9e12, {"v": "ZZPIIB"})

    async with maker() as db:
        res = await svc.erase_org(db, a["org"], storage_root=tmp_path)

    assert not [p for p in a_files if p.exists()], "files of the erased organisation remain on the volume"
    assert all(p.exists() for p in b_files)
    assert not [k for k in a_keys if k in redis.data], "Redis keys of the erased organisation remain"
    assert all(k in redis.data for k in b_keys)
    assert [e.org_id for e in memory._backend.all()] == [b["org"]]
    assert not [k for k in conv._fallback_store if a["users"][1] in k]
    assert any(b["users"][1] in k for k in conv._fallback_store)
    assert f"cache:x:{a['org']}" not in cache._memory_cache and f"cache:x:{b['org']}" in cache._memory_cache
    eph = res.counts["_ephemeral"]
    assert eph["redis_deleted"] == len(a_keys) and eph["agent_memory_deleted"] == 1
    for k in [*a_keys, a["org"]]:
        assert k not in repr(res.record.counts)


async def test_a_redis_outage_does_not_block_erasure_and_is_reported(
    maker, tmp_path: Path, monkeypatch, memory: am.AgentMemoryStore
) -> None:
    class Broken(FakeRedis):
        async def scan_iter(self, match: str = "*", count: int = 100) -> AsyncIterator[str]:
            raise ConnectionError("down")
            yield ""  # pragma: no cover

    async def _get() -> Broken:
        return Broken()

    monkeypatch.setattr("app.core.redis_client.get_redis", _get)
    monkeypatch.setattr("app.core.redis_client.mark_unavailable", lambda *_a, **_k: None)
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        res = await svc.erase_org(db, a["org"], storage_root=tmp_path)
    assert res.counts["_ephemeral"]["redis_failed"] == 1 and not res.already_erased


async def test_the_operator_is_told_which_third_party_copies_remain(maker, tmp_path: Path, redis, memory) -> None:
    async with maker() as db:
        a, _, _ = await _two_orgs(db)
        res = await svc.erase_org(db, a["org"], storage_root=tmp_path)
    follow = res.counts["_external_followup"]
    assert follow["stripe_customer"] == 1  # the seeder fills every text column
    assert follow["erp_integrations"] == 1 and follow["connector_connections"] == 1


async def test_the_sqlite_agent_memory_file_is_erased_per_organisation(maker, tmp_path: Path, redis, monkeypatch) -> None:
    store = am.AgentMemoryStore(backend="sqlite", db_path=str(tmp_path / "agent_memory.db"))
    monkeypatch.setattr(am, "_default_store", store)
    async with maker() as db:
        a, b, _ = await _two_orgs(db)
    store.save(_episode(a["org"]))
    store.save(_episode(b["org"]))
    async with maker() as db:
        res = await svc.erase_org(db, a["org"], storage_root=tmp_path)
    assert res.counts["_ephemeral"]["agent_memory_deleted"] == 1
    assert [e.org_id for e in store._backend.all()] == [b["org"]]
