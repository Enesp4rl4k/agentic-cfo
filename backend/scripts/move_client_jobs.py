"""Move a client's old analyses into the client's own organisation (SMMM plan M1).

Dry-run by default: prints what would move and what would be refused, writes
nothing. Pass --apply to do it. Safe to re-run.

Usage (from backend/):
    python scripts/move_client_jobs.py --client <SMMMMusteriKayit id>
    python scripts/move_client_jobs.py --client <id> --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: F401 - registers the models
from app.database import engine, get_session_factory
from app.services.smmm_adopt import adopt_client_jobs


async def main(client_id: str, apply: bool) -> None:
    async with get_session_factory(engine())() as db:
        report = await adopt_client_jobs(db, client_id=client_id, dry_run=not apply)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if not apply:
        print("\n(dry-run: nothing was written. Re-run with --apply to move.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client", required=True, help="SMMMMusteriKayit id")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry-run)")
    args = ap.parse_args()
    asyncio.run(main(args.client, args.apply))
