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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.organization import OrgMembership
from app.models.user import User, UserRole
from app.services.acting_role import acting_role

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


# ── Who may change what ─────────────────────────────────────────────────────
# Four classes of state-changing route, by the least role that may use them.
# The role is the caller's *membership* role in the organisation they are
# acting in (`users.org_id`), the same reading `org_erasure` and the briefing
# release use — not `users.role`, one global value.
#
#   contributor  brings data in and runs computations on it: file / document
#            upload, analysis start and rerun, data-source add. An `analyst` may
#            (the documented meaning of the role: "upload, run analysis"); a
#            viewer may not. Never a record-changing route.
#   writer   changes working data: correct a category, resolve a duplicate or
#            settlement match, approve a held run. Not viewer or analyst: an
#            analyst brings data in, a person who answers for the books decides
#            what it means.
#   decider  an owner's or admin's decision: connecting a bank or ERP, approving
#            an action that leaves the system, org-wide resets.
#   smmm     binds the official record: closing a month, finalising the
#            defensibility packet. An `smmm`; and, when the organisation has no
#            accountant at all, an owner, admin or cfo (owner decision
#            2026-11-13, `services/approval_authority.py`), so a company that
#            keeps its own books is not locked out of its month-end.
#
# A caller without an organisation has nothing to be read-only *in*: such a user
# only reaches their own objects (`can_access`), and the routes that need an
# organisation say so themselves (400). Cross-organisation access stays 404: the
# guard reads the role in the caller's own organisation, then the handler
# refuses the object that is not theirs.
WRITER_ROLES = frozenset({"owner", "admin", "cfo", "smmm"})
CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "cfo", "smmm", "analyst"})  # WRITER_ROLES + analyst (tested)
DECIDER_ROLES = frozenset({"owner", "admin"})
OWN_BOOKS_ROLES = frozenset({"owner", "admin", "cfo"})


def _refuse(needed: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=f"Bu işlem için {needed} gerekli; mevcut rolünüz bu işlemi yapamaz.",
    )


async def require_writer(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency: owner, admin, cfo or smmm in the acting organisation, or 403."""
    role = await acting_role(db, user) if user.org_id else None
    if role is not None and role not in WRITER_ROLES:
        raise _refuse("veriyi değiştirme yetkisi (viewer ve analyst salt okunurdur)")
    return user


async def require_member(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency for reads of an organisation's own queue: any member of the acting organisation.

    A viewer may read; a caller with no organisation has nothing to read (400, as the ledger's
    read routes answer). The rows are then selected by that organisation only, so another
    organisation's are never visible.
    """
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Bu işlem için bir organizasyon gerekli.")
    return user


async def require_contributor(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency: owner, admin, cfo, smmm or analyst in the acting organisation, or 403.

    ONLY for bringing data in and running computations on it (upload, analysis
    start / rerun, data-source add). Anything that changes or decides a record
    is `require_writer` or stricter.
    """
    role = await acting_role(db, user) if user.org_id else None
    if role is not None and role not in CONTRIBUTOR_ROLES:
        raise _refuse("veri yükleme ve analiz çalıştırma yetkisi (viewer salt okunurdur)")
    return user


async def require_platform_operator(user: User = Depends(get_current_user)) -> User:
    """Dependency: a platform operator (e-mail in `PLATFORM_OPERATOR_EMAILS`), or 403.

    Pilot invites and the pilot feedback of every company are platform-wide, not
    a company's: a company owner is not an operator. Empty list (the default)
    means nobody.
    """
    from app.config import get_settings

    if not is_platform_operator(user.email, get_settings().platform_operator_emails):
        raise _refuse("platform operatörü yetkisi")
    return user


def is_platform_operator(email: str | None, configured: str) -> bool:
    allowed = {e.strip().lower() for e in (configured or "").split(",") if e.strip()}
    return bool(email) and str(email).strip().lower() in allowed


async def require_decider(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency: owner or admin in the acting organisation, or 403."""
    role = await acting_role(db, user) if user.org_id else None
    if role is not None and role not in DECIDER_ROLES:
        raise _refuse("owner veya admin rolü")
    return user


def may_set_standing_rules(role: str | None) -> bool:
    """Creating or revoking a remembered statement mapping changes how every later statement of that
    format is booked: an owner, admin or the accountant."""
    return role in DECIDER_ROLES or role == UserRole.SMMM.value


async def require_decider_or_smmm(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency: owner, admin or smmm in the acting organisation, or 403."""
    role = await acting_role(db, user) if user.org_id else None
    if role is not None and not may_set_standing_rules(role):
        raise _refuse("owner, admin veya mali müşavir (smmm) rolü")
    return user


async def require_smmm(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency: the company's `smmm`, or its owner/admin/cfo when it has none."""
    role = await acting_role(db, user) if user.org_id else None
    if role is None or role == UserRole.SMMM.value:
        return user
    if role in OWN_BOOKS_ROLES:
        has_smmm = (
            await db.execute(
                select(OrgMembership.id)
                .where(OrgMembership.org_id == str(user.org_id), OrgMembership.role == UserRole.SMMM.value)
                .limit(1)
            )
        ).first()
        if has_smmm is None:
            return user
    raise _refuse("mali müşavir (smmm) rolü")


# Routes reachable without a user, and why. Anything absent from this list must
# authenticate; `tests/test_route_access.py` enforces it.
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/health"): "liveness probe",
    ("GET", "/api/v1/system/health"): "liveness probe",
    ("POST", "/api/v1/auth/register"): "creates the user",
    ("POST", "/api/v1/auth/login"): "issues the token",
    ("POST", "/api/v1/demo/guest"): "mints an isolated demo session without signup (gated by demo_mode)",
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
    ("POST", "/api/v1/email/inbound"): "mail provider webhook; verifies the shared secret, refuses all when unset",
    ("GET", "/api/v1/erp/parasut/callback"): "Paraşüt OAuth redirect; verifies a signed, expiring, single-use state",
    # FastAPI's own schema and docs pages: the route list, no data. Candidates
    # for docs_url=None in production; that is a deployment decision.
    ("GET", "/openapi.json"): "API schema, no data",
    ("GET", "/docs"): "Swagger UI, no data",
    ("GET", "/docs/oauth2-redirect"): "Swagger UI OAuth redirect, no data",
    ("GET", "/redoc"): "ReDoc UI, no data",
}


# ── Authorisation classes of state-changing routes ───────────────────────────
# Every POST / PUT / PATCH / DELETE route is exactly one of: public (above), guarded by
# `require_writer` / `require_decider` / `require_smmm` / `require_role`, guarded inline
# (INLINE_GUARDED, with how), or intentionally open to any member of the organisation
# (OPEN_ROUTES, with why). `tests/test_route_authorisation.py` fails on a route that
# is none of these, naming it; an entry here is a review decision, not a way to pass.

_COMPUTE_ROUTES = [
    ("POST", "/api/v1/advanced/board-deck-pdf"),
    ("POST", "/api/v1/advanced/nl-simulate"),
    ("POST", "/api/v1/analysis/{job_id}/causal"),
    ("POST", "/api/v1/analysis/{job_id}/sensitivity/matrix"),
    ("POST", "/api/v1/analysis/{job_id}/sensitivity/variable"),
    ("POST", "/api/v1/analytics/advanced-anomaly"),
    ("POST", "/api/v1/analytics/break-even"),
    ("POST", "/api/v1/analytics/cohort"),
    ("POST", "/api/v1/analytics/forecast-v2"),
    ("POST", "/api/v1/analytics/monte-carlo"),
    ("POST", "/api/v1/analytics/working-capital"),
    ("POST", "/api/v1/authority/evaluate"),
    ("POST", "/api/v1/benchmark/compare"),
    ("POST", "/api/v1/benchmark/from-org"),
    ("POST", "/api/v1/cascade/simulate"),
    ("POST", "/api/v1/ceo/analyze"),
    ("POST", "/api/v1/ceo/analyze-from-job/{job_id}"),
    ("POST", "/api/v1/ceo/export-pdf"),
    ("POST", "/api/v1/chat/agent"),
    ("POST", "/api/v1/chat/ceo"),
    ("POST", "/api/v1/chat/job/{job_id}"),
    ("POST", "/api/v1/comparison/multi-period"),
    ("POST", "/api/v1/counterfactual/simulate/cost"),
    ("POST", "/api/v1/counterfactual/simulate/headcount"),
    ("POST", "/api/v1/counterfactual/simulate/price"),
    ("POST", "/api/v1/cross-domain/analyze"),
    ("POST", "/api/v1/cross-domain/from-job"),
    ("POST", "/api/v1/cross-domain/from-org"),
    ("POST", "/api/v1/cto/analyze"),
    ("POST", "/api/v1/data-quality/validate"),
    ("POST", "/api/v1/macro/simulate"),
    ("POST", "/api/v1/multidomain-cf/headcount"),
    ("POST", "/api/v1/multidomain-cf/marketing"),
    ("POST", "/api/v1/multidomain-cf/tech"),
    ("POST", "/api/v1/negotiation/ask"),
    ("POST", "/api/v1/negotiation/budget-revision"),
    ("POST", "/api/v1/negotiation/cash-crisis"),
    ("POST", "/api/v1/negotiation/consensus"),
    ("POST", "/api/v1/query"),
    ("POST", "/api/v1/query/stream"),
    ("POST", "/api/v1/related-parties/check"),
    ("POST", "/api/v1/reports/pdf/cfo-summary"),
    ("POST", "/api/v1/reports/pdf/compliance-cert"),
    ("POST", "/api/v1/reports/pdf/executive-brief"),
    ("POST", "/api/v1/risk-cascade/analyze"),
    ("POST", "/api/v1/risk-cascade/from-job"),
    ("POST", "/api/v1/risk-cascade/from-org"),
    ("POST", "/api/v1/risk/cascade"),
    ("POST", "/api/v1/swot/analyze"),
    ("POST", "/api/v1/swot/from-job"),
    ("POST", "/api/v1/swot/from-org"),
    ("POST", "/api/v1/temporal/delta"),
    ("POST", "/api/v1/temporal/trends"),
    ("POST", "/api/v1/tetikler/dry-run"),
]

_PERSONAL_ROUTES = [
    ("DELETE", "/api/v1/auth/api-key"),
    ("POST", "/api/v1/auth/api-key"),
    ("DELETE", "/api/v1/chat/sessions/{session_id}"),
    ("POST", "/api/v1/compliance/erasure-request"),
    ("POST", "/api/v1/org/create"),
    ("POST", "/api/v1/org/switch"),
    ("POST", "/api/v1/pilot/feedback"),
    ("POST", "/api/v1/pilot/invite/use"),
    ("POST", "/api/v1/smmm/clients"),
    ("DELETE", "/api/v1/smmm/clients/{client_id}"),
    ("PUT", "/api/v1/smmm/clients/{client_id}"),
    ("POST", "/api/v1/smmm/register"),
    ("POST", "/api/v1/stream/{job_id}/ticket"),
]

_TEST_ROUTES = [
    ("POST", "/api/v1/security/ip-whitelist/test"),
]

OPEN_ROUTES: dict[tuple[str, str], str] = {
    **dict.fromkeys(_COMPUTE_ROUTES, "runs a calculation, simulation or LLM answer on data the caller can already read and returns it; stores nothing in the company record, the company context or a shared queue, sends nothing out"),
    **dict.fromkeys(_PERSONAL_ROUTES, "acts on the caller's own account, API key, chat session, accountant profile or sign-up/feedback; creates only their own new organisation; no existing organisation's record or other member's data"),
    **dict.fromkeys(_TEST_ROUTES, "checks an address against the configured whitelist; sends and stores nothing"),
}

INLINE_GUARDED: dict[tuple[str, str], str] = {
    ("PUT", "/api/v1/authority/policy"): "owner or admin, checked in the handler",
    ("POST", "/api/v1/briefing/monday/release"): "an active smmm membership of the acting organisation, checked in the handler (owner decision K10)",
    ("POST", "/api/v1/compliance/org-erasure/request"): "owner or admin by membership role",
    ("POST", "/api/v1/compliance/org-erasure/{request_id}/confirm"): "owner by membership role",
    ("POST", "/api/v1/ledger/plan-changes"): "payment_plan.propose: owner, admin, cfo or analyst may propose",
    ("POST", "/api/v1/ledger/plan-changes/{change_id}/approve"): "payment_plan: owner or admin decide",
    ("POST", "/api/v1/ledger/plan-changes/{change_id}/reject"): "payment_plan: owner or admin decide",
    ("POST", "/api/v1/ledger/plan-changes/{change_id}/withdraw"): "payment_plan.withdraw: only the person who proposed it, while it waits (the author check, not a role check)",
    ("POST", "/api/v1/org/invite"): "_require_admin: owner or admin",
    ("DELETE", "/api/v1/org/invites/{invite_id}"): "_require_admin: owner or admin",
    ("PATCH", "/api/v1/org/me"): "_require_admin: owner or admin",
    ("DELETE", "/api/v1/org/members/{user_id}"): "_require_admin: owner or admin; an admin cannot remove an admin or owner",
    ("POST", "/api/v1/related-parties"): "owner or admin, checked in the handler",
    ("DELETE", "/api/v1/related-parties/{party_id}"): "owner or admin, checked in the handler",
    ("PATCH", "/api/v1/related-parties/{party_id}"): "owner or admin, checked in the handler",
    ("PUT", "/api/v1/security/ip-whitelist"): "owner or admin, checked in the handler",
    ("POST", "/api/v1/smmm/onay/toplu-onayla"): "approval authority matrix (services/approval_authority.verdict): smmm, or owner/admin/cfo when the company has no smmm; never viewer or analyst",
    ("POST", "/api/v1/smmm/onay/{kayit_id}/duzeltle"): "approval authority matrix (services/approval_authority.verdict): smmm, or owner/admin/cfo when the company has no smmm; never viewer or analyst",
    ("POST", "/api/v1/smmm/onay/{kayit_id}/onayla"): "approval authority matrix (services/approval_authority.verdict): smmm, or owner/admin/cfo when the company has no smmm; never viewer or analyst",
    ("POST", "/api/v1/smmm/onay/{kayit_id}/reddet"): "approval authority matrix (services/approval_authority.verdict): smmm, or owner/admin/cfo when the company has no smmm; never viewer or analyst",
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
