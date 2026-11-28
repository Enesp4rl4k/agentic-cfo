"""`llm_call_logs.error` stores an exception type and a short code, never the exception's message.

A provider's or a validator's message can quote the model's output or our own input (a name, an amount):
`f"{type(exc).__name__}: {exc}"` put that text into the audit table. The gateway now stores `<Type>:<code>`
(`timeout`, `http_429`, `provider_rejected_400`, `failed`), as the embedding gateway already stored the type
alone, and `persist_call_log` drops anything after the leading identifier of a string that is not in that shape.
Fake transport only.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.platform.llm_egress.audit import error_code, safe_error
from tests.llm_egress_harness import CANARY, Recorder, open_world

SECRET_TEXT = f"model said: {CANARY.person} owes 1.234.567,89 TL to {CANARY.counterparty}"


@pytest.mark.parametrize(("given", "stored"), [
    (None, None),
    ("", None),
    ("TimeoutError", "TimeoutError"),
    ("APIStatusError:http_429", "APIStatusError:http_429"),
    ("egress_refused:no_organisation_context", "egress_refused:no_organisation_context"),
    (f"ValidationError: {SECRET_TEXT}", "ValidationError"),
    ("RuntimeError:fallback", "RuntimeError:fallback"), ("TimeoutError:loop_timeout", "TimeoutError:loop_timeout"),
    ("X:provider_rejected_400", "X:provider_rejected_400"), (f"RuntimeError:{SECRET_TEXT}", "RuntimeError"),
    (SECRET_TEXT, "error"),
    ("çok gizli: Selin", "error"),
])
def test_safe_error_keeps_a_type_and_a_code_only(given, stored) -> None:
    assert safe_error(given) == stored


def test_error_code_is_the_type_and_the_code() -> None:
    assert error_code(ValueError(SECRET_TEXT)) == "ValueError"
    assert error_code(TimeoutError(), "timeout") == "TimeoutError:timeout"


class _Boom:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def ainvoke(self, messages: list[Any]) -> Any:
        raise self.exc


class _HTTPError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(("exc", "stored"), [
    (RuntimeError(SECRET_TEXT), "RuntimeError:failed"),
    (_HTTPError(SECRET_TEXT, 400), "_HTTPError:provider_rejected_400"),
    (_HTTPError(SECRET_TEXT, 503), "_HTTPError:http_503"),
])
async def test_a_failed_call_stores_no_message(monkeypatch, exc, stored) -> None:
    from app.platform import model_gateway as mg

    rows: list[dict[str, Any]] = []
    async with open_world(monkeypatch, Recorder(), tenant=True):
        monkeypatch.setattr(mg, "_build_client", lambda cfg, temperature, max_tokens: _Boom(exc))
        monkeypatch.setattr(mg, "_persist_call_log", lambda **kw: rows.append(kw))
        with pytest.raises((RuntimeError, mg.LLMUnavailable)):
            await mg.complete(task="deep_analysis", prompt="özet", max_attempts=1)
    failed = [r for r in rows if not r["ok"]]
    assert [r["error"] for r in failed] == [stored]
    assert all(CANARY.person not in str(r.get("error")) for r in rows)


async def test_the_router_reply_names_the_error_type_never_its_message(monkeypatch) -> None:
    """`LLMTaskRouter.complete` puts its error into the REPLY text: only the type (no production caller, but the
    matrix and tests drive it)."""
    from app.services.llm_router import LLMTaskRouter

    async def boom(self, **kwargs):
        raise ValueError(SECRET_TEXT)

    monkeypatch.setattr(LLMTaskRouter, "_call_llm", boom)
    res = await LLMTaskRouter().complete("deep_analysis", "özet")
    assert res.content == "[LLM hatası: ValueError]" and CANARY.person not in res.content
