"""Test databases isolate their sessions (tests/db_helpers.py says why).

On `sqlite+aiosqlite:///:memory:` every session shared one connection, and a
session closing mid-way rolled back another's pending write — the order- and
load-dependent failures in the approval, category-rule and company-view tests.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Column, Integer, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import declarative_base

from tests.db_helpers import gecici_motor

_Base = declarative_base()


class _Satir(_Base):
    __tablename__ = "satir"
    id = Column(Integer, primary_key=True)


async def test_a_session_closing_does_not_undo_another_sessions_write():
    engine = gecici_motor()
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as yazan:
            yazan.add(_Satir(id=1))
            await yazan.flush()
            async with maker() as okuyan:      # a poller reads, then closes
                assert (await okuyan.execute(select(_Satir))).scalars().all() == []
            await yazan.commit()
        async with maker() as db:
            assert len((await db.execute(select(_Satir))).scalars().all()) == 1
    finally:
        await engine.dispose()


def test_no_test_builds_an_in_memory_async_engine():
    tests = Path(__file__).parent
    desen = re.compile(r"aiosqlite:///:memory:")
    kullananlar = [
        str(p.relative_to(tests)) for p in tests.rglob("*.py")
        if p.name not in {"db_helpers.py", Path(__file__).name}
        and desen.search(p.read_text(encoding="utf-8"))
    ]
    assert kullananlar == [], f"use tests.db_helpers.gecici_motor instead: {kullananlar}"
