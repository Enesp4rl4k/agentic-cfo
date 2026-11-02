"""Append every completed analysis to its company ledger (plan v9 §K1). Safe to re-run.

Usage (from backend/):
    python scripts/ledger_backfill.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: F401 - registers the models
from app.database import engine, get_session_factory
from app.services.ledger import backfill


async def main() -> None:
    async with get_session_factory(engine())() as db:
        print(await backfill(db))


if __name__ == "__main__":
    asyncio.run(main())
