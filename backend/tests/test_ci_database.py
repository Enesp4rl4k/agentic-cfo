"""CI ne çalıştırdığını söylemeli; göçler gerçek Postgres'te koşmalı.

Three things were true of CI before this, and none was visible:

- Every job set `DATABASE_URL`, which Settings does not read (`extra="ignore"`,
  no such field). The suite ran on SQLite while the workflow read as a
  Postgres run; the load-baseline job, with USE_SQLITE=false, connected to
  the postgres_* defaults instead of its service container.
- No job ran the migrations at all. The chain cannot be checked on SQLite —
  migration 005 alters constraints, which SQLite does not support — so a
  broken migration could only be found in production.
- Pushes to `master`, this repository's default branch, triggered nothing.

These tests hold the workflow to what it now claims.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci() -> dict:
    # A plain import, not importorskip: a guard that skips when its parser is
    # missing passes exactly where it is needed. PyYAML is pinned in
    # requirements.txt for this.
    import yaml

    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _env_blocks(ci: dict):
    for name, job in ci["jobs"].items():
        yield name, "job", job.get("env") or {}
        for step in job.get("steps", []):
            yield name, step.get("name", "?"), step.get("env") or {}


# ── Settings ─────────────────────────────────────────────────────────────────

def test_the_sync_url_follows_the_override() -> None:
    s = Settings(database_url_override="postgresql+asyncpg://u:p@db:5432/aicfo", use_sqlite=False)
    assert s.database_url == "postgresql+asyncpg://u:p@db:5432/aicfo"
    assert s.database_url_sync == "postgresql://u:p@db:5432/aicfo"


def test_a_sqlite_override_gives_a_sync_sqlite_url() -> None:
    s = Settings(database_url_override="sqlite+aiosqlite:///./x.db")
    assert s.database_url_sync == "sqlite:///./x.db"


def test_database_url_is_not_a_setting() -> None:
    """If this starts failing, Settings grew a DATABASE_URL field and the
    workflow guard below can be relaxed — not before."""
    assert "database_url" not in Settings.model_fields


# ── Workflow ─────────────────────────────────────────────────────────────────

def test_no_job_relies_on_the_ignored_variable(ci) -> None:
    offenders = [f"{job} / {step}" for job, step, env in _env_blocks(ci) if "DATABASE_URL" in env]
    assert not offenders, f"DATABASE_URL Settings tarafından okunmaz: {offenders}"


def test_the_default_branch_triggers_ci(ci) -> None:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = ci.get("on") or ci.get(True)
    assert "master" in triggers["push"]["branches"]
    assert "master" in triggers["pull_request"]["branches"]


def test_migrations_run_on_postgres(ci) -> None:
    job = ci["jobs"]["migrations-postgres"]
    assert "postgres" in job["services"]
    script = "\n".join(step.get("run", "") for step in job["steps"])
    for command in ("alembic upgrade head", "schema_drift.py", "alembic downgrade base"):
        assert command in script, command
    envs = [step.get("env") or {} for step in job["steps"]] + [job.get("env") or {}]
    merged = {k: v for env in envs for k, v in env.items()}
    assert str(merged.get("USE_SQLITE")).lower() == "false"
    assert str(merged.get("DATABASE_URL_OVERRIDE", "")).startswith("postgresql+asyncpg://")


# ── The workflow is one GitHub will run ─────────────────────────────────────
# Every run of ci.yml failed in 0 seconds with no jobs, from at least
# 2026-08-20: the workflow `env` context was read in a job name and in job- and
# service-level env, where GitHub does not provide it, and GitHub rejects the
# whole file. Nothing locally parsed the expressions, so it looked fine.

def _exprs(value) -> list[str]:
    import re

    return re.findall(r"\$\{\{(.*?)\}\}", str(value))


def test_contexts_are_used_only_where_github_provides_them(ci) -> None:
    offenders = []
    for name, job in ci["jobs"].items():
        positions = [("name", job.get("name", ""), ("env.", "secrets.", "job.", "steps.", "runner.")),
                     ("if", job.get("if", ""), ("env.", "secrets.", "job.", "steps.", "runner.", "matrix.")),
                     ("env", job.get("env") or {}, ("env.", "job.", "steps.", "runner."))]
        for svc, spec in (job.get("services") or {}).items():
            positions.append((f"services.{svc}.env", spec.get("env") or {}, ("env.", "job.", "steps.", "runner.")))
        for where, value, forbidden in positions:
            for expr in _exprs(value):
                if any(f in expr for f in forbidden):
                    offenders.append(f"{name}.{where}: ${{{{{expr}}}}}")
    assert not offenders, offenders


def test_ci_needs_no_repository_secret_to_run(ci) -> None:
    """Throwaway values are generated per run; a missing secret stopped every job at step one."""
    import re

    used = set(re.findall(r"secrets\.([A-Z_]+)", WORKFLOW.read_text(encoding="utf-8")))
    assert used <= {"GITHUB_TOKEN"}, used


def test_the_workflow_holds_no_password_literal() -> None:
    import re

    # The CI database runs with trust auth. A literal password — even one for
    # a throwaway container — was reported as a leaked credential by every
    # scanner that read the file, and failed the PR's security gate.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" not in text
    assert not re.search(r"postgresql\+\w+://[^@\s/]+:[^@\s/]+@", text)
