"""`raw` with a provider that is not on this host is a production WARNING; `masked` and `off` are quiet."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.core.preflight import WARN, check_settings
from tests.test_preflight import production_settings


def codes(settings: Settings, env: dict[str, str]) -> set[str]:
    return {f.code for f in check_settings(settings, env) if f.severity == WARN}


ENV = {"APP_ENV": "production"}


def test_raw_with_the_default_foreign_provider_warns_in_production() -> None:
    assert "llm_raw_foreign" in codes(production_settings(llm_data_mode="raw"), ENV)
    assert "llm_raw_foreign" in codes(production_settings(llm_data_mode="raw", llm_base_url=""), ENV)  # the OpenAI default


@pytest.mark.parametrize("mode", ["masked", "off"])
def test_masked_and_off_do_not_warn(mode: str) -> None:
    assert "llm_raw_foreign" not in codes(production_settings(llm_data_mode=mode), ENV)


@pytest.mark.parametrize("base_url", ["http://localhost:11434/v1", "http://127.0.0.1:8000", "http://llm.internal/v1"])
def test_raw_against_a_local_provider_is_quiet(base_url: str) -> None:
    assert "llm_raw_foreign" not in codes(production_settings(llm_data_mode="raw", llm_base_url=base_url), ENV)


def test_raw_outside_production_is_not_a_finding() -> None:
    dev = Settings(_env_file=None, use_sqlite=True, llm_data_mode="raw")
    assert "llm_raw_foreign" not in codes(dev, {"APP_ENV": "development"})


def test_the_default_is_masked_and_raw_is_never_a_fallback() -> None:
    assert Settings(_env_file=None).llm_data_mode == "masked"
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_data_mode="whatever")   # a typo is refused, not read as raw
