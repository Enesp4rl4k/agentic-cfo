"""An analysis runs inside the API process only on a laptop.

`allow_inline_job_fallback` defaulted to True everywhere. With Postgres and a
worker (staging, production), a Redis blip made the API run the analysis
in-process: no retry, gone on restart, reported only in a log line. Now the
default follows the database, and switching it on with Postgres is refused at
startup like an insecure secret is.
"""
from __future__ import annotations

import pytest

from app.config import Settings

SECURE = "x" * 64


def test_on_by_default_with_sqlite() -> None:
    assert Settings(use_sqlite=True).allow_inline_job_fallback is True


def test_off_by_default_with_postgres() -> None:
    assert Settings(use_sqlite=False).allow_inline_job_fallback is False


def test_an_explicit_choice_is_kept() -> None:
    assert Settings(use_sqlite=True, allow_inline_job_fallback=False).allow_inline_job_fallback is False


def test_production_refuses_it_switched_on() -> None:
    settings = Settings(
        use_sqlite=False, backend_secret_key=SECURE, allow_inline_job_fallback=True,
    )
    with pytest.raises(ValueError, match="ALLOW_INLINE_JOB_FALLBACK"):
        settings.validate_production_security()


def test_production_starts_with_it_left_unset() -> None:
    Settings(use_sqlite=False, backend_secret_key=SECURE).validate_production_security()
