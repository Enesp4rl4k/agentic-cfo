"""
Loop Engineering — RetryHarness

Solves the self-correction loop problem in agentic pipelines:
  - Agent produces output → validate → if invalid, retry with correction hint
  - Max 3 retries with exponential back-off (async-safe)
  - Each retry gets a richer correction prompt ("your previous answer was wrong because...")
  - After max retries → fallback strategy (raise | return_last | return_default)
  - Full observability: every attempt logged with latency + reason

Design:
  - Pure async, no side effects
  - Works with any async callable (agent function or LLM call)
  - Validator is a Callable[[Any], tuple[bool, str]] returning (ok, reason)
  - Correction builder is a Callable[[Any, str, int], str] → new prompt/input

Usage:
    harness = RetryHarness(max_retries=3, fallback="return_last")

    result = await harness.run(
        fn=my_agent_fn,
        initial_input=prompt,
        validator=validate_json_output,
        correction_builder=build_correction_prompt,
    )
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

FallbackStrategy = Literal["raise", "return_last", "return_default"]


# ── Attempt log ───────────────────────────────────────────────────────────────

@dataclass
class AttemptLog:
    attempt: int
    ok: bool
    latency_ms: float
    reason: str | None = None
    output_preview: str | None = None


@dataclass
class RetryResult:
    value: Any
    attempts: list[AttemptLog]
    success: bool
    total_latency_ms: float

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def last_failure_reason(self) -> str | None:
        failed = [a for a in self.attempts if not a.ok]
        return failed[-1].reason if failed else None


# ── Built-in validators ───────────────────────────────────────────────────────

def validate_non_empty_string(output: Any) -> tuple[bool, str]:
    if not isinstance(output, str) or not output.strip():
        return False, "Output is empty or not a string."
    return True, ""


def validate_non_empty_dict(output: Any) -> tuple[bool, str]:
    if not isinstance(output, dict) or not output:
        return False, "Output is empty or not a dict."
    return True, ""


def validate_has_keys(*required_keys: str):
    """Returns a validator that checks for required keys in a dict."""
    def _validator(output: Any) -> tuple[bool, str]:
        if not isinstance(output, dict):
            return False, f"Expected dict, got {type(output).__name__}."
        missing = [k for k in required_keys if k not in output]
        if missing:
            return False, f"Missing required keys: {missing}"
        return True, ""
    return _validator


def validate_narrative_quality(output: Any) -> tuple[bool, str]:
    """
    Validates LLM narrative output:
    - Must be non-empty string
    - At least 50 characters
    - Not a JSON blob (agent hallucination pattern)
    - Not a refusal ("üzgünüm", "yapamam", "I cannot")
    """
    if not isinstance(output, str):
        return False, "Not a string."
    text = output.strip()
    if len(text) < 50:
        return False, f"Too short: {len(text)} chars (min 50)."
    refusals = ["üzgünüm", "yapamam", "i cannot", "i'm unable", "as an ai"]
    if any(r in text.lower() for r in refusals):
        return False, f"Detected refusal pattern in output."
    if text.startswith("{") or text.startswith("["):
        return False, "Output looks like JSON, not narrative."
    return True, ""


# ── Default correction builder ────────────────────────────────────────────────

def default_correction_builder(
    original_input: Any,
    previous_output: Any,
    failure_reason: str,
    attempt: int,
) -> Any:
    """
    Builds a corrected input for the next attempt.
    If the input is a string (prompt), appends a correction instruction.
    Otherwise returns the original input unchanged.
    """
    if not isinstance(original_input, str):
        return original_input

    return (
        f"{original_input}\n\n"
        f"--- CORRECTION REQUEST (attempt {attempt}) ---\n"
        f"Your previous response was rejected because: {failure_reason}\n"
        f"Previous response (rejected): {str(previous_output)[:200]}\n"
        f"Please try again and correct the issue."
    )


# ── RetryHarness ──────────────────────────────────────────────────────────────

class RetryHarness:
    """
    Generic async retry harness with self-correction.

    Parameters
    ----------
    max_retries : int
        Maximum number of attempts (1 = no retry).
    fallback : FallbackStrategy
        What to do after max_retries:
          "raise"          — raise RuntimeError
          "return_last"    — return last output even if invalid
          "return_default" — return default_value
    default_value : Any
        Used when fallback="return_default".
    base_delay_ms : float
        Initial delay between retries in milliseconds.
    backoff_factor : float
        Multiply delay by this factor on each retry.
    """

    def __init__(
        self,
        max_retries: int = 3,
        fallback: FallbackStrategy = "return_last",
        default_value: Any = None,
        base_delay_ms: float = 200.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.max_retries = max(1, max_retries)
        self.fallback = fallback
        self.default_value = default_value
        self.base_delay_ms = base_delay_ms
        self.backoff_factor = backoff_factor

    async def run(
        self,
        fn: Callable[..., Awaitable[Any]],
        initial_input: Any,
        validator: Callable[[Any], tuple[bool, str]] | None = None,
        correction_builder: Callable[[Any, Any, str, int], Any] | None = None,
        fn_kwargs: dict[str, Any] | None = None,
    ) -> RetryResult:
        """
        Run `fn(current_input, **fn_kwargs)` up to `max_retries` times.

        Parameters
        ----------
        fn : async callable
            The function to retry. Receives (current_input, **fn_kwargs).
        initial_input : Any
            First input passed to fn.
        validator : callable, optional
            (output) → (ok: bool, reason: str). If None, always passes.
        correction_builder : callable, optional
            (original_input, previous_output, reason, attempt) → new_input.
            Defaults to `default_correction_builder`.
        fn_kwargs : dict, optional
            Extra keyword arguments passed to fn on every call.
        """
        if validator is None:
            validator = lambda _: (True, "")
        if correction_builder is None:
            correction_builder = default_correction_builder
        if fn_kwargs is None:
            fn_kwargs = {}

        attempts: list[AttemptLog] = []
        current_input = initial_input
        last_output: Any = None
        start_total = time.monotonic()

        for attempt in range(1, self.max_retries + 1):
            t0 = time.monotonic()
            try:
                output = await fn(current_input, **fn_kwargs)
            except Exception as exc:
                latency = (time.monotonic() - t0) * 1000
                reason = f"Exception: {exc}"
                attempts.append(AttemptLog(
                    attempt=attempt,
                    ok=False,
                    latency_ms=latency,
                    reason=reason,
                ))
                logger.warning("RetryHarness attempt %d/%d failed: %s", attempt, self.max_retries, reason)
                last_output = None
                if attempt < self.max_retries:
                    await asyncio.sleep(self.base_delay_ms * (self.backoff_factor ** (attempt - 1)) / 1000)
                continue

            latency = (time.monotonic() - t0) * 1000
            last_output = output
            ok, reason = validator(output)

            preview = str(output)[:80] if output is not None else None
            attempts.append(AttemptLog(
                attempt=attempt,
                ok=ok,
                latency_ms=latency,
                reason=reason if not ok else None,
                output_preview=preview,
            ))

            if ok:
                total = (time.monotonic() - start_total) * 1000
                logger.debug(
                    "RetryHarness succeeded on attempt %d/%d (%.0f ms)",
                    attempt, self.max_retries, total,
                )
                return RetryResult(
                    value=output,
                    attempts=attempts,
                    success=True,
                    total_latency_ms=total,
                )

            logger.warning(
                "RetryHarness attempt %d/%d invalid: %s", attempt, self.max_retries, reason
            )

            if attempt < self.max_retries:
                current_input = correction_builder(initial_input, output, reason, attempt)
                await asyncio.sleep(
                    self.base_delay_ms * (self.backoff_factor ** (attempt - 1)) / 1000
                )

        # Max retries exhausted
        total = (time.monotonic() - start_total) * 1000
        logger.error(
            "RetryHarness exhausted %d attempts. Last reason: %s",
            self.max_retries,
            attempts[-1].reason if attempts else "unknown",
        )

        if self.fallback == "raise":
            last_reason = attempts[-1].reason if attempts else "unknown"
            raise RuntimeError(
                f"RetryHarness failed after {self.max_retries} attempts. "
                f"Last reason: {last_reason}"
            )
        elif self.fallback == "return_default":
            return RetryResult(
                value=self.default_value,
                attempts=attempts,
                success=False,
                total_latency_ms=total,
            )
        else:  # return_last
            return RetryResult(
                value=last_output,
                attempts=attempts,
                success=False,
                total_latency_ms=total,
            )


# ── Convenience wrapper ───────────────────────────────────────────────────────

async def retry_with_correction(
    fn: Callable[..., Awaitable[Any]],
    initial_input: Any,
    validator: Callable[[Any], tuple[bool, str]] | None = None,
    max_retries: int = 3,
    fallback: FallbackStrategy = "return_last",
    **fn_kwargs: Any,
) -> RetryResult:
    """
    Convenience function wrapping RetryHarness.

    Example:
        result = await retry_with_correction(
            fn=call_llm,
            initial_input=prompt,
            validator=validate_narrative_quality,
            max_retries=3,
        )
        narrative = result.value
    """
    harness = RetryHarness(max_retries=max_retries, fallback=fallback)
    return await harness.run(fn, initial_input, validator=validator, fn_kwargs=fn_kwargs)
