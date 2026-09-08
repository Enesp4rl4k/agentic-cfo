"""Kuyruk mu, bu süreç mi — ikisi aynı söz değil.

`enqueue_analysis` falls back to running the pipeline inline when the broker is
briefly unreachable, which is what keeps upload → analysis working on a machine
with no Redis. That fallback is deliberate. What was not deliberate is that the
API reported `queued: true` either way, so a run that would die with the
process was announced as safely queued.

The other half is the classifier. It used to decide "transient" by looking for
the substring "redis" in the exception text, which made an authentication
failure transient too — so a wrong password would silently run every job inline
and never be reported. A misconfiguration that keeps working is one nobody
fixes.

Testable without a broker, which matters: there is no Docker on this machine
(see the docker-deferred note), so the queue path itself stays unverified and
these are the parts that need not.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from redis import exceptions as redis_exc

from app.worker import _is_transient_error, enqueue_analysis

# ── Which broker faults deserve an inline run ────────────────────────────────

@pytest.mark.parametrize(
    ("exc", "transient", "why"),
    [
        (redis_exc.TimeoutError("Timeout connecting to server"), True,
         "broker yok — bu makinede olağan durum"),
        (redis_exc.ConnectionError("Error 10061 connecting to localhost:6379."), True,
         "bağlantı reddedildi"),
        (redis_exc.BusyLoadingError("Redis is loading the dataset in memory"), True,
         "sunucu açılıyor"),
        (ConnectionRefusedError("refused"), True, "yerleşik soket hatası"),
        (OSError("network unreachable"), True, "ağ"),
        (redis_exc.AuthenticationError("Authentication required."), False,
         "kimlik doğrulama — yapılandırma hatası"),
        (redis_exc.ResponseError("WRONGPASS invalid username-password pair"), False,
         "yanlış parola"),
        (ValueError("redis config broken"), False,
         "metninde redis geçiyor ama geçici değil"),
    ],
)
def test_only_a_briefly_unreachable_broker_is_transient(
    exc: Exception, transient: bool, why: str
) -> None:
    assert _is_transient_error(exc) is transient, why


def test_redis_exceptions_do_not_subclass_the_builtins() -> None:
    """The reason the classifier has to name both families.

    `redis.exceptions.ConnectionError` descends from RedisError, not from the
    builtin of the same name — so a rule that only knew the builtins would call
    a missing broker permanent and fail every upload.
    """
    assert not issubclass(redis_exc.ConnectionError, ConnectionError)
    assert not issubclass(redis_exc.TimeoutError, TimeoutError)
    # And this is why the message check is not optional:
    assert issubclass(redis_exc.AuthenticationError, redis_exc.ConnectionError)


# ── What the caller is told ──────────────────────────────────────────────────

@pytest.fixture
def inline_fallback(monkeypatch):
    """Toggle the fallback on the cached settings instance.

    It is a pydantic field, so it lives on the object rather than the class.
    """

    def _set(allowed: bool) -> None:
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "allow_inline_job_fallback", allowed)

    return _set


@pytest.mark.asyncio
async def test_a_queued_job_reports_queued() -> None:
    pool = AsyncMock()
    with patch("app.worker.get_arq_pool", AsyncMock(return_value=pool)):
        assert await enqueue_analysis("job-1") == "queued"
    pool.enqueue_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_inline_run_says_inline_rather_than_queued(inline_fallback) -> None:
    """The distinction the API could not make.

    An inline run dies with the process and is never retried; announcing it as
    queued tells the user their work is safe when it is not.
    """
    inline_fallback(True)
    ran = asyncio.Event()

    async def _fake_run(_ctx, _job_id, _budget=None):
        ran.set()

    with (
        patch("app.worker.get_arq_pool",
              AsyncMock(side_effect=redis_exc.TimeoutError("Timeout connecting to server"))),
        patch("app.worker.run_cfo_analysis", _fake_run),
    ):
        assert await enqueue_analysis("job-2") == "inline"
        # Fire-and-forget: the caller must not be held for the pipeline.
        await asyncio.wait_for(ran.wait(), timeout=5)


@pytest.mark.asyncio
async def test_a_misconfigured_broker_is_raised_not_hidden(inline_fallback) -> None:
    """A wrong password used to fall through to inline, so every job ran
    undurably and the deployment never learned why."""
    inline_fallback(True)
    with (
        patch("app.worker.get_arq_pool",
              AsyncMock(side_effect=redis_exc.AuthenticationError("WRONGPASS"))),
    ):
        with pytest.raises(redis_exc.AuthenticationError):
            await enqueue_analysis("job-3")


@pytest.mark.asyncio
async def test_without_the_fallback_an_unreachable_broker_raises(inline_fallback) -> None:
    inline_fallback(False)
    with (
        patch("app.worker.get_arq_pool",
              AsyncMock(side_effect=redis_exc.TimeoutError("Timeout connecting"))),
    ):
        with pytest.raises(redis_exc.TimeoutError):
            await enqueue_analysis("job-4")


# ── Both upload paths have to say the same thing ─────────────────────────────

def test_both_upload_routes_report_how_the_work_was_dispatched() -> None:
    """These two have diverged once already: /data-quality copied the job
    creation from /upload and not the enqueue, so the UI's uploads sat pending
    forever behind `started: true`."""
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    for rel in ("api/upload.py", "api/data_quality.py"):
        src = (app / rel).read_text(encoding="utf-8")
        assert "enqueue_analysis(" in src, rel
        assert '"dispatch"' in src, f"{rel}: yanıt hangi yoldan gittiğini söylemiyor"
        assert '"durable"' in src, f"{rel}: dayanıklılık bildirilmiyor"
        assert "logger.exception" in src, f"{rel}: enqueue hatası sessizce yutuluyor"
