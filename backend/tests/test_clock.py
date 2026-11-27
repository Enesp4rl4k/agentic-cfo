"""The one clock (app/core/clock.py): pinned for every test, movable for the browser journey, refused in production."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.core import clock
from app.core.preflight import FATAL, WARN, PreflightError, check_settings, enforce
from tests.test_preflight import CLEAN_ENV, NO_MAIL_NEEDED, codes, production_settings

BACKEND = Path(__file__).resolve().parents[1]
INSTANT = "2026-11-25T10:00:00Z"
SESSION_INSTANT = clock.parse_instant(os.environ["TEST_CLOCK_INSTANT"]) if os.environ.get("TEST_CLOCK_INSTANT") else clock.TEST_INSTANT


class TestTheSessionClock:
    def test_every_test_starts_at_the_documented_instant(self) -> None:
        now = datetime.now(UTC)
        assert SESSION_INSTANT <= now < SESSION_INSTANT + timedelta(seconds=30)
        assert clock.today() == SESSION_INSTANT.date()
        assert datetime.utcnow().replace(tzinfo=UTC) - now < timedelta(seconds=5)

    def test_the_documented_instant_is_away_from_every_boundary(self) -> None:
        i = clock.TEST_INSTANT
        assert i.weekday() == 2 and i.hour == 10 and 3 <= i.day <= 25  # Wednesday 10:00 UTC (13:00 Turkey)
        assert i.astimezone(clock._dt.timezone(timedelta(hours=3))).date() == i.date()

    def test_the_stdlib_types_still_are_the_stdlib_types(self) -> None:
        real = clock.real_datetime(2026, 1, 2, tzinfo=UTC)
        assert isinstance(real, datetime) and isinstance(real, date) and isinstance(datetime.now(UTC), clock.real_datetime)
        assert isinstance(clock.real_date(2026, 1, 2), date) and not isinstance(clock.real_date(2026, 1, 2), datetime)
        assert datetime.fromisoformat("2026-11-25T10:00:00+00:00") == clock.TEST_INSTANT
        assert datetime.now(UTC) - SESSION_INSTANT < timedelta(seconds=30)  # arithmetic across the two kinds works

    @pytest.mark.real_clock(reason="proves the opt-out reaches the wall clock")
    def test_a_test_can_opt_into_the_wall_clock(self) -> None:
        assert not clock.is_pinned()
        assert abs(datetime.now(UTC) - clock.wall_now()) < timedelta(seconds=5)

    def test_pinning_moves_the_products_today(self) -> None:
        from app.services.runway import opening_cash_for

        with clock.pinned(datetime(2028, 2, 29, 23, 59, 30, tzinfo=UTC), tick=False):
            got = opening_cash_for({"opening_cash": {"date": "2028-02-27", "balance_cents": 5}})
        assert got is not None and got["age_days"] == 2
        assert clock.today() == SESSION_INSTANT.date()  # restored

    def test_a_token_is_stamped_by_the_wall_clock_and_stays_valid(self) -> None:
        from app.services.auth import create_access_token, decode_token

        with clock.pinned(datetime(2020, 1, 1, tzinfo=UTC)):
            payload = decode_token(create_access_token("u1", "a@example.com", "owner"))
        assert abs(payload["iat"] - clock.wall_now().timestamp()) < 60


class TestTheOverride:
    @pytest.mark.parametrize("env", ["test", "ci", " Test "])
    def test_it_is_honoured_in_a_test_environment(self, env: str) -> None:
        got = clock.override_from_env({"APP_ENV": env, "APP_CLOCK_START": INSTANT})
        assert got == datetime(2026, 11, 25, 10, tzinfo=UTC)

    @pytest.mark.parametrize("env", ["production", "prod", "staging", "demo", "development", ""])
    def test_it_is_ignored_anywhere_else(self, env: str) -> None:
        assert clock.override_from_env({"APP_ENV": env, "APP_CLOCK_START": INSTANT}) is None

    def test_a_malformed_instant_is_an_error_not_the_real_clock(self) -> None:
        with pytest.raises(ValueError):
            clock.override_from_env({"APP_ENV": "test", "APP_CLOCK_START": "next tuesday"})

    def test_preflight_refuses_it_in_production(self) -> None:
        settings = production_settings(**NO_MAIL_NEEDED)
        for env in ("production", "staging", "ci"):  # Postgres with APP_ENV=ci is production too
            found = check_settings(settings, {**CLEAN_ENV, "APP_ENV": env, "APP_CLOCK_START": INSTANT})
            assert "clock_override_in_production" in codes(found, FATAL), env
        with pytest.raises(PreflightError, match="clock_override_in_production"):
            enforce(settings, {**CLEAN_ENV, "APP_CLOCK_START": INSTANT})
        assert "clock_override_in_production" not in codes(check_settings(settings, CLEAN_ENV))

    def test_preflight_says_when_it_is_ignored_and_is_silent_in_a_test_environment(self) -> None:
        sqlite = production_settings(use_sqlite=True, **NO_MAIL_NEEDED)
        assert "clock_override_ignored" in codes(check_settings(sqlite, {"APP_ENV": "demo", "APP_CLOCK_START": INSTANT}), WARN)
        quiet = codes(check_settings(sqlite, {"APP_ENV": "test", "APP_CLOCK_START": INSTANT}))
        assert not {"clock_override_in_production", "clock_override_ignored"} & quiet

    @pytest.mark.parametrize(("env", "expect"), [("test", "2026-11-25"), ("development", None)])
    def test_the_api_process_runs_on_the_simulated_date_only_in_a_test_environment(self, env: str, expect: str | None) -> None:
        code = (
            "import json; from datetime import UTC, date, datetime; import app.services.runway as r; "
            "print(json.dumps([r.datetime.now(UTC).date().isoformat(), date.today().isoformat()]))"
        )
        child = {k: v for k, v in os.environ.items() if k not in ("APP_CLOCK_START", "APP_ENV", "TEST_CLOCK_INSTANT")}
        child.update(APP_ENV=env, APP_CLOCK_START=INSTANT, PYTHONPATH=str(BACKEND))
        out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=child, capture_output=True, text=True, timeout=120)
        product_today = json.loads(out.stdout.strip().splitlines()[-1])[0]
        if expect:
            assert product_today == expect
        else:
            assert product_today == clock.wall_now().date().isoformat()


class TestProductionIsInert:
    """Where the override is not honoured nothing is installed: no import hook, the stdlib `datetime`, the real now()."""

    PROBE = (
        "import builtins, json, sys\n"
        "before = builtins.__import__\n"
        "import app, app.services.runway as r\n"
        "import datetime as stdlib\n"
        "from app.core import clock\n"
        "wall = stdlib.datetime.now(stdlib.UTC)\n"
        "mine = r.datetime.now(stdlib.UTC)\n"
        "print(json.dumps({\n"
        "  'import_untouched': builtins.__import__ is before,\n"
        "  'import_is_builtin': type(builtins.__import__).__name__ == 'builtin_function_or_method',\n"
        "  'datetime_module_real': sys.modules['datetime'] is stdlib and not hasattr(stdlib.datetime, '_real'),\n"
        "  'product_class_real': r.datetime is stdlib.datetime and r.datetime.__module__ == 'datetime',\n"
        "  'pinned': clock.is_pinned(),\n"
        "  'now_is_real': abs((mine - wall).total_seconds()) < 60,\n"
        "  'year': mine.year,\n"
        "}))\n"
    )

    def _run(self, **env: str) -> dict:
        child = {k: v for k, v in os.environ.items() if k not in ("APP_CLOCK_START", "APP_ENV", "TEST_CLOCK_INSTANT")}
        child.update(env, PYTHONPATH=str(BACKEND))
        out = subprocess.run([sys.executable, "-c", self.PROBE], cwd=BACKEND, env=child, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-2000:]
        return json.loads(out.stdout.strip().splitlines()[-1])

    @pytest.mark.parametrize("env", [None, "production", "Production", "prod", "staging", "demo", "development", "tset", "testing", ""])
    def test_a_clock_start_outside_a_test_environment_changes_nothing(self, env: str | None) -> None:
        got = self._run(APP_CLOCK_START="2001-01-01T00:00:00Z", **({} if env is None else {"APP_ENV": env}))
        assert got == {
            "import_untouched": True, "import_is_builtin": True, "datetime_module_real": True,
            "product_class_real": True, "pinned": False, "now_is_real": True, "year": got["year"],
        }
        assert got["year"] >= 2026

    def test_without_a_clock_start_a_test_environment_installs_nothing_either(self) -> None:
        got = self._run(APP_ENV="test")
        assert got["import_untouched"] and got["product_class_real"] and not got["pinned"] and got["now_is_real"]

    def test_the_control_proves_the_probe_can_see_an_installed_clock(self) -> None:
        got = self._run(APP_ENV="test", APP_CLOCK_START="2001-01-01T00:00:00Z")
        assert not got["import_untouched"] and not got["product_class_real"] and got["pinned"] and got["year"] == 2001
