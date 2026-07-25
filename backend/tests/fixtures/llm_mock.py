"""
Harness Engineering — LLM Mock Fixtures

Provides deterministic, no-API LLM mocks for testing agent pipelines.

Usage in tests:
    from tests.fixtures.llm_mock import MockLLM, patch_llm

    # Option 1: Direct mock
    llm = MockLLM(response="Gelir büyümesi güçlü, riskler kontrol altında.")
    result = await llm.ainvoke("Tell me about finances")
    assert result.content == "Gelir büyümesi güçlü..."

    # Option 2: Context manager patch
    with patch_llm(response="mock narrative"):
        result = await run_pnl(state, config)
        assert result.ok
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


# ── Mock message type ─────────────────────────────────────────────────────────

@dataclass
class MockMessage:
    """Mimics langchain_core.messages.AIMessage interface."""
    content: str

    def __str__(self) -> str:
        return self.content


# ── MockLLM ───────────────────────────────────────────────────────────────────

class MockLLM:
    """
    Drop-in replacement for LangChain ChatOpenAI.

    Features:
    - Fixed response or response sequence (round-robin)
    - Optional latency simulation
    - Call count tracking for assertions
    - Can raise on demand for error path testing
    """

    def __init__(
        self,
        response: str | list[str] = "Test narrative — mock LLM response.",
        latency_ms: float = 0.0,
        raise_on_call: int | None = None,  # raise on this call number (1-indexed)
        error: Exception | None = None,
    ) -> None:
        self._responses = [response] if isinstance(response, str) else list(response)
        self._latency_ms = latency_ms
        self._raise_on_call = raise_on_call
        self._error = error or RuntimeError("MockLLM: simulated error")
        self.call_count = 0
        self.call_inputs: list[Any] = []

    async def ainvoke(self, input: Any, **kwargs: Any) -> MockMessage:
        self.call_count += 1
        self.call_inputs.append(input)

        if self._raise_on_call is not None and self.call_count == self._raise_on_call:
            raise self._error

        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000)

        # Round-robin through responses
        idx = (self.call_count - 1) % len(self._responses)
        return MockMessage(content=self._responses[idx])

    def invoke(self, input: Any, **kwargs: Any) -> MockMessage:
        """Sync version — wraps ainvoke result."""
        self.call_count += 1
        self.call_inputs.append(input)
        if self._raise_on_call is not None and self.call_count == self._raise_on_call:
            raise self._error
        idx = (self.call_count - 1) % len(self._responses)
        return MockMessage(content=self._responses[idx])

    def reset(self) -> None:
        self.call_count = 0
        self.call_inputs.clear()


# ── Patch helpers ─────────────────────────────────────────────────────────────

@contextmanager
def patch_llm(
    response: str | list[str] = "Mock CFO narrative — dönemi güçlü kapattık.",
    target: str = "langchain_openai.ChatOpenAI",
):
    """
    Context manager that patches ChatOpenAI with MockLLM.

    with patch_llm(response="Güçlü dönem."):
        result = await run_pnl(state, config)
    """
    mock_llm = MockLLM(response=response)
    mock_class = MagicMock(return_value=mock_llm)
    with patch(target, mock_class):
        yield mock_llm


@contextmanager
def patch_settings(
    openai_api_key: str = "sk-test-mock-key-not-real",
    llm_model: str = "gpt-3.5-turbo",
):
    """Patch get_settings() to return a mock settings object."""
    mock_settings = MagicMock()
    mock_settings.openai_api_key = openai_api_key
    mock_settings.llm_model = llm_model
    mock_settings.llm_base_url = ""
    mock_settings.llm_temperature = 0
    mock_settings.llm_max_tokens = 1024

    with patch("app.config.get_settings", return_value=mock_settings):
        yield mock_settings


# ── Sample state builders ─────────────────────────────────────────────────────

def make_sample_transactions(n: int = 20) -> list[dict[str, Any]]:
    """Generate n deterministic sample transactions for testing."""
    import random
    rng = random.Random(42)

    categories = ["revenue", "salary", "rent", "utilities", "marketing", "cogs"]
    vendors = ["Müşteri A", "Müşteri B", "Çalışan Maaşları", "Kira", "Reklam Ajansı", "Tedarikçi"]

    txs = []
    for i in range(n):
        is_income = i % 3 == 0
        txs.append({
            "id": f"tx-{i:04d}",
            "transaction_date": f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
            "type": "income" if is_income else "expense",
            "category": "revenue" if is_income else categories[i % len(categories)],
            "description": f"İşlem {i}",
            "vendor": vendors[i % len(vendors)],
            "amount_cents": rng.randint(10_000, 500_000),
        })
    return txs


def make_sample_pnl() -> dict[str, Any]:
    return {
        "revenue":       480_000_00,
        "cogs":          144_000_00,
        "gross_profit":  336_000_00,
        "gross_margin":  0.70,
        "opex": {
            "salary":    120_000_00,
            "rent":       24_000_00,
            "marketing":  18_000_00,
            "technology":  9_600_00,
            "other_expense": 4_800_00,
        },
        "total_opex":    176_400_00,
        "ebitda":        159_600_00,
        "ebitda_margin": 0.332,
        "net_income":    139_200_00,
        "net_margin":    0.29,
        "narrative":     "",
    }


def make_sample_cashflow() -> dict[str, Any]:
    return {
        "operating":   120_000_00,
        "investing":   -24_000_00,
        "financing":    -6_000_00,
        "net_change":   90_000_00,
        "monthly_series": [
            {"month": f"2024-{m:02d}", "in": 40_000_00, "out": 32_500_00, "net": 7_500_00}
            for m in range(1, 13)
        ],
        "narrative": "",
        "alerts": [],
    }


def make_sample_state(n_transactions: int = 20) -> dict[str, Any]:
    """Build a complete CFOState-compatible dict for pipeline testing."""
    return {
        "job_id":       "test-job-001",
        "file_path":    "/tmp/test.csv",
        "file_type":    "csv",
        "transactions": make_sample_transactions(n_transactions),
        "pnl":          make_sample_pnl(),
        "cashflow":     make_sample_cashflow(),
        "logs":         [],
        "min_confidence": 1.0,
        "awaiting_review": False,
        "halted": False,
        "error": None,
    }
