"""What a person could not read from the screen, read from the test's own database.

Three commands, all against the API's SQLite file in `frontend/e2e/.run/`:

  outbox [recipient]       the e-mails the product wrote and did not deliver (JSON on stdout)
  invite-token <email>     the token in an invitation e-mail (the API only queues it; there is
                           no SMTP here, and no screen or endpoint shows it)
  monday-tick              what the scheduler does every Monday: assemble each company's briefing
                           and put its e-mail in the outbox (the product's own job, run once)

Reads go through the product's models. Nothing here writes a row of its own.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent / ".run"
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(RUN)
os.environ.update({"USE_SQLITE": "true", "LOG_FORMAT": "plain", "LANGGRAPH_CHECKPOINT": "memory",
                   "OPENAI_API_KEY": "llm-placeholder-e2e", "SMTP_HOST": "", "SMTP_USER": ""})


def sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    return Session(create_engine("sqlite:///./aicfo_dev.db"))


def outbox(recipient: str | None) -> list[dict]:
    from sqlalchemy import select

    from app.models.outbox_message import OutboxMessage as M

    with sync_session() as db:
        query = select(M).order_by(M.created_at)
        if recipient:
            query = query.where(M.recipient == recipient)
        return [
            {"recipient": r.recipient, "status": r.status, "subject": r.subject, "body": r.body,
             "source": r.source, "source_ref": r.source_ref, "last_error": r.last_error}
            for r in db.execute(query).scalars()
        ]


def invite_token(email: str) -> str | None:
    """The token is stored only as a digest; the invitation e-mail in the outbox carries the link.

    The sender here is a recorded no-op (SQLite, no SMTP), which keeps the text of the row."""
    import re

    from sqlalchemy import select

    from app.models.outbox_message import OutboxMessage as M

    with sync_session() as db:
        body = db.execute(
            select(M.body).where(M.kind == "org_invite", M.recipient == email).order_by(M.created_at.desc())
        ).scalars().first()
    found = re.search(r"token=([0-9a-f]{64})", body or "")
    return found.group(1) if found else None


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "outbox":
        print(json.dumps(outbox(sys.argv[2] if len(sys.argv) > 2 else None), ensure_ascii=False))
    elif cmd == "invite-token":
        print(json.dumps({"token": invite_token(sys.argv[2])}))
    elif cmd == "monday-tick":
        from app.scheduler import _dispatch_monday_briefings

        asyncio.run(_dispatch_monday_briefings())
        print(json.dumps({"ok": True}))
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
