"""Startup preflight: refuse a dangerous configuration, say loudly when one is only degraded.

`Settings.validate_production_security` catches the three mistakes it was written for. This module
is the wider list an operator needs before a company's data is on the box:

* FATAL (production only): the process would run, and run unsafely. Default or placeholder secrets,
  wildcard CORS with credentials, SQLite under `APP_ENV`, the public WhatsApp verify token; and, when
  `APP_ENV` says production or staging, the demo seed and e-mail links that point at localhost (with
  Postgres alone those two are warnings: the demo stack and a developer's compose run exactly so).
* APP_ENV must be set to a known value whenever the database is Postgres (`app_env_missing`): a production
  host that forgot it would otherwise run in "warnings only" mode for demo mode and localhost links.
* Mail-dependent features with no mail sender (`mail_required_no_sender`): invite-only registration and
  required e-mail verification both need a delivered e-mail; with none, nobody could ever get in. Fatal
  when APP_ENV says production or staging, a warning otherwise (the demo stack runs that way).
* WARN (always logged): safe but degraded. No mail sender, no LLM key, no error tracking, no proxy
  setting, no field-encryption key, nobody who can operate the platform.

"Production" is `USE_SQLITE=false`, or `APP_ENV` set to `production` or `staging`. Outside it a fatal
finding is logged as a warning, so a laptop is never blocked.

The schema check (`schema_state`) compares the database's Alembic revision with the head of the
code's migrations. The API reports it on `/api/v1/ready`; `python -m app.core.preflight --db` runs
both checks and exits non-zero, for the deploy script and the `migrate` step.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

FATAL = "fatal"
WARN = "warn"

# Substrings that mark a value as a template, whatever its length.
_PLACEHOLDER_MARKERS = ("change-this", "changeme", "change_me", "your-secret", "replace-me", "dev-secret")
_PUBLIC_WHATSAPP_VERIFY_TOKEN = "agentic-cfo-verify"
_PRODUCTION_ENVS = frozenset({"production", "prod", "staging"})
# The values APP_ENV may take. Postgres without one of them is fatal: say which you mean.
ALLOWED_APP_ENVS = ("production", "prod", "staging", "demo", "development", "dev", "ci", "test")
MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str


class PreflightError(RuntimeError):
    """Production configuration that must not start."""


def app_env(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return env.get("APP_ENV", "").strip().lower()


def is_production(settings: Settings, environ: Mapping[str, str] | None = None) -> bool:
    return (not settings.use_sqlite) or app_env(environ) in _PRODUCTION_ENVS


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return not lowered or any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_localhost(url: str) -> bool:
    lowered = url.strip().lower()
    return "localhost" in lowered or "127.0.0.1" in lowered or "[::1]" in lowered


def _fatal(code: str, message: str) -> Finding:
    return Finding(code, FATAL, message)


def _warn(code: str, message: str) -> Finding:
    return Finding(code, WARN, message)


def _secret_findings(settings: Settings, env: Mapping[str, str]) -> list[Finding]:
    out: list[Finding] = []
    secret = settings.backend_secret_key
    if _looks_like_placeholder(secret):
        out.append(_fatal("secret_placeholder", "BACKEND_SECRET_KEY is empty or a template value from .env.example."))
    elif len(secret) < MIN_SECRET_LENGTH:
        out.append(
            _fatal(
                "secret_short",
                f"BACKEND_SECRET_KEY has {len(secret)} characters; use at least {MIN_SECRET_LENGTH} "
                '(python -c "import secrets; print(secrets.token_hex(32))").',
            )
        )
    # The frontend's session secret is not a backend setting, but a shared .env file reaches both.
    nextauth = env.get("NEXTAUTH_SECRET")
    if nextauth is not None and _looks_like_placeholder(nextauth):
        out.append(_fatal("nextauth_placeholder", "NEXTAUTH_SECRET is empty or the template value from .env.example."))
    if not settings.use_sqlite and not settings.database_url_override:
        if _looks_like_placeholder(settings.postgres_password):
            out.append(_fatal("db_password_default", "POSTGRES_PASSWORD is empty or the default `changeme`."))
    if settings.database_url_override and ":changeme@" in settings.database_url_override:
        out.append(_fatal("db_password_default", "DATABASE_URL_OVERRIDE carries the default password `changeme`."))
    return out


def _exposure_findings(settings: Settings, env: Mapping[str, str]) -> list[Finding]:
    out: list[Finding] = []
    # Fatal only where the operator said "this is production" (APP_ENV). Postgres alone is not enough: the
    # demo compose stack and a developer's docker-compose run Postgres with the demo seed and localhost links.
    declared = app_env(env) in _PRODUCTION_ENVS
    explicit = _fatal if declared else _warn
    if settings.demo_mode:
        out.append(explicit("demo_mode", "DEMO_MODE=true: the demo seed and guest sessions must not run where real companies sign in."))
    origins = [o for o in settings.cors_origins if o]
    if "*" in origins:
        out.append(_fatal("cors_wildcard", "BACKEND_CORS_ORIGINS contains `*` while credentials are allowed."))
    elif not origins:
        out.append(_warn("cors_empty", "BACKEND_CORS_ORIGINS is empty: no browser origin may call the API."))
    elif any(_is_localhost(o) for o in origins):
        out.append(_warn("cors_localhost", "BACKEND_CORS_ORIGINS still names a localhost origin; list only the public app origin."))
    elif any(o.startswith("http://") for o in origins):
        out.append(_warn("cors_http", "BACKEND_CORS_ORIGINS has a plain http:// origin; the app must be served over TLS."))
    if not settings.erasure_pseudonym_secret.strip():
        out.append(explicit(
            "no_pseudonym_secret",
            "ERASURE_PSEUDONYM_SECRET is unset: erased members' pseudonyms would be derived from BACKEND_SECRET_KEY, which the "
            "rotate-secret runbook rotates, so the same person would get a different handle afterwards. Set it once "
            "to its own random value (docs/ops/runbooks/rotate-secret.md) and never rotate it."))
    for name, value in (("FRONTEND_URL", settings.frontend_url), ("BRAND_APP_URL", settings.brand_app_url)):
        if _is_localhost(value):
            out.append(explicit("links_localhost", f"{name} points at localhost: every e-mailed link (verification, reset, invite) would be dead."))
    if _is_localhost(settings.backend_url):
        out.append(_warn("backend_url_localhost", "BACKEND_URL points at localhost: OAuth callbacks (Paraşüt) are built from it."))
    token = settings.whatsapp_verify_token
    if token == _PUBLIC_WHATSAPP_VERIFY_TOKEN and (settings.whatsapp_app_secret or settings.whatsapp_phone_number_id):
        out.append(_fatal("whatsapp_verify_token", "WHATSAPP_VERIFY_TOKEN is the public default; choose your own."))
    if env.get("LOG_LEVEL", "").strip().upper() == "DEBUG":
        out.append(_warn("log_debug", "LOG_LEVEL=DEBUG: request detail reaches the logs; use INFO."))
    return out


def _mail_findings(settings: Settings, env: Mapping[str, str]) -> list[Finding]:
    declared = app_env(env) in _PRODUCTION_ENVS
    no_sender = settings.outbox_transport == "noop" or not (settings.smtp_user and settings.smtp_password)
    needs = [
        name
        for name, on in (
            ("REGISTRATION_MODE=invite_only (invitations and pilot invites are e-mailed)", settings.registration_mode == "invite_only"),
            ("EMAIL_VERIFICATION_REQUIRED=true (verification links are e-mailed)", settings.email_verification_required),
        )
        if on
    ]
    if not (no_sender and needs):
        return []
    explicit = _fatal if declared else _warn
    return [
        explicit(
            "mail_required_no_sender",
            "No mail can be sent (SMTP_USER / SMTP_PASSWORD unset, or OUTBOX_TRANSPORT=noop) but "
            + " and ".join(needs)
            + ": nobody could ever get in. Configure SMTP (docs/ops/mail.md), or for a deployment without mail "
            "set REGISTRATION_MODE=open and EMAIL_VERIFICATION_REQUIRED=false knowingly.",
        )
    ]


def _env_findings(settings: Settings, env: Mapping[str, str]) -> list[Finding]:
    if settings.use_sqlite:
        return []
    declared = app_env(env)
    allowed = ", ".join(ALLOWED_APP_ENVS)
    if not declared:
        return [_fatal("app_env_missing", f"APP_ENV is not set while the database is Postgres: set it to one of {allowed}.")]
    if declared not in ALLOWED_APP_ENVS:
        return [_fatal("app_env_unknown", f"APP_ENV={declared!r} is not a known value; use one of {allowed}.")]
    return []


def _degraded_findings(settings: Settings, env: Mapping[str, str]) -> list[Finding]:
    out: list[Finding] = []
    if settings.outbox_transport == "noop":
        out.append(_warn("outbox_noop", "OUTBOX_TRANSPORT=noop: mail is recorded, never sent (verification, reset, invite, briefing)."))
    elif not (settings.smtp_user and settings.smtp_password):
        out.append(_warn("no_mail_sender", "No mail sender (SMTP_USER / SMTP_PASSWORD): invitations, resets and briefings end as failed outbox rows."))
    key = settings.openai_api_key
    if not key or key.startswith("llm-placeholder"):
        out.append(_warn("no_llm_key", "OPENAI_API_KEY is a placeholder: chat and narrative text answer 503; the numbers are unaffected."))
    if not env.get("SENTRY_DSN"):
        out.append(_warn("no_error_tracking", "SENTRY_DSN is not set: unhandled errors are only in the container log."))
    if not settings.trusted_proxy_count and not settings.trusted_proxy_cidrs.strip():
        out.append(_warn("no_trusted_proxy", "Neither TRUSTED_PROXY_COUNT nor TRUSTED_PROXY_CIDRS is set: behind a reverse proxy every client shares one rate-limit bucket."))
    if not settings.field_encryption_key.strip():
        out.append(_warn("no_field_key", "FIELD_ENCRYPTION_KEY is unset: connector secrets are encrypted with a key derived from BACKEND_SECRET_KEY, so rotating that secret would lose them."))
    if not settings.platform_operator_emails.strip():
        out.append(_warn("no_operator", "PLATFORM_OPERATOR_EMAILS is empty: nobody can mint pilot invites or clear an IP allow-list lock-out."))
    if not settings.support_contact.strip():
        out.append(_warn("no_support_contact", "SUPPORT_CONTACT is unset: a locked-out user is told to ask their platform administrator, with no address."))
    return out


def check_settings(settings: Settings, environ: Mapping[str, str] | None = None) -> list[Finding]:
    """Every finding for these settings. Pure: logs nothing, raises nothing."""
    env = os.environ if environ is None else environ
    findings = [
        *_secret_findings(settings, env),
        *_env_findings(settings, env),
        *_exposure_findings(settings, env),
        *_mail_findings(settings, env),
        *_degraded_findings(settings, env),
    ]
    if settings.use_sqlite and app_env(env) in _PRODUCTION_ENVS:
        findings.append(_fatal("sqlite_in_production", f"APP_ENV={app_env(env)} with USE_SQLITE=true: a development database must not hold company data."))
    return findings


def enforce(settings: Settings, environ: Mapping[str, str] | None = None) -> list[Finding]:
    """Log every finding; raise `PreflightError` for fatal ones in production.

    Outside production a fatal finding is logged as a warning (and returned) so development is not
    blocked. Returns the findings so a caller can show them."""
    findings = check_settings(settings, environ)
    production = is_production(settings, environ)
    fatal = [f for f in findings if f.severity == FATAL]
    for finding in findings:
        level = logging.CRITICAL if finding.severity == FATAL and production else logging.WARNING
        logger.log(level, "preflight %s [%s]: %s", finding.severity, finding.code, finding.message)
    if fatal and production:
        raise PreflightError(
            "Production preflight failed:\n" + "\n".join(f"  - [{f.code}] {f.message}" for f in fatal)
        )
    return findings


_enforced = False


def enforce_or_exit(settings: Settings, *, process: str) -> list[Finding]:
    """`enforce`, and stop the process (exit 1) on a fatal finding. Used by every process type: the API
    at import of `main.py`, the ARQ worker at import of `worker.py`. Runs once per process."""
    global _enforced
    if _enforced:
        return []
    try:
        findings = enforce(settings)
    except PreflightError as err:
        logger.critical("%s process: STARTUP ABORTED — %s", process, err)
        raise SystemExit(1) from err
    _enforced = True
    return findings


# ── Database schema ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SchemaState:
    """`status`: ok | behind | ahead | unknown | skipped. `at_head` is True only for ok."""

    status: str
    current: str | None
    heads: tuple[str, ...]

    @property
    def at_head(self) -> bool:
        return self.status == "ok"


def _backend_dir() -> Path:
    # app/core/preflight.py -> app -> backend (/app in the image, where alembic/ sits beside app/).
    return Path(__file__).resolve().parents[2]


def _script_directory() -> Any:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(_backend_dir() / "alembic"))
    return ScriptDirectory.from_config(config)


def code_heads() -> tuple[str, ...]:
    """The head revision(s) of the migrations shipped with this code."""
    return tuple(sorted(_script_directory().get_heads()))


async def database_revision(conn: Any) -> str | None:
    """The revision recorded in `alembic_version`, or None when the table is missing or empty.

    `conn` is an `AsyncConnection` (a session's own via `await session.connection()`, or one opened on
    an engine). The table is looked up first, so a missing one never fails a statement inside the
    caller's transaction."""
    from sqlalchemy import inspect, text

    if not await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("alembic_version")):
        return None
    row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).first()
    return None if row is None else str(row[0])


async def schema_state(conn: Any) -> SchemaState:
    """Compare the database with the code. SQLite (development) builds its schema itself: skipped."""
    if conn.dialect.name == "sqlite":
        return SchemaState("skipped", None, ())
    script = _script_directory()
    heads = tuple(sorted(script.get_heads()))
    current = await database_revision(conn)
    if current is None:
        return SchemaState("behind", None, heads)
    if len(heads) != 1:
        return SchemaState("unknown", current, heads)  # a branched chain: `alembic merge` first
    if current == heads[0]:
        return SchemaState("ok", current, heads)
    try:
        script.get_revision(current)
    except Exception:  # a revision this code has never heard of: the database is newer than the code
        return SchemaState("ahead", current, heads)
    return SchemaState("behind", current, heads)


# ── Command line ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """`python -m app.core.preflight [--db]`: print findings; exit 1 on a fatal one or a stale schema."""
    import asyncio

    from app.config import get_settings

    args = sys.argv[1:] if argv is None else argv
    settings = get_settings()
    findings = check_settings(settings)
    production = is_production(settings)
    for finding in findings:
        print(f"{finding.severity.upper():5} [{finding.code}] {finding.message}")
    failed = production and any(f.severity == FATAL for f in findings)
    if "--db" in args:
        from app.database import engine

        async def _state() -> SchemaState:
            async with engine().connect() as conn:
                return await schema_state(conn)

        state = asyncio.run(_state())
        print(f"SCHEMA {state.status}: database={state.current} code={','.join(state.heads) or '-'}")
        failed = failed or state.status in ("behind", "ahead", "unknown")
    print("PREFLIGHT " + ("FAILED" if failed else "ok") + (" (production)" if production else " (not production)"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
