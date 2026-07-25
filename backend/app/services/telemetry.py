"""
Telemetry Service — OpenTelemetry + Structured Logging
=======================================================

Provides:
  1. OpenTelemetry tracing (spans for every agent run + API request)
  2. JSON-structured logging (machine-readable, Datadog/CloudWatch friendly)
  3. Agent performance metrics (latency, confidence, token count)
  4. LangSmith integration (optional, for LLM call tracing)

Architecture:
  - Zero-dependency core: falls back gracefully if otel packages not installed
  - All spans are no-ops when tracing is disabled (production opt-in)
  - Structured logs always work — no external service needed

Configuration (via .env):
  OTEL_ENABLED=true               # Enable OpenTelemetry tracing (default: false)
  OTEL_EXPORTER=console           # "console" | "otlp" | "jaeger"
  OTEL_ENDPOINT=http://localhost:4317  # OTLP gRPC endpoint
  LANGSMITH_ENABLED=true          # Enable LangSmith LLM tracing (default: false)
  LANGSMITH_API_KEY=ls-...        # LangSmith API key
  LANGSMITH_PROJECT=aicfo-prod    # LangSmith project name

Usage:
    from app.services.telemetry import tracer, trace_agent, get_logger

    # Structured logger
    logger = get_logger(__name__)
    logger.info("Agent started", extra={"job_id": "abc", "agent": "pnl"})

    # Manual span
    with tracer.start_as_current_span("custom_operation") as span:
        span.set_attribute("job_id", job_id)
        result = do_work()

    # Decorator
    @trace_agent("pnl_agent")
    async def run_pnl(state, config):
        ...
"""
from __future__ import annotations

import functools
import json
import logging
import os
import time
from typing import Any, Callable

# ── Structured JSON Log Formatter ─────────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.
    Includes: timestamp, level, logger, message, extra fields.

    Output example:
    {"ts":"2024-03-15T10:23:45.123Z","level":"INFO","logger":"app.agents.pnl","msg":"P&L computed","job_id":"abc123","duration_ms":142}
    """

    RESERVED_ATTRS = frozenset({
        "args", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message",
        "module", "msecs", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:
        log: dict[str, Any] = {
            "ts":     self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{record.msecs:03.0f}Z",
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }

        # Add extra fields (job_id, agent, duration_ms, etc.)
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                try:
                    json.dumps(value)   # Only include JSON-serializable values
                    log[key] = value
                except (TypeError, ValueError):
                    log[key] = str(value)

        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)

        return json.dumps(log, ensure_ascii=False)


def setup_json_logging(level: str = "INFO") -> None:
    """Configure root logger to output JSON to stdout."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g., in tests)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Use instead of logging.getLogger() for consistent config."""
    return logging.getLogger(name)


# ── OpenTelemetry Setup ───────────────────────────────────────────────────────

_tracer = None
_otel_available = False


def _setup_otel() -> None:
    """Initialize OpenTelemetry tracing if packages are installed and OTEL_ENABLED=true."""
    global _tracer, _otel_available

    if os.getenv("OTEL_ENABLED", "false").lower() != "true":
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME

        resource = Resource(attributes={
            SERVICE_NAME: "aicfo-backend",
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("APP_ENV", "development"),
        })

        provider = TracerProvider(resource=resource)

        exporter_type = os.getenv("OTEL_EXPORTER", "console").lower()
        if exporter_type == "console":
            exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(exporter))
        elif exporter_type == "otlp":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                endpoint = os.getenv("OTEL_ENDPOINT", "http://localhost:4317")
                exporter = OTLPSpanExporter(endpoint=endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except ImportError:
                logging.getLogger(__name__).warning(
                    "OTLP exporter requested but opentelemetry-exporter-otlp not installed. "
                    "Run: pip install opentelemetry-exporter-otlp-proto-grpc"
                )
        elif exporter_type == "jaeger":
            try:
                from opentelemetry.exporter.jaeger.thrift import JaegerExporter
                exporter = JaegerExporter(
                    agent_host_name=os.getenv("JAEGER_HOST", "localhost"),
                    agent_port=int(os.getenv("JAEGER_PORT", "6831")),
                )
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except ImportError:
                logging.getLogger(__name__).warning(
                    "Jaeger exporter not installed. Run: pip install opentelemetry-exporter-jaeger"
                )

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("aicfo")
        _otel_available = True
        logging.getLogger(__name__).info("OpenTelemetry tracing enabled", extra={"exporter": exporter_type})

    except ImportError:
        logging.getLogger(__name__).info(
            "OpenTelemetry not installed — tracing disabled. "
            "Install: pip install opentelemetry-sdk opentelemetry-api"
        )


class _NoOpSpan:
    """No-op span context manager — used when tracing is disabled."""
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def set_attribute(self, *_): pass
    def set_status(self, *_): pass
    def record_exception(self, *_): pass
    def add_event(self, *_, **__): pass


class _NoOpTracer:
    """No-op tracer — used when OpenTelemetry is not available."""
    def start_as_current_span(self, name: str, **kwargs):
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs):
        return _NoOpSpan()


def _get_tracer():
    """Get the tracer (real or no-op)."""
    if _tracer is not None:
        return _tracer
    return _NoOpTracer()


# Export `tracer` for direct use
tracer = _get_tracer()


# ── Agent Trace Decorator ─────────────────────────────────────────────────────

def trace_agent(agent_name: str) -> Callable:
    """
    Decorator that wraps an agent run function with OpenTelemetry spans + structured logging.

    Automatically records:
    - Agent name, job_id
    - Duration in milliseconds
    - Confidence score (from SkillResult)
    - Success / failure status
    - Any exceptions

    Usage:
        @trace_agent("pnl_agent")
        async def run_pnl(state: CFOState, config: AgentRunConfig) -> SkillResult:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            _tracer = _get_tracer()
            logger = get_logger(f"app.agents.{agent_name}")

            # Extract job_id from state (first positional arg)
            state = args[0] if args else {}
            job_id = state.get("job_id", "unknown") if isinstance(state, dict) else "unknown"

            start_ms = time.monotonic() * 1000

            with _tracer.start_as_current_span(f"agent.{agent_name}") as span:
                span.set_attribute("agent.name", agent_name)
                span.set_attribute("job.id", job_id)

                logger.info(
                    f"Agent started: {agent_name}",
                    extra={"agent": agent_name, "job_id": job_id, "event": "agent.start"}
                )

                try:
                    result = await func(*args, **kwargs)
                    duration_ms = round(time.monotonic() * 1000 - start_ms)

                    # Extract confidence from SkillResult
                    confidence = getattr(result, "confidence", None)
                    ok = getattr(result, "ok", True)
                    detail = getattr(result, "detail", "")

                    span.set_attribute("agent.ok", ok)
                    span.set_attribute("agent.duration_ms", duration_ms)
                    if confidence is not None:
                        span.set_attribute("agent.confidence", confidence)

                    logger.info(
                        f"Agent completed: {agent_name}",
                        extra={
                            "agent": agent_name,
                            "job_id": job_id,
                            "ok": ok,
                            "duration_ms": duration_ms,
                            "confidence": confidence,
                            "detail": detail,
                            "event": "agent.complete",
                        }
                    )
                    return result

                except Exception as exc:
                    duration_ms = round(time.monotonic() * 1000 - start_ms)
                    span.record_exception(exc)

                    try:
                        from opentelemetry.trace import Status, StatusCode
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                    except ImportError:
                        pass

                    logger.error(
                        f"Agent failed: {agent_name}",
                        extra={
                            "agent": agent_name,
                            "job_id": job_id,
                            "error": str(exc),
                            "duration_ms": duration_ms,
                            "event": "agent.error",
                        },
                        exc_info=True,
                    )
                    raise

        return async_wrapper
    return decorator


# ── LangSmith Integration ─────────────────────────────────────────────────────

def setup_langsmith() -> bool:
    """
    Configure LangSmith tracing if LANGSMITH_ENABLED=true.
    Returns True if successfully configured, False otherwise.

    LangSmith traces every LLM call with:
    - Input/output messages
    - Token counts and costs
    - Latency per call
    - Error rates
    """
    if os.getenv("LANGSMITH_ENABLED", "false").lower() != "true":
        return False

    api_key = os.getenv("LANGSMITH_API_KEY", "")
    project = os.getenv("LANGSMITH_PROJECT", "aicfo")

    if not api_key:
        logging.getLogger(__name__).warning(
            "LANGSMITH_ENABLED=true but LANGSMITH_API_KEY not set"
        )
        return False

    try:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ["LANGCHAIN_PROJECT"] = project
        os.environ["LANGCHAIN_ENDPOINT"] = os.getenv(
            "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
        )

        logging.getLogger(__name__).info(
            "LangSmith tracing enabled",
            extra={"project": project, "event": "langsmith.configured"}
        )
        return True

    except Exception as exc:
        logging.getLogger(__name__).warning(
            f"LangSmith setup failed: {exc}",
            extra={"event": "langsmith.error"}
        )
        return False


# ── Metrics helpers ───────────────────────────────────────────────────────────

class AgentMetrics:
    """
    Simple in-memory metrics collector for agent performance.
    Exported to logs on each run — no external service needed.

    In production: replace with Prometheus or Datadog metrics.
    """

    _runs: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def record(
        cls,
        agent_name: str,
        job_id: str,
        duration_ms: float,
        ok: bool,
        confidence: float | None = None,
    ) -> None:
        if agent_name not in cls._runs:
            cls._runs[agent_name] = []
        cls._runs[agent_name].append({
            "job_id": job_id,
            "duration_ms": duration_ms,
            "ok": ok,
            "confidence": confidence,
            "ts": time.time(),
        })
        # Keep last 1000 runs per agent
        if len(cls._runs[agent_name]) > 1000:
            cls._runs[agent_name] = cls._runs[agent_name][-1000:]

    @classmethod
    def summary(cls, agent_name: str | None = None) -> dict[str, Any]:
        """Return performance summary for one or all agents."""
        agents = [agent_name] if agent_name else list(cls._runs.keys())
        result = {}
        for name in agents:
            runs = cls._runs.get(name, [])
            if not runs:
                continue
            durations = [r["duration_ms"] for r in runs]
            success_rate = sum(1 for r in runs if r["ok"]) / len(runs)
            confidences = [r["confidence"] for r in runs if r.get("confidence") is not None]
            result[name] = {
                "total_runs": len(runs),
                "success_rate": round(success_rate, 3),
                "avg_duration_ms": round(sum(durations) / len(durations), 1),
                "p95_duration_ms": round(sorted(durations)[int(len(durations) * 0.95)], 1),
                "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
            }
        return result


# ── Initialization ────────────────────────────────────────────────────────────

def initialize_telemetry(log_level: str = "INFO", json_logs: bool = True) -> None:
    """
    Initialize all telemetry components.
    Call once at application startup.

    Args:
        log_level: Python log level (DEBUG, INFO, WARNING, ERROR)
        json_logs: If True, format logs as JSON (default: True in production)
    """
    if json_logs:
        setup_json_logging(log_level)
    else:
        logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    _setup_otel()
    setup_langsmith()

    logger = get_logger(__name__)
    logger.info(
        "Telemetry initialized",
        extra={
            "otel_enabled": _otel_available,
            "langsmith_enabled": os.getenv("LANGSMITH_ENABLED", "false").lower() == "true",
            "log_format": "json" if json_logs else "text",
            "event": "telemetry.init",
        }
    )
