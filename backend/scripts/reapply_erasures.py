"""Re-apply erasures after a restore from a backup that predates them (docs/ops/runbooks/db-restore.md).

Before restoring, export what was erased, as hashes (no personal data), from the database you are about to replace:

    python scripts/reapply_erasures.py --export > erased.json

After the restore, from the same directory:

    python scripts/reapply_erasures.py --apply < erased.json

`--apply` hashes every restored organisation and user id the way the erasure did and erases again the ones whose hash
is in the file. It is idempotent. The file holds hashes of random ids, not names or addresses.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    import app.models  # noqa: F401
    from app.database import engine, get_session_factory
    from app.models.erasure_record import OrgErasureRecord
    from app.services.privacy.erasure_flow import reapply_erased

    async with get_session_factory(engine())() as db:
        if args.export:
            rows = (await db.execute(select(OrgErasureRecord.org_hash, OrgErasureRecord.mode))).all()
            sys.stdout.write(json.dumps({str(h): str(m) for h, m in rows}, indent=1) + "\n")
            return 0
        sys.stdout.write(json.dumps(await reapply_erased(db, args.erased)) + "\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true")
    group.add_argument("--apply", action="store_true", help="read the exported JSON from standard input")
    parsed = parser.parse_args()
    parsed.erased = json.load(sys.stdin) if parsed.apply else {}  # stdin, not a path taken from the command line
    sys.exit(asyncio.run(_run(parsed)))
