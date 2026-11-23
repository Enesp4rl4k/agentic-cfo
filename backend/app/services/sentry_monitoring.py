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

Gizlilik (KVKK): Sentry bir üçüncü taraf aktarımıdır; DSN ayarlanmadıkça HİÇBİR ŞEY gönderilmez
(varsayılan kapalı). Açıkken: `send_default_pii=False`, istek gövdesi hiç eklenmez
(`max_request_body_size="never"`), yerel değişkenler eklenmez, ve `before_send` her olayda istek
gövdesini, çerezleri, kimlik bilgisi taşıyan başlıkları siler; mesaj, istisna metni, breadcrumb ve
extra içindeki e-posta, IBAN, bearer ve `anahtar=değer` sırları log maskeleme yardımcısıyla maskelenir.
"""
from __future__ import annotations

import logging
import os
from typing import Any, cast

logger = logging.getLogger(__name__)


def init_sentry(settings: Any) -> bool:
    """
    Sentry'yi başlat. DSN yoksa sessizce atla.

    Returns True if Sentry was successfully initialized.
    """
    # `Settings` has no sentry fields (it ignores unknown variables), so the setting alone never
    # reached this function and error tracking was silently off. The process environment is the source.
    dsn = getattr(settings, "sentry_dsn", "") or os.environ.get("SENTRY_DSN", "")
    if not dsn or dsn.startswith("https://xxx"):
        logger.debug("Sentry DSN not configured — error monitoring disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        environment = getattr(settings, "sentry_environment", None) or os.environ.get(
            "SENTRY_ENVIRONMENT", os.environ.get("APP_ENV", "production")
        )
        sample_rate = getattr(settings, "sentry_traces_sample_rate", None) or os.environ.get(
            "SENTRY_TRACES_SAMPLE_RATE", "0.05"
        )

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
            before_send=cast(Any, _filter_sensitive_data),

            # Request veri ayarları: gövde yok, yerel değişken yok, PII yok.
            send_default_pii=False,  # Email, IP gibi PII'ları otomatik gönderme
            max_request_body_size="never",
            include_local_variables=False,
            before_breadcrumb=cast(Any, _scrub_breadcrumb),

            # Release tracking (CI'da GIT_COMMIT env var set edilir)
            release=getattr(settings, "app_version", None) or os.environ.get("GIT_SHA") or None,
        )

        logger.info("Sentry initialized: env=%s", environment)
        return True

    except ImportError:
        logger.warning("sentry-sdk not installed — run: pip install sentry-sdk[fastapi]")
        return False
    except Exception as exc:
        logger.warning("Sentry initialization failed: %s", exc)
        return False


_SENSITIVE_KEYS = {
    "password", "hashed_password", "token", "access_token", "refresh_token", "invite_token", "id_token",
    "api_key", "secret", "secret_key", "authorization", "openai_api_key", "x-api-key", "x-ops-token",
    "azure_client_secret", "google_client_secret", "smtp_password", "cookie", "set-cookie",
    "x-forwarded-for", "x-real-ip",
}
_DROPPED_REQUEST_KEYS = ("data", "cookies", "query_string")


def _mask(value: str) -> str:
    from app.core.log_redaction import redact

    masked = redact(value)
    return masked[:1000] + "...[truncated]" if len(masked) > 1000 else masked


def _redact(obj: Any, depth: int = 0) -> Any:
    """Sensitive keys replaced, every string masked (e-mail, IBAN, bearer, key=value secrets), depth and
    list length bounded. Applied to the whole event, not to a list of fields we remembered."""
    if depth > 8:
        return "[deep]"
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if str(k).lower() in _SENSITIVE_KEYS else _redact(v, depth + 1) for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(item, depth + 1) for item in obj[:50]]
    if isinstance(obj, str):
        return _mask(obj)
    return obj


def _scrub_breadcrumb(crumb: dict, hint: dict) -> dict | None:
    try:
        return _redact(crumb)  # type: ignore[no-any-return]
    except Exception:
        return None


def _filter_sensitive_data(event: dict, hint: dict) -> dict | None:
    """The last thing every event passes before it leaves the process (KVKK: a third-party transfer).

    Removes the request body, cookies, query string and credential headers outright; masks e-mails, IBANs,
    bearer tokens and `key=value` secrets in every remaining string (message, exception text, breadcrumbs,
    extra, contexts, tags); drops the user's e-mail and IP (an id may stay). If scrubbing itself fails the
    event is dropped rather than sent half-clean."""
    try:
        request = event.get("request")
        if isinstance(request, dict):
            for key in _DROPPED_REQUEST_KEYS:
                request.pop(key, None)
        user = event.get("user")
        if isinstance(user, dict):
            event["user"] = {k: v for k, v in user.items() if k in ("id", "org")}
        return _redact(event)  # type: ignore[no-any-return]
    except Exception:
        return None


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
