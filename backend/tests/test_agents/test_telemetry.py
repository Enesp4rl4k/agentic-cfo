"""
Tests for telemetry.py — all tests run without OpenTelemetry installed.
Covers: JSONFormatter, trace_agent decorator, AgentMetrics, helper functions.
"""
import asyncio
import json
import logging
import pytest
from unittest.mock import MagicMock

from app.services.telemetry import (
    JSONFormatter,
    AgentMetrics,
    _NoOpSpan,
    _NoOpTracer,
    get_logger,
    trace_agent,
    initialize_telemetry,
)


# ── JSONFormatter ──────────────────────────────────────────────────────────────

class TestJSONFormatter:

    def setup_method(self):
        self.formatter = JSONFormatter()
        self.logger = logging.getLogger("test.json")

    def _make_record(self, msg: str, level: int = logging.INFO, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_produces_valid_json(self):
        record = self._make_record("Test message")
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_contains_required_fields(self):
        record = self._make_record("Test message")
        parsed = json.loads(self.formatter.format(record))
        for key in ("ts", "level", "logger", "msg"):
            assert key in parsed

    def test_message_preserved(self):
        record = self._make_record("Hello world")
        parsed = json.loads(self.formatter.format(record))
        assert parsed["msg"] == "Hello world"

    def test_level_is_string(self):
        record = self._make_record("msg", level=logging.ERROR)
        parsed = json.loads(self.formatter.format(record))
        assert parsed["level"] == "ERROR"

    def test_extra_fields_included(self):
        record = self._make_record("msg", job_id="abc123", agent="pnl")
        parsed = json.loads(self.formatter.format(record))
        assert parsed.get("job_id") == "abc123"
        assert parsed.get("agent") == "pnl"

    def test_non_serializable_extra_converted_to_str(self):
        record = self._make_record("msg")
        setattr(record, "obj", object())  # non-serializable
        # Should not raise
        output = self.formatter.format(record)
        assert isinstance(output, str)

    def test_reserved_attrs_not_included(self):
        record = self._make_record("msg")
        parsed = json.loads(self.formatter.format(record))
        # These should not appear as top-level fields
        assert "args" not in parsed
        assert "levelno" not in parsed
        assert "pathname" not in parsed

    def test_exception_info_included(self):
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            record = self._make_record("Error occurred", exc_info=sys.exc_info())
            parsed = json.loads(self.formatter.format(record))
            assert "exc" in parsed
            assert "ValueError" in parsed["exc"]

    def test_timestamp_format(self):
        record = self._make_record("msg")
        parsed = json.loads(self.formatter.format(record))
        # Should contain 'T' separator (ISO 8601)
        assert "T" in parsed["ts"]


# ── _NoOpSpan and _NoOpTracer ──────────────────────────────────────────────────

class TestNoOpComponents:

    def test_noop_span_context_manager(self):
        span = _NoOpSpan()
        with span as s:
            assert s is span

    def test_noop_span_methods_no_error(self):
        span = _NoOpSpan()
        span.set_attribute("key", "value")
        span.set_status("ok")
        span.record_exception(Exception("test"))
        span.add_event("event", key="val")

    def test_noop_tracer_returns_noop_span(self):
        tracer = _NoOpTracer()
        ctx = tracer.start_as_current_span("test_op")
        assert isinstance(ctx, _NoOpSpan)


# ── trace_agent decorator ──────────────────────────────────────────────────────

class TestTraceAgentDecorator:

    def test_decorator_preserves_function_name(self):
        @trace_agent("test_agent")
        async def my_run(state, config):
            pass
        assert my_run.__name__ == "my_run"

    def test_decorator_preserves_docstring(self):
        @trace_agent("test_agent")
        async def my_run(state, config):
            """My docstring."""
            pass
        assert my_run.__doc__ == "My docstring."

    def test_decorated_function_runs(self):
        from app.agents.state import SkillResult

        @trace_agent("test_agent")
        async def my_run(state, config):
            return SkillResult(ok=True, detail="done")

        result = asyncio.run(my_run({"job_id": "test-123"}, None))
        assert result.ok is True

    def test_decorated_function_passes_args(self):
        called_with = []

        @trace_agent("test_agent")
        async def my_run(state, config):
            called_with.append(state)
            from app.agents.state import SkillResult
            return SkillResult(ok=True)

        asyncio.run(my_run({"job_id": "abc"}, None))
        assert called_with[0]["job_id"] == "abc"

    def test_exception_propagates(self):
        @trace_agent("error_agent")
        async def failing_run(state, config):
            raise RuntimeError("Intentional failure")

        with pytest.raises(RuntimeError, match="Intentional failure"):
            asyncio.run(failing_run({}, None))

    def test_empty_state_does_not_crash(self):
        from app.agents.state import SkillResult

        @trace_agent("test_agent")
        async def my_run(state, config):
            return SkillResult(ok=True)

        # Empty state — should not crash
        result = asyncio.run(my_run({}, None))
        assert result.ok is True

    def test_non_dict_state_does_not_crash(self):
        from app.agents.state import SkillResult

        @trace_agent("test_agent")
        async def my_run(state, config):
            return SkillResult(ok=True)

        # Non-dict state
        result = asyncio.run(my_run(None, None))
        assert result.ok is True


# ── AgentMetrics ──────────────────────────────────────────────────────────────

class TestAgentMetrics:

    def setup_method(self):
        # Clear metrics between tests
        AgentMetrics._runs.clear()

    def test_record_stores_run(self):
        AgentMetrics.record("pnl_agent", "job-1", 142.5, ok=True, confidence=0.95)
        assert "pnl_agent" in AgentMetrics._runs
        assert len(AgentMetrics._runs["pnl_agent"]) == 1

    def test_summary_returns_correct_total(self):
        AgentMetrics.record("pnl_agent", "job-1", 100.0, ok=True)
        AgentMetrics.record("pnl_agent", "job-2", 200.0, ok=True)
        AgentMetrics.record("pnl_agent", "job-3", 150.0, ok=False)
        summary = AgentMetrics.summary("pnl_agent")
        assert summary["pnl_agent"]["total_runs"] == 3

    def test_success_rate_calculated(self):
        AgentMetrics.record("cf_agent", "j1", 100, ok=True)
        AgentMetrics.record("cf_agent", "j2", 100, ok=True)
        AgentMetrics.record("cf_agent", "j3", 100, ok=False)
        summary = AgentMetrics.summary("cf_agent")
        assert summary["cf_agent"]["success_rate"] == pytest.approx(2/3, abs=0.01)

    def test_avg_duration_calculated(self):
        AgentMetrics.record("fc_agent", "j1", 100.0, ok=True)
        AgentMetrics.record("fc_agent", "j2", 200.0, ok=True)
        summary = AgentMetrics.summary("fc_agent")
        assert summary["fc_agent"]["avg_duration_ms"] == pytest.approx(150.0)

    def test_avg_confidence_calculated(self):
        AgentMetrics.record("pnl_agent", "j1", 100, ok=True, confidence=0.90)
        AgentMetrics.record("pnl_agent", "j2", 100, ok=True, confidence=0.80)
        summary = AgentMetrics.summary("pnl_agent")
        assert summary["pnl_agent"]["avg_confidence"] == pytest.approx(0.85)

    def test_no_confidence_returns_none(self):
        AgentMetrics.record("pnl_agent", "j1", 100, ok=True)
        summary = AgentMetrics.summary("pnl_agent")
        assert summary["pnl_agent"]["avg_confidence"] is None

    def test_all_agents_summary(self):
        AgentMetrics.record("agent_a", "j1", 100, ok=True)
        AgentMetrics.record("agent_b", "j1", 200, ok=False)
        summary = AgentMetrics.summary()
        assert "agent_a" in summary
        assert "agent_b" in summary

    def test_unknown_agent_returns_empty(self):
        summary = AgentMetrics.summary("nonexistent_agent")
        assert summary == {}

    def test_caps_at_1000_runs(self):
        for i in range(1005):
            AgentMetrics.record("busy_agent", f"j{i}", 100, ok=True)
        assert len(AgentMetrics._runs["busy_agent"]) <= 1000


# ── get_logger ────────────────────────────────────────────────────────────────

def test_get_logger_returns_logger():
    logger = get_logger("test.module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test.module"


# ── initialize_telemetry ──────────────────────────────────────────────────────

def test_initialize_telemetry_no_crash():
    """initialize_telemetry should not raise even with no OTEL packages."""
    # Call twice to test idempotency (second call is a no-op due to handler check)
    initialize_telemetry(log_level="WARNING", json_logs=False)
    initialize_telemetry(log_level="INFO", json_logs=False)
