"""Issue a pilot invitation from the host: the way the very first operator account is created.

`REGISTRATION_MODE=invite_only` lets nobody sign up without an invitation, including the person who is
meant to operate the platform. Anyone who can run commands on the server may issue that first invitation
(host access is a larger power than an operator's). Later invitations are issued from the API
(`POST /api/v1/pilot/invite/generate`, by an operator).

Usage (from the backend container, with the production environment):
  python scripts/issue_pilot_invite.py --email you@example.com.tr --company "Tiphys Operasyon"

The invitation link is e-mailed to the address through the outbox; it is never printed here. With no mail
sender configured nothing is created and the command says so.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


async def run(email: str, company: str) -> int:
    from app.database import engine, get_session_factory
    from app.services import outbox, pilot_invites

    async with get_session_factory(engine())() as db:
        try:
            invite = await pilot_invites.issue(db, operator_id="host-cli", email=email, company_name=company)
        except pilot_invites.PilotInviteError as err:
            print(f"NOT CREATED: {err.detail}")
            return 1
        await db.commit()
        await outbox.deliver_pending(db)
        await db.commit()
    print(f"Invitation {invite.code} queued for {invite.email} (company: {invite.company_name}); expires {invite.expires_at}.")
    print("Check the outbox row status if the mail does not arrive (docs/ops/runbooks/login-and-email.md).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--company", required=True, help="the company the invited person will own")
    args = parser.parse_args()
    return asyncio.run(run(args.email, args.company))


if __name__ == "__main__":
    raise SystemExit(main())
