"""Kim neye erişebilir — tek yerde, tek kuralla.

Before this module, tenancy was checked route by route, and mostly not:

- 62 routes took no authentication dependency at all, among them report and
  PDF downloads, transaction detail, chat over a job, the morning brief, and
  the LLM-running `/ceo/analyze` and `/audit/analyze`.
- 50 more authenticated the caller and then loaded the object by id without
  asking whose it was — including the SMMM approve / correct / reject routes,
  a cross-organisation *write*.
- The helper that did exist, `analysis._check_job_access`, skipped the check
  whenever the caller had no organisation, and the muhasebe routes let any
  organisation's "owner" into every other organisation's jobs: `owner` and
  `admin` are roles *within* an organisation, not across the platform.

The rule here is the only one: an object with an organisation belongs to that
organisation; an object without one belongs to the user who created it; an
object with neither belongs to nobody who can be named, and is refused.

Refusals are 404, not 403. "It exists and is not yours" is itself a fact
about somebody else's organisation.

`tests/test_route_access.py` walks every registered route and fails if one is
neither authenticated nor listed in `PUBLIC_ROUTES` with its reason, or takes
an object id without going through this module. A route cannot be added that
skips it without the test naming the route.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.user import User

NOT_FOUND = "Kayıt bulunamadı."


def can_access(user: User, *, org_id: Any, user_id: Any) -> bool:
    """Whether `user` may see an object owned by (`org_id`, `user_id`)."""
    if org_id:
        return bool(user.org_id) and str(user.org_id) == str(org_id)
    if user_id:
        return str(user.id) == str(user_id)
    return False


def ensure_tenant(user: User, *, org_id: Any, user_id: Any = None) -> None:
    """Raise 404 unless `user` may see the object. For non-job objects."""
    if not can_access(user, org_id=org_id, user_id=user_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)


async def load_owned_job(db: AsyncSession, job_id: str, user: User) -> AnalysisJob:
    """The job, if it exists and belongs to `user`; otherwise 404.

    For routes that already hold a session and user and cannot take
    `owned_job` as a dependency (the job id arrives in a body, say).
    """
    job = await db.get(AnalysisJob, job_id)
    if job is None or not can_access(user, org_id=job.org_id, user_id=job.user_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return job


async def owned_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisJob:
    """Dependency: resolve `{job_id}` to a job the caller owns, or 404.

    Declared on the route, so the check is visible in the dependency tree and
    the access test can see it — a check inside the body is invisible to it.
    """
    return await load_owned_job(db, job_id, current_user)


# Routes reachable without a user, and why. Anything absent from this list must
# authenticate; `tests/test_route_access.py` enforces it.
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/health"): "liveness probe",
    ("GET", "/api/v1/system/health"): "liveness probe",
    ("POST", "/api/v1/auth/register"): "creates the user",
    ("POST", "/api/v1/auth/login"): "issues the token",
    ("POST", "/api/v1/auth/refresh"): "exchanges a refresh token, which it verifies",
    ("GET", "/api/v1/auth/sso/providers"): "lists login options before login",
    ("GET", "/api/v1/auth/sso/{provider}/login"): "starts an SSO login",
    ("GET", "/api/v1/auth/sso/{provider}/callback"): "SSO provider redirect; verifies state",
    ("GET", "/api/v1/billing/plans"): "public price list",
    ("POST", "/api/v1/billing/webhook"): "Stripe; verifies the signature",
    ("GET", "/api/v1/webhooks/whatsapp"): "Meta verification handshake; checks the token",
    ("POST", "/api/v1/webhooks/whatsapp"): "Meta; verifies the signature",
    ("POST", "/api/v1/webhooks/slack"): "Slack; verifies the signature",
    ("GET", "/api/v1/open-banking/callback"): "bank OAuth redirect; verifies state",
    ("GET", "/api/v1/pilot/invite/validate"): "checks an invite code before sign-up",
    ("POST", "/api/v1/org/invite/accept"): "accepts an invite by its token",
    ("GET", "/api/v1/benchmark/sectors"): "static sector list, no tenant data",
    ("GET", "/api/v1/agent-graph/topology"): "static agent graph, no tenant data",
    ("GET", "/api/v1/open-banking/banks"): "static list of supported banks",
    # FastAPI's own schema and docs pages: the route list, no data. Candidates
    # for docs_url=None in production; that is a deployment decision.
    ("GET", "/openapi.json"): "API schema, no data",
    ("GET", "/docs"): "Swagger UI, no data",
    ("GET", "/docs/oauth2-redirect"): "Swagger UI OAuth redirect, no data",
    ("GET", "/redoc"): "ReDoc UI, no data",
}


# ── Server-sent events ───────────────────────────────────────────────────────
# A browser EventSource cannot send an Authorization header, which is why the
# progress stream took no user at all. The fix is not to put the session token
# in the URL — it would sit in server logs and browser history, reusable for
# its whole lifetime. The page asks for a ticket over an authenticated call; the
# ticket names one job and one user and expires, and the stream checks both.

STREAM_TICKET_TTL_SECONDS = 600


def _ticket_signature(job_id: str, user_id: str, expires: int) -> str:
    import hashlib
    import hmac

    from app.config import get_settings

    key = get_settings().secret_key.encode("utf-8")
    msg = f"stream|{job_id}|{user_id}|{expires}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def issue_stream_ticket(job_id: str, user_id: str) -> tuple[str, int]:
    import time

    expires = int(time.time()) + STREAM_TICKET_TTL_SECONDS
    return f"{user_id}.{expires}.{_ticket_signature(job_id, user_id, expires)}", STREAM_TICKET_TTL_SECONDS


async def stream_ticket_user(
    job_id: str,
    ticket: str = "",
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: the user a valid stream ticket for this job names, or 401.

    Ownership is checked again here rather than trusted from the moment the
    ticket was issued: a user moved out of the organisation inside the ticket's
    lifetime must not keep watching its jobs.
    """
    import hmac
    import time

    try:
        user_id, expires_s, signature = ticket.split(".", 2)
        expires = int(expires_s)
    except ValueError:
        raise HTTPException(status_code=401, detail="Geçersiz akış bileti.") from None
    expected = _ticket_signature(job_id, user_id, expires)
    if not hmac.compare_digest(signature, expected) or expires < int(time.time()):
        raise HTTPException(status_code=401, detail="Geçersiz ya da süresi dolmuş akış bileti.")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Geçersiz akış bileti.")
    await load_owned_job(db, job_id, user)
    return user


def current_user_org_matches(user: User, org_id: Any) -> bool:
    """For objects that carry only an organisation: the caller's, and set."""
    return bool(org_id) and bool(user.org_id) and str(user.org_id) == str(org_id)
