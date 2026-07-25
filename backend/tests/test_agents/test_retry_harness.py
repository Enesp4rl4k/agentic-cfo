"""
Tests for RetryHarness — loop engineering layer.
Pure async tests, no LLM, no DB.
"""
import asyncio
import pytest

from app.services.retry_harness import (
    RetryHarness,
    RetryResult,
    AttemptLog,
    retry_with_correction,
    validate_non_empty_string,
    validate_non_empty_dict,
    validate_has_keys,
    validate_narrative_quality,
    default_correction_builder,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

async def always_ok(input_: str, **kwargs) -> str:
    return f"OK: {input_}"


async def always_fail(input_: str, **kwargs) -> str:
    return ""  # empty — will fail validate_non_empty_string


async def fail_then_succeed(input_: str, state=None, **kwargs) -> str:
    """Fails first 2 calls, succeeds on 3rd."""
    if not hasattr(fail_then_succeed, "_count"):
        fail_then_succeed._count = 0
    fail_then_succeed._count += 1
    if fail_then_succeed._count < 3:
        return ""
    return "success narrative"


async def raises_on_call(input_: str, **kwargs) -> str:
    raise ValueError("Simulated LLM error")


# ── Validators ────────────────────────────────────────────────────────────────

class TestValidators:
    def test_non_empty_string_pass(self):
        ok, _ = validate_non_empty_string("hello")
        assert ok

    def test_non_empty_string_fail_empty(self):
        ok, reason = validate_non_empty_string("")
        assert not ok
        assert "empty" in reason.lower()

    def test_non_empty_string_fail_not_string(self):
        ok, _ = validate_non_empty_string(123)
        assert not ok

    def test_non_empty_dict_pass(self):
        ok, _ = validate_non_empty_dict({"key": "val"})
        assert ok

    def test_non_empty_dict_fail_empty(self):
        ok, _ = validate_non_empty_dict({})
        assert not ok

    def test_non_empty_dict_fail_not_dict(self):
        ok, _ = validate_non_empty_dict("string")
        assert not ok

    def test_has_keys_pass(self):
        validator = validate_has_keys("a", "b")
        ok, _ = validator({"a": 1, "b": 2, "c": 3})
        assert ok

    def test_has_keys_fail_missing(self):
        validator = validate_has_keys("a", "b", "c")
        ok, reason = validator({"a": 1})
        assert not ok
        assert "b" in reason or "c" in reason

    def test_has_keys_fail_not_dict(self):
        validator = validate_has_keys("a")
        ok, _ = validator("not a dict")
        assert not ok

    def test_narrative_quality_pass(self):
        ok, _ = validate_narrative_quality(
            "Gelir büyümesi %15 ile güçlü seyretti. EBITDA marjı hedeflerin üzerinde kaldı."
        )
        assert ok

    def test_narrative_quality_fail_too_short(self):
        ok, reason = validate_narrative_quality("Kısa.")
        assert not ok
        assert "short" in reason.lower()

    def test_narrative_quality_fail_json(self):
        # Must be >= 50 chars so "too short" doesn't fire first
        json_output = '{"revenue": 4800000, "net_income": 1440000, "margin": 0.30, "opex": {"salary": 1200000}}'
        ok, reason = validate_narrative_quality(json_output)
        assert not ok
        assert "json" in reason.lower()

    def test_narrative_quality_fail_refusal(self):
        ok, reason = validate_narrative_quality(
            "Üzgünüm, bu konuda yardım edemiyorum çünkü bilgim yok."
        )
        assert not ok
        assert "refusal" in reason.lower()

    def test_narrative_quality_fail_not_string(self):
        ok, _ = validate_narrative_quality(42)
        assert not ok


# ── Default correction builder ────────────────────────────────────────────────

class TestCorrectionBuilder:
    def test_string_input_appends_correction(self):
        new_input = default_correction_builder(
            original_input="Original prompt",
            previous_output="bad output",
            failure_reason="Too short",
            attempt=1,
        )
        assert "Original prompt" in new_input
        assert "Too short" in new_input
        assert "CORRECTION REQUEST" in new_input

    def test_non_string_input_returned_unchanged(self):
        original = {"key": "value"}
        result = default_correction_builder(original, "bad", "reason", 1)
        assert result == original

    def test_attempt_number_in_output(self):
        result = default_correction_builder("prompt", "out", "reason", 2)
        assert "attempt 2" in result


# ── RetryHarness ──────────────────────────────────────────────────────────────

class TestRetryHarness:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        harness = RetryHarness(max_retries=3)
        result = await harness.run(always_ok, "test")
        assert result.success
        assert result.value == "OK: test"
        assert result.attempt_count == 1

    @pytest.mark.asyncio
    async def test_no_validator_always_passes(self):
        harness = RetryHarness(max_retries=3)
        result = await harness.run(always_fail, "test", validator=None)
        assert result.success
        assert result.attempt_count == 1

    @pytest.mark.asyncio
    async def test_fails_with_validator_exhausts_retries(self):
        harness = RetryHarness(max_retries=3, fallback="return_last", base_delay_ms=0)
        result = await harness.run(
            always_fail, "test", validator=validate_non_empty_string
        )
        assert not result.success
        assert result.attempt_count == 3

    @pytest.mark.asyncio
    async def test_succeeds_on_third_attempt(self):
        fail_then_succeed._count = 0  # reset state
        harness = RetryHarness(max_retries=3, base_delay_ms=0)
        result = await harness.run(
            fail_then_succeed, "test", validator=validate_non_empty_string
        )
        assert result.success
        assert result.attempt_count == 3
        assert result.value == "success narrative"

    @pytest.mark.asyncio
    async def test_fallback_raise(self):
        harness = RetryHarness(max_retries=2, fallback="raise", base_delay_ms=0)
        with pytest.raises(RuntimeError, match="RetryHarness failed"):
            await harness.run(always_fail, "test", validator=validate_non_empty_string)

    @pytest.mark.asyncio
    async def test_fallback_return_default(self):
        harness = RetryHarness(
            max_retries=2, fallback="return_default",
            default_value="fallback narrative", base_delay_ms=0
        )
        result = await harness.run(always_fail, "test", validator=validate_non_empty_string)
        assert not result.success
        assert result.value == "fallback narrative"

    @pytest.mark.asyncio
    async def test_fallback_return_last(self):
        harness = RetryHarness(max_retries=2, fallback="return_last", base_delay_ms=0)
        result = await harness.run(always_fail, "test", validator=validate_non_empty_string)
        assert not result.success
        assert result.value == ""  # last (empty) output

    @pytest.mark.asyncio
    async def test_exception_in_fn_caught(self):
        harness = RetryHarness(max_retries=3, fallback="return_last", base_delay_ms=0)
        result = await harness.run(raises_on_call, "test")
        assert not result.success
        assert result.attempt_count == 3
        assert all(not a.ok for a in result.attempts)

    @pytest.mark.asyncio
    async def test_attempt_logs_have_latency(self):
        harness = RetryHarness(max_retries=1)
        result = await harness.run(always_ok, "test")
        assert result.attempts[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_attempt_logs_failure_reason(self):
        harness = RetryHarness(max_retries=1, base_delay_ms=0)
        result = await harness.run(always_fail, "test", validator=validate_non_empty_string)
        assert result.attempts[0].reason is not None
        assert len(result.attempts[0].reason) > 0

    @pytest.mark.asyncio
    async def test_last_failure_reason_property(self):
        harness = RetryHarness(max_retries=2, base_delay_ms=0)
        result = await harness.run(always_fail, "test", validator=validate_non_empty_string)
        assert result.last_failure_reason is not None

    @pytest.mark.asyncio
    async def test_total_latency_measured(self):
        harness = RetryHarness(max_retries=1)
        result = await harness.run(always_ok, "test")
        assert result.total_latency_ms >= 0

    @pytest.mark.asyncio
    async def test_fn_kwargs_passed(self):
        received_kwargs = {}

        async def capture_kwargs(input_: str, extra: str = "", **kwargs) -> str:
            received_kwargs["extra"] = extra
            return "ok narrative from function"

        harness = RetryHarness(max_retries=1)
        await harness.run(capture_kwargs, "test", fn_kwargs={"extra": "value123"})
        assert received_kwargs.get("extra") == "value123"

    @pytest.mark.asyncio
    async def test_max_retries_one_means_no_retry(self):
        harness = RetryHarness(max_retries=1, base_delay_ms=0)
        result = await harness.run(always_fail, "test", validator=validate_non_empty_string)
        assert result.attempt_count == 1

    @pytest.mark.asyncio
    async def test_retry_with_correction_convenience(self):
        result = await retry_with_correction(
            fn=always_ok,
            initial_input="test",
            validator=validate_non_empty_string,
            max_retries=3,
        )
        assert result.success
        assert "OK: test" in result.value
