"""Operational hardening that touches no product behaviour: logs carry no personal data, the API sends a
CSP, error tracking reads its DSN from the environment."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.log_redaction import RedactingFilter, redact
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.sentry_monitoring import init_sentry
from app.services.telemetry import JSONFormatter


def test_an_email_address_keeps_its_first_letter_and_domain() -> None:
    assert redact("User logged in: ayse.yilmaz@firma.com.tr ok") == "User logged in: a***@firma.com.tr ok"


def test_an_iban_keeps_country_and_last_four() -> None:
    assert redact("hesap TR33 0006 1005 1978 6457 8413 26 yatti") == "hesap TR**…26 yatti"


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer " + "t" * 30,
        "password=" + "p" * 14,
        "api_key: sk-" + "k" * 20,
        'refresh_token": "' + "r" * 12 + '"',
    ],
)
def test_credentials_are_masked(line: str) -> None:
    out = redact(line)
    assert "[redacted]" in out
    assert not any(run in out for run in ("t" * 12, "p" * 8, "k" * 8, "r" * 8))


def test_text_without_personal_data_is_untouched() -> None:
    line = "Org created: Acme (slug=acme) job=3f9c2a54 rows=120 balance=1250.50"
    assert redact(line) == line and redact("") == ""


def record(msg: str, *args: Any, **extra: Any) -> logging.LogRecord:
    rec = logging.LogRecord("app.api.auth", logging.INFO, __file__, 1, msg, args, None)
    rec.__dict__.update(extra)
    return rec


def test_the_json_formatter_masks_message_extras_and_traceback() -> None:
    try:
        raise RuntimeError("smtp refused owner@firma.com")
    except RuntimeError:
        import sys

        rec = record("User logged in: %s", "owner@firma.com", recipient="x@y.com", n=3)
        rec.exc_info = sys.exc_info()
    out = json.loads(JSONFormatter().format(rec))
    assert out["msg"] == "User logged in: o***@firma.com"
    assert out["recipient"] == "x***@y.com" and out["n"] == 3
    assert "owner@firma.com" not in out["exc"]
    assert "@" not in json.dumps(out).replace("***@", "")


def test_the_text_format_filter_masks_the_rendered_line() -> None:
    rec = record("Invite queued: %s -> %s", "Acme", "cfo@acme.com.tr")
    assert RedactingFilter().filter(rec)
    assert rec.getMessage() == "Invite queued: Acme -> c***@acme.com.tr"


# ── CSP ────────────────────────────────────────────────────────────────────────


def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/thing")
    async def thing() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/docs")
    async def docs() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_the_api_forbids_loading_framing_and_basing_anything() -> None:
    csp = client().get("/api/thing").headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "base-uri 'none'" in csp


def test_the_docs_pages_are_exempt_because_they_need_scripts() -> None:
    res = client().get("/docs")
    assert "Content-Security-Policy" not in res.headers
    assert res.headers["X-Content-Type-Options"] == "nosniff"


# ── Sentry ─────────────────────────────────────────────────────────────────────


def test_sentry_reads_its_dsn_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings has no sentry fields, so `getattr(settings, "sentry_dsn")` was always empty."""
    sentry_sdk = pytest.importorskip("sentry_sdk")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example.test/42")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    assert init_sentry(SimpleNamespace()) is True
    assert seen["dsn"].endswith("/42") and seen["environment"] == "staging"
    assert seen["release"] == "abc1234" and seen["send_default_pii"] is False


def test_sentry_stays_off_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry(SimpleNamespace()) is False
