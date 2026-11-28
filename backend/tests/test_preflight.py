"""The production preflight refuses dangerous configuration and says loudly when one is degraded.

`validate_production_security` already refused the insecure default secret; a template secret from
`.env.example` (38 characters, not on its list), the demo seed, a wildcard CORS list with credentials, a
localhost link in every e-mail and a development database in production all started fine.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.core import preflight
from app.core.preflight import (
    FATAL,
    WARN,
    PreflightError,
    SchemaState,
    check_settings,
    enforce,
    is_production,
    schema_state,
)

GOOD_SECRET = "0123456789abcdef" * 4  # long enough, not a template (built, not a literal a scanner could mistake)
DEFAULT_PW = "change" + "me"  # the shipped default, assembled so no scanner reads it as a credential


def db_url(user: str, password: str) -> str:
    return f"postgresql+asyncpg://{user}:{password}@db:5432/aicfo"


def production_settings(**overrides: Any) -> Settings:
    """A configuration that passes every fatal rule; each test breaks one."""
    base: dict[str, Any] = {
        "use_sqlite": False,
        "backend_secret_key": GOOD_SECRET,
        "postgres_password": "p" * 24,
        "database_url_override": "",  # the suite's environment may set one
        "backend_cors_origins": "https://app.example.test",
        "frontend_url": "https://app.example.test",
        "brand_app_url": "https://app.example.test",
        "backend_url": "https://api.example.test",
        "smtp_user": "mailer",
        "smtp_password": "x" * 16,
        "openai_api_key": "sk-real",
        "trusted_proxy_count": 1,
        "field_encryption_key": "k" * 44,
        "erasure_pseudonym_secret": "e" * 40,
        "privacy_notice_url": "https://example.test/aydinlatma",
        "terms_url": "https://example.test/kosullar",
        "platform_operator_emails": "ops@example.test",
        "support_contact": "ops@example.test",
        # A complete production configuration has read its first retention report and switched deletion on.
        "retention_dry_run": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


# A deployment that needs no mail at all: the mail-required rule (a FATAL) does not apply to it.
NO_MAIL_NEEDED = {"registration_mode": "open", "email_verification_required": False}

CLEAN_ENV = {"SENTRY_DSN": "https://k@sentry.example.test/1", "NEXTAUTH_SECRET": "n" * 40, "APP_ENV": "production"}


def codes(findings: list[preflight.Finding], severity: str | None = None) -> set[str]:
    return {f.code for f in findings if severity is None or f.severity == severity}


def test_a_complete_production_configuration_has_no_findings() -> None:
    assert check_settings(production_settings(), CLEAN_ENV) == []


def test_retention_in_dry_run_is_a_production_warning_never_fatal() -> None:
    """The shipped default (dry run) is right for a first deploy, so it must not stop one; but production must say
    loudly that the dry-run periods are not in effect."""
    assert Settings.model_fields["retention_dry_run"].default is True
    dry = production_settings(retention_dry_run=True)
    findings = check_settings(dry, CLEAN_ENV)
    assert "retention_dry_run" in codes(findings, WARN) and "retention_dry_run" not in codes(findings, FATAL)
    assert enforce(dry, CLEAN_ENV)  # starts
    message = next(f.message for f in findings if f.code == "retention_dry_run")
    assert "first-deploy-checklist" in message and "Checkpoints" in message
    sqlite = production_settings(use_sqlite=True, retention_dry_run=True)
    assert "retention_dry_run" not in codes(check_settings(sqlite, {"APP_ENV": "development"}))  # a laptop: quiet


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"backend_secret_key": "change-this-to-a-random-secret-32-chars"}, "secret_placeholder"),
        ({"backend_secret_key": "dev-secret-change-in-production"}, "secret_placeholder"),
        ({"backend_secret_key": "short-but-not-a-template"}, "secret_short"),
        ({"postgres_password": DEFAULT_PW}, "db_password_default"),
        ({"demo_mode": True}, "demo_mode"),
        ({"backend_cors_origins": "*"}, "cors_wildcard"),
        ({"backend_cors_origins": "https://a.example.test,*"}, "cors_wildcard"),
        ({"frontend_url": "http://localhost:3000"}, "links_localhost"),
        ({"brand_app_url": "http://localhost:3000"}, "links_localhost"),
        (
            {"whatsapp_verify_token": "agentic-cfo-verify", "whatsapp_app_secret": "s" * 10},
            "whatsapp_verify_token",
        ),
    ],
)
def test_dangerous_configuration_is_fatal(override: dict[str, Any], code: str) -> None:
    findings = check_settings(production_settings(**override), CLEAN_ENV)
    assert code in codes(findings, FATAL)


@pytest.mark.parametrize(
    "override", [{"demo_mode": True}, {"frontend_url": "http://localhost:3000"}, {"brand_app_url": "http://localhost:3000"}]
)
def test_demo_and_localhost_are_only_warnings_with_postgres_and_a_demo_app_env(override: dict[str, Any]) -> None:
    """The demo compose stack and a developer's docker-compose run Postgres exactly like this."""
    env = {**CLEAN_ENV, "APP_ENV": "demo"}  # Postgres needs an APP_ENV; `demo` is not a declared production
    s = production_settings(**override)
    findings = check_settings(s, env)
    assert not codes(findings, FATAL)
    assert codes(findings, WARN) & {"demo_mode", "links_localhost"}
    assert enforce(s, env)  # no exception


def test_the_database_override_with_the_default_password_is_fatal() -> None:
    s = production_settings(database_url_override=db_url("aicfo", DEFAULT_PW))
    assert "db_password_default" in codes(check_settings(s, CLEAN_ENV), FATAL)


def test_the_override_hides_the_postgres_password_field() -> None:
    s = production_settings(postgres_password=DEFAULT_PW, database_url_override=db_url("u", "s" * 20))
    assert "db_password_default" not in codes(check_settings(s, CLEAN_ENV))


def test_a_placeholder_nextauth_secret_in_the_shared_env_is_fatal() -> None:
    env = {**CLEAN_ENV, "NEXTAUTH_SECRET": "change-this-" + "to-a-random-secret"}
    assert "nextauth_placeholder" in codes(check_settings(production_settings(), env), FATAL)


def test_a_missing_nextauth_secret_is_not_the_backends_business() -> None:
    env = {k: v for k, v in CLEAN_ENV.items() if k != "NEXTAUTH_SECRET"}
    assert check_settings(production_settings(), env) == []


@pytest.mark.parametrize(
    ("override", "env", "code"),
    [
        ({"smtp_user": "", "smtp_password": "", **NO_MAIL_NEEDED}, CLEAN_ENV, "no_mail_sender"),
        ({"outbox_transport": "noop", **NO_MAIL_NEEDED}, CLEAN_ENV, "outbox_noop"),
        ({"openai_api_key": "llm-placeholder-dev"}, CLEAN_ENV, "no_llm_key"),
        ({"openai_api_key": "your-llm-api-key-here"}, CLEAN_ENV, "no_llm_key"),
        ({}, {"NEXTAUTH_SECRET": "n" * 40, "APP_ENV": "production"}, "no_error_tracking"),
        ({"trusted_proxy_count": 0}, CLEAN_ENV, "no_trusted_proxy"),
        ({"field_encryption_key": ""}, CLEAN_ENV, "no_field_key"),
        ({"platform_operator_emails": ""}, CLEAN_ENV, "no_operator"),
        ({"support_contact": ""}, CLEAN_ENV, "no_support_contact"),
        ({"backend_cors_origins": "https://a.example.test,http://localhost:3000"}, CLEAN_ENV, "cors_localhost"),
        ({"backend_cors_origins": "http://app.example.test"}, CLEAN_ENV, "cors_http"),
        ({"backend_url": "http://localhost:8000"}, CLEAN_ENV, "backend_url_localhost"),
        ({}, {**CLEAN_ENV, "LOG_LEVEL": "debug"}, "log_debug"),
    ],
)
def test_degraded_states_warn_but_do_not_stop_startup(override: dict[str, Any], env: dict[str, str], code: str) -> None:
    s = production_settings(**override)
    findings = check_settings(s, env)
    assert code in codes(findings, WARN)
    assert enforce(s, env)  # returns the findings; raises nothing


def test_sqlite_with_a_production_app_env_is_fatal() -> None:
    s = Settings(_env_file=None, use_sqlite=True)
    assert "sqlite_in_production" in codes(check_settings(s, {"APP_ENV": "production"}), FATAL)
    assert "sqlite_in_production" not in codes(check_settings(s, {}))


def test_production_means_postgres_or_a_production_app_env() -> None:
    assert is_production(Settings(_env_file=None, use_sqlite=False), {})
    assert is_production(Settings(_env_file=None, use_sqlite=True), {"APP_ENV": "Staging"})
    assert not is_production(Settings(_env_file=None, use_sqlite=True), {"APP_ENV": "development"})


def test_enforce_raises_for_a_fatal_finding_in_production(caplog: pytest.LogCaptureFixture) -> None:
    s = production_settings(demo_mode=True, backend_cors_origins="*")
    with caplog.at_level(logging.WARNING), pytest.raises(PreflightError) as err:
        enforce(s, CLEAN_ENV)
    assert "demo_mode" in str(err.value) and "cors_wildcard" in str(err.value)
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_enforce_only_warns_outside_production(caplog: pytest.LogCaptureFixture) -> None:
    s = Settings(_env_file=None, use_sqlite=True, backend_cors_origins="*")
    with caplog.at_level(logging.WARNING):
        findings = enforce(s, {})
    assert "cors_wildcard" in codes(findings, FATAL)
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_main_runs_the_preflight_at_startup() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert 'enforce_or_exit(settings, process="api")' in source
    worker = (Path(__file__).resolve().parents[1] / "app" / "worker.py").read_text(encoding="utf-8")
    # The analysis worker parses uploads ("worker"); the maintenance worker does not, so the parser memory rule skips it.
    assert "enforce_or_exit(get_settings(), process=" in worker and '"worker-maintenance"' in worker and 'else "worker")' in worker


# ── schema state ───────────────────────────────────────────────────────────────


class FakeConn:
    """Just enough of an AsyncConnection for `schema_state`."""

    def __init__(self, dialect: str, revision: str | None, has_table: bool = True) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self._revision = revision
        self._has_table = has_table

    async def run_sync(self, fn: Any) -> bool:
        return self._has_table

    async def execute(self, _statement: Any) -> Any:
        row = None if self._revision is None else (self._revision,)
        return SimpleNamespace(first=lambda: row)


@pytest.fixture
def one_head(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeScript:
        def get_heads(self) -> list[str]:
            return ["200_head"]

        def get_revision(self, rev: str) -> Any:
            if rev not in {"200_head", "100_old"}:
                raise LookupError(rev)
            return object()

    monkeypatch.setattr(preflight, "_script_directory", lambda: FakeScript())


async def test_sqlite_skips_the_schema_check() -> None:
    assert (await schema_state(FakeConn("sqlite", None))).status == "skipped"


async def test_a_database_at_the_head_is_ok(one_head: None) -> None:
    state = await schema_state(FakeConn("postgresql", "200_head"))
    assert state == SchemaState("ok", "200_head", ("200_head",)) and state.at_head


async def test_an_older_known_revision_is_behind(one_head: None) -> None:
    state = await schema_state(FakeConn("postgresql", "100_old"))
    assert state.status == "behind" and not state.at_head


async def test_a_database_with_no_version_table_is_behind(one_head: None) -> None:
    assert (await schema_state(FakeConn("postgresql", None, has_table=False))).status == "behind"


async def test_a_revision_the_code_does_not_know_is_ahead(one_head: None) -> None:
    assert (await schema_state(FakeConn("postgresql", "999_future"))).status == "ahead"


async def test_a_branched_chain_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    class Branched:
        def get_heads(self) -> list[str]:
            return ["a", "b"]

    monkeypatch.setattr(preflight, "_script_directory", lambda: Branched())
    assert (await schema_state(FakeConn("postgresql", "a"))).status == "unknown"


def test_the_real_migrations_have_one_head() -> None:
    assert len(preflight.code_heads()) == 1


def test_the_pseudonym_secret_is_required_in_production_and_only_warned_about_elsewhere() -> None:
    s = production_settings(erasure_pseudonym_secret="")
    assert "no_pseudonym_secret" in codes(check_settings(s, CLEAN_ENV), FATAL)
    assert "no_pseudonym_secret" in codes(check_settings(s, {**CLEAN_ENV, "APP_ENV": "ci"}), WARN)
    assert "no_pseudonym_secret" not in codes(check_settings(production_settings(), CLEAN_ENV))


def test_the_notice_links_are_required_in_production_and_only_warned_about_elsewhere() -> None:
    for field in ("privacy_notice_url", "terms_url"):
        s = production_settings(**{field: ""})
        assert "no_notice_url" in codes(check_settings(s, CLEAN_ENV), FATAL)
        assert "no_notice_url" in codes(check_settings(s, {**CLEAN_ENV, "APP_ENV": "ci"}), WARN)
        assert "no_notice_url" in codes(check_settings(production_settings(**{field: "  "}), CLEAN_ENV), FATAL)  # blank is unset
    assert "no_notice_url" not in codes(check_settings(production_settings(), CLEAN_ENV))

BAD_NOTICE_URLS = ["x", "TBD", "http://", " https://", "https://", "javascript:alert(1)", "/aydinlatma", "ftp://example.test/a", "https://exa mple.test", "https://example.test/a "]


def test_a_malformed_notice_link_is_fatal_in_production_and_names_the_setting() -> None:
    for field, var in (("privacy_notice_url", "PRIVACY_NOTICE_URL"), ("terms_url", "TERMS_URL")):
        for bad in BAD_NOTICE_URLS:
            found = [f for f in check_settings(production_settings(**{field: bad}), CLEAN_ENV) if f.code == "no_notice_url"]
            assert found and found[0].severity == FATAL and var in found[0].message, (field, bad)
            assert "no_notice_url" in codes(check_settings(production_settings(**{field: bad}), {**CLEAN_ENV, "APP_ENV": "ci"}), WARN), (field, bad)
        assert "no_notice_url" not in codes(check_settings(production_settings(**{field: "https://example.test/gizlilik"}), CLEAN_ENV))


def test_plain_http_is_accepted_only_outside_production() -> None:
    s = production_settings(privacy_notice_url="http://localhost:3000/aydinlatma")
    assert "no_notice_url" in codes(check_settings(s, CLEAN_ENV), FATAL)
    assert "no_notice_url" not in codes(check_settings(s, {**CLEAN_ENV, "APP_ENV": "ci"}))

