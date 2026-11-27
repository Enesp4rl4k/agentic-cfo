"""`.env.example` and `docs/ops/configuration.md` describe exactly the variables the code reads.

Before this test `.env.example` named 25 variables no code reads (`PILOT_REQUIRE_INVITE` implied a
protection that did not exist) and omitted 70 that the settings class does. A new setting needs a row in
the configuration reference; a row for a setting that is gone has to go.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "backend" / "app"
DOC = (REPO / "docs" / "ops" / "configuration.md").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO / ".env.example").read_text(encoding="utf-8")

SETTINGS = {name.upper() for name in Settings.model_fields}

# Read with os.environ / os.getenv / the preflight's environment mapping (section 2 of the reference).
PROCESS_ENV = {
    "APP_ENV", "LOG_LEVEL", "LOG_FORMAT", "SENTRY_DSN", "SENTRY_ENVIRONMENT", "SENTRY_TRACES_SAMPLE_RATE",
    "GIT_SHA", "IMAGE_TAG", "BUILD_TIME", "NEXTAUTH_SECRET", "USE_SQLITE", "REDIS_URL", "DISABLE_REDIS",
    "AGENT_BUS_REDIS", "LANGGRAPH_CHECKPOINT", "OTEL_ENABLED", "OTEL_ENDPOINT", "OTEL_EXPORTER",
    "JAEGER_HOST", "JAEGER_PORT", "LANGSMITH_ENABLED", "LANGSMITH_API_KEY", "LANGSMITH_ENDPOINT",
    "LANGSMITH_PROJECT", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_ENDPOINT",
    "LANGCHAIN_PROJECT", "CSUITE_URL", "CSUITE_API_KEY",
    "APP_CLOCK_START",  # app/core/clock.py reads it through the CLOCK_ENV constant (test-only; refused in production)
}


def test_the_test_clock_override_is_the_variable_the_clock_reads() -> None:
    from app.core.clock import CLOCK_ENV

    assert CLOCK_ENV == "APP_CLOCK_START" and CLOCK_ENV in PROCESS_ENV
# Not read by the backend: the frontend, docker compose, the staging stack (section 3).
OUTSIDE_THE_BACKEND = {
    "NEXTAUTH_URL", "NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_DEMO_MODE", "NEXT_PUBLIC_LEGACY_DASHBOARDS",
    "NEXT_PUBLIC_BRAND_NAME", "NEXT_PUBLIC_BRAND_DOMAIN", "NEXT_PUBLIC_BRAND_APP_URL",
    "NEXT_PUBLIC_BRAND_CONTACT_EMAIL", "NEXT_PUBLIC_BRAND_TWITTER_URL", "NEXT_PUBLIC_BRAND_LINKEDIN_URL",
    "BACKEND_INTERNAL_URL", "BACKEND_PORT", "FRONTEND_PORT", "BACKEND_IMAGE", "FRONTEND_IMAGE",
    "GITHUB_REPOSITORY", "APP_DOMAIN", "API_DOMAIN", "ACME_EMAIL", "AGE_RECIPIENT",
    "BACKUP_RCLONE_REMOTE", "BACKUP_RETENTION_DAYS", "BACKUP_LOCAL_DIR", "BACKUP_KEEP_LOCAL",
}


def keys(text: str) -> set[str]:
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))


def settings_section() -> str:
    return DOC.split("<!-- settings-table-start -->")[1].split("<!-- settings-table-end -->")[0]


def test_every_setting_has_a_row_and_every_row_is_a_setting() -> None:
    rows = set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)` \|", settings_section(), re.M))
    assert SETTINGS - rows == set(), f"settings without a row in docs/ops/configuration.md: {sorted(SETTINGS - rows)}"
    assert rows - SETTINGS == set(), f"rows without a setting: {sorted(rows - SETTINGS)}"


def test_env_example_names_only_variables_something_reads() -> None:
    unknown = keys(ENV_EXAMPLE) - SETTINGS - PROCESS_ENV - OUTSIDE_THE_BACKEND
    assert unknown == set(), f".env.example documents variables nothing reads: {sorted(unknown)}"


def test_env_example_names_every_setting() -> None:
    assert SETTINGS - keys(ENV_EXAMPLE) == set()


def test_every_environment_read_in_the_app_is_documented() -> None:
    reads: set[str] = set()
    pattern = re.compile(r"""os\.(?:environ\.get|getenv|environ\[)\(?\s*["']([A-Z][A-Z0-9_]+)""")
    for path in APP.rglob("*.py"):
        reads |= set(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
    assert reads - PROCESS_ENV - SETTINGS == set(), (
        f"environment variables read but missing from PROCESS_ENV (and section 2 of the reference): "
        f"{sorted(reads - PROCESS_ENV - SETTINGS)}"
    )


def test_the_process_environment_variables_are_in_the_reference() -> None:
    section = DOC.split("## 2. Process environment only")[1].split("## 3.")[0]
    missing = {name for name in PROCESS_ENV if f"`{name}`" not in section}
    assert missing == set(), f"missing from section 2 of docs/ops/configuration.md: {sorted(missing)}"


def test_the_template_secrets_are_the_ones_the_preflight_refuses() -> None:
    from app.core.preflight import _looks_like_placeholder

    values = dict(re.findall(r"^(BACKEND_SECRET_KEY|NEXTAUTH_SECRET)=(.*)$", ENV_EXAMPLE, re.M))
    assert values and all(_looks_like_placeholder(v) for v in values.values())
