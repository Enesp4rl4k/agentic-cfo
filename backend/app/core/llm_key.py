"""One answer to "is this LLM API key a template value, not a real key?".

A template key must never reach a provider: the request would carry company data to be rejected with a 401, and the
honest "no model" path (deterministic answer or 503) would never be taken. Used by the preflight, the model gateway,
`llm_structured` and `rag_service`.

Placeholder (case-insensitive, after trimming):
  * empty or whitespace
  * `llm-placeholder-*` (dev, demo, ci, mock ...)
  * `your-*` (`your-llm-api-key-here`, the old .env.example value)
  * `change-me*`, `changeme*`, `change_me*`, `change-this*`
  * `xxx*` and `sk-xxx*` (obvious templates such as `sk-xxxxxxxx`)
  * `<...>` (an unfilled `<api key>`)
"""

from __future__ import annotations

_PREFIXES = ("llm-placeholder-", "your-", "change-me", "changeme", "change_me", "change-this", "xxx", "sk-xxx")


def is_placeholder_key(api_key: str | None) -> bool:
    value = (api_key or "").strip().lower()
    if not value:
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    return value.startswith(_PREFIXES)
