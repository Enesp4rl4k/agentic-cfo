"""
Sentry Error Monitoring — PROD-2

Backend için Sentry entegrasyonu.

Kurulum:
  pip install sentry-sdk[fastapi]

.env'e ekle:
  SENTRY_DSN=https://xxx@sentry.io/xxx
  SENTRY_ENVIRONMENT=production  # veya staging/development
  SENTRY_TRACES_SAMPLE_RATE=0.1  # %10 performance tracing

Özellikler:
  - FastAPI exception tracking
  - LangGraph agent hata yakalama
  - Database hatası loglama
  - Performance tracing (opsiyonel, maliyet gözetilerek %10)
  - Kullanıcı bağlamı (org_id, user_id)
  - PII filtreleme (şifre, API key alanları gizlenir)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def init_sentry(settings: Any) -> bool:
    """
    Sentry'yi başlat. DSN yoksa sessizce atla.

    Returns True if Sentry was successfully initialized.
    """
    dsn = getattr(settings, "sentry_dsn", "") or ""
    if not dsn or dsn.startswith("https://xxx"):
        logger.debug("Sentry DSN not configured — error monitoring disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        environment = getattr(settings, "sentry_environment", "production")
        sample_rate = getattr(settings, "sentry_traces_sample_rate", 0.05)

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=float(sample_rate),

            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                AsyncioIntegration(),
                LoggingIntegration(
                    level=logging.WARNING,  # Only WARNING+ to Sentry
                    event_level=logging.ERROR,
                ),
            ],

            # PII filtreleme — hassas veri Sentry'ye gitmesin
            before_send=_filter_sensitive_data,

            # Request veri ayarları
            send_default_pii=False,  # Email, IP gibi PII'ları otomatik gönderme
            max_request_body_size="small",  # max 4KB request body

            # Release tracking (CI'da GIT_COMMIT env var set edilir)
            release=getattr(settings, "app_version", None),
        )

        logger.info("Sentry initialized: env=%s", environment)
        return True

    except ImportError:
        logger.warning("sentry-sdk not installed — run: pip install sentry-sdk[fastapi]")
        return False
    except Exception as exc:
        logger.warning("Sentry initialization failed: %s", exc)
        return False


def _filter_sensitive_data(event: dict, hint: dict) -> dict | None:
    """
    PII ve hassas veri filtreleme.

    - Şifre, token, API key alanlarını temizler
    - Büyük JSON payload'larını kırpar
    """
    _SENSITIVE_KEYS = {
        "password", "hashed_password", "token", "access_token", "refresh_token",
        "api_key", "secret", "secret_key", "authorization", "openai_api_key",
        "azure_client_secret", "google_client_secret", "smtp_password",
    }

    def _redact(obj: Any, depth: int = 0) -> Any:
        if depth > 5:
            return obj
        if isinstance(obj, dict):
            return {
                k: "[REDACTED]" if k.lower() in _SENSITIVE_KEYS else _redact(v, depth + 1)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_redact(item, depth + 1) for item in obj[:20]]  # Limit list size
        if isinstance(obj, str) and len(obj) > 1000:
            return obj[:1000] + "...[truncated]"
        return obj

    try:
        if "request" in event:
            event["request"] = _redact(event["request"])
        if "extra" in event:
            event["extra"] = _redact(event["extra"])
    except Exception:
        pass

    return event


def capture_agent_error(
    agent_name: str,
    error: Exception,
    context: dict | None = None,
    org_id: str | None = None,
) -> None:
    """
    Agent hatasını Sentry'ye gönder.

    Usage:
        try:
            result = await run_cfo_pipeline(state, config)
        except Exception as exc:
            capture_agent_error("cfo", exc, {"job_id": job_id}, org_id=org_id)
            raise
    """
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("agent", agent_name)
            if org_id:
                scope.set_user({"id": org_id})
            if context:
                for k, v in context.items():
                    scope.set_extra(k, v)
            sentry_sdk.capture_exception(error)
    except Exception:
        pass


def set_sentry_user(user_id: str, org_id: str | None = None, email: str | None = None) -> None:
    """
    Sentry scope'una kullanıcı bağlamı ekle.
    Auth endpoint'lerinde çağır.
    """
    try:
        import sentry_sdk
        sentry_sdk.set_user({
            "id":    user_id,
            "org":   org_id,
            # email gönderilmiyor — PII
        })
    except Exception:
        pass
