"""The one clock. Every "now" and "today" the product computes can be pinned here, and only here.

Four master-red incidents in one week were tests whose outcome depended on the day they ran (a Monday
07:00 UTC scheduler window, a radar week on the 26th-2nd, a balance that went stale, a month end). The
cure is not more care in each test: it is one seam a test session (and the browser journey's API) can
freeze, so a date-relative fixture means the same date on every run.

How it works. `install()` wraps `builtins.__import__`: every `app.*` / `tests.*` module imported afterwards that says
`from datetime import datetime, date` (or `import datetime`) gets subclasses whose `now()` / `utcnow()` /
`today()` read `now()` below; nothing in the 380-odd call sites changes. Third-party modules keep the
stdlib classes. While nothing is pinned the subclasses return the real time, so production behaviour is
unchanged. `isinstance(stdlib_value, datetime)` stays True (metaclass), pydantic and sqlite3 treat them as
the stdlib types, arithmetic and parsing are the stdlib's own. NOT pinned: `time.time()`, `time.monotonic()`,
database server defaults, and signed-token stamps (`wall_now`, below).

Who pins it:
- the pytest session (`tests/conftest.py`): every test starts at `TEST_INSTANT` (or the instant in
  `TEST_CLOCK_INSTANT`, which the boundary-matrix job sets) and the clock ticks from there in real
  time; a test that needs the real clock says so with `@pytest.mark.real_clock(reason=...)`;
- the browser journey's API: `APP_CLOCK_START` (an ISO-8601 instant), honoured ONLY when `APP_ENV` is
  `test` or `ci`, and refused by preflight (`clock_override_in_production`, FATAL) in production.

"Today" is the UTC calendar day of `now()`, as the radar, runway and briefing already use it (whether that
should be Europe/Istanbul is an open product question: see docs/ops/configuration.md, APP_CLOCK_START).
"""
from __future__ import annotations

import builtins
import datetime as _dt
import os
import time
import types
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

real_datetime = _dt.datetime
real_date = _dt.date

# The documented instant every test starts at: a Wednesday, mid-month, mid-day in UTC and in Turkey
# (13:00 TRT), five days from the month end, no Monday scheduler window, after every literal date the
# suite states (a balance of 2026-11-19 is six days old: current, under the 7-day staleness limit).
TEST_INSTANT = real_datetime(2026, 11, 25, 10, 0, 0, tzinfo=_dt.UTC)

CLOCK_ENV = "APP_CLOCK_START"
CLOCK_ENVS = frozenset({"test", "ci"})  # APP_ENV values under which APP_CLOCK_START is honoured

_pinned: real_datetime | None = None  # the instant the clock was pinned to (aware, UTC)
_pinned_at = 0.0  # time.monotonic() when it was pinned
_ticking = True


def now() -> real_datetime:
    """The current instant, aware UTC: pinned (and ticking from the pin) or the real one."""
    if _pinned is None:
        return real_datetime.now(_dt.UTC)
    if not _ticking:
        return _pinned
    return _pinned + _dt.timedelta(seconds=time.monotonic() - _pinned_at)


def today() -> real_date:
    """Today's UTC calendar date (the product's "today" for radar, runway and briefing)."""
    return now().date()


def wall_now() -> real_datetime:
    """The wall clock, never pinned. Only for what a party outside the product checks against ITS wall clock:
    a signed token's `exp` / `iat` (python-jose here, the Next.js server's refresh rule, the browser's cookie
    jar). Stamped by the pinned clock they would be born expired whenever the pin is in the past."""
    return real_datetime.now(_dt.UTC)


def is_pinned() -> bool:
    return _pinned is not None


def pin(instant: real_datetime, *, tick: bool = True) -> None:
    """Pin the clock to `instant` (naive = UTC). With `tick`, it advances from there in real time."""
    global _pinned, _pinned_at, _ticking
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.UTC)
    _pinned = real_datetime.fromtimestamp(instant.timestamp(), _dt.UTC)
    _pinned_at, _ticking = time.monotonic(), tick


def unpin() -> None:
    global _pinned
    _pinned = None


@contextmanager
def pinned(instant: real_datetime, *, tick: bool = True) -> Iterator[None]:
    """Pin for a block, then restore whatever was there before."""
    before = (_pinned, _pinned_at, _ticking)
    pin(instant, tick=tick)
    try:
        yield
    finally:
        _restore(before)


def _restore(state: tuple[real_datetime | None, float, bool]) -> None:
    global _pinned, _pinned_at, _ticking
    _pinned, _pinned_at, _ticking = state


def parse_instant(text: str) -> real_datetime:
    """An ISO-8601 instant (`2026-11-25T10:00:00Z`; naive = UTC). Raises ValueError otherwise."""
    value = real_datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return value if value.tzinfo is not None else value.replace(tzinfo=_dt.UTC)


def override_from_env(environ: Any = None) -> real_datetime | None:
    """The instant `APP_CLOCK_START` asks for, if this environment may honour it (APP_ENV test/ci)."""
    env = os.environ if environ is None else environ
    raw = (env.get(CLOCK_ENV) or "").strip()
    if not raw or env.get("APP_ENV", "").strip().lower() not in CLOCK_ENVS:
        return None
    return parse_instant(raw)


class _ClockMeta(type):
    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, cls._real)  # type: ignore[attr-defined]

    def __subclasscheck__(cls, sub: type) -> bool:
        return issubclass(sub, cls._real)  # type: ignore[attr-defined]


def _schema_of(real: type, _handler: Any) -> Any:
    """A model field annotated `datetime` / `date` after `install()` validates exactly as the stdlib type
    (the schema pydantic builds for the plain stdlib annotation)."""
    from pydantic_core import core_schema

    return core_schema.datetime_schema() if real is real_datetime else core_schema.date_schema()


class ClockDate(real_date, metaclass=_ClockMeta):
    _real = real_date

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: Any, handler: Any) -> Any:
        return _schema_of(real_date, handler)

    @classmethod
    def today(cls) -> ClockDate:
        if _pinned is None:
            d = real_date.today()
        else:
            d = now().astimezone().date()  # the stdlib's meaning: the machine's local calendar day
        return cls(d.year, d.month, d.day)


class ClockDatetime(real_datetime, metaclass=_ClockMeta):
    _real = real_datetime

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: Any, handler: Any) -> Any:
        return _schema_of(real_datetime, handler)

    @classmethod
    def now(cls, tz: _dt.tzinfo | None = None) -> ClockDatetime:
        if _pinned is None:
            v = real_datetime.now(tz)
        else:
            v = now().astimezone(tz) if tz is not None else now().astimezone().replace(tzinfo=None)
        return cls._of(v)

    @classmethod
    def utcnow(cls) -> ClockDatetime:
        return cls._of(now().replace(tzinfo=None))

    @classmethod
    def today(cls) -> ClockDatetime:
        return cls.now()

    @classmethod
    def _of(cls, v: real_datetime) -> ClockDatetime:
        return cls(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, v.tzinfo, fold=v.fold)


# The modules that read this clock: the product and its tests. Third-party code keeps the stdlib classes
# (some subclass `date` with their own metaclass, and a library's notion of time is not ours to move).
SCOPES = frozenset({"app", "tests"})
_proxy = types.ModuleType("datetime", _dt.__doc__)
_proxy.__dict__.update({k: v for k, v in vars(_dt).items() if k not in ("__name__", "__doc__")})
_proxy.__dict__.update(datetime=ClockDatetime, date=ClockDate)


class _ScopedImport:
    """`builtins.__import__`, answering `import datetime` / `from datetime import ...` with the clock's classes
    when the importing module is `app.*` or `tests.*` (module level and inside functions alike). Every other
    import, and every other caller, goes to the import function that was in place before (a test that
    monkeypatches `builtins.__import__` wraps this one and keeps working)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __call__(self, name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if name == "datetime" and level == 0 and globals and str(globals.get("__name__", "")).split(".")[0] in SCOPES:
            return _proxy
        return self.inner(name, globals, locals, fromlist, level)


def install() -> None:
    """Route `datetime.datetime` / `datetime.date` through this clock in every `app.*` / `tests.*` module that
    imports them from now on.

    Idempotent. Harmless while nothing is pinned (the real time is returned)."""
    if not isinstance(builtins.__import__, _ScopedImport):
        builtins.__import__ = _ScopedImport(builtins.__import__)
        import sqlite3

        # sqlite3 looks its adapters up by exact type: the stdlib's own conversions, for the subclasses.
        sqlite3.register_adapter(ClockDatetime, lambda v: v.isoformat(" "))
        sqlite3.register_adapter(ClockDate, lambda v: v.isoformat())

def install_from_env(environ: Any = None) -> real_datetime | None:
    """For the API and worker processes: pin to `APP_CLOCK_START` when the environment allows it."""
    instant = override_from_env(environ)
    if instant is not None:
        install()
        pin(instant)
    return instant
