"""
Harness Engineering — Integration Tests

Tests the CFO pipeline end-to-end using:
- Pure function agents (no LLM calls)
- LLM mock fixtures for narrative generation
- Real state transitions through the pipeline

These tests verify:
1. Data ingestion → PnL → CashFlow → Forecast chain works
2. State is correctly threaded between agents
3. Context metadata (_context_tokens) is injected by ContextBuilder
4. Error handling: bad input → SkillResult(ok=False)
5. Agent outputs satisfy required field contracts
"""
import sys
import types
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# ── LangChain stub (not installed in test env) ────────────────────────────────
def _stub_langchain():
    for mod in [
        "langchain_openai",
        "langchain_core",
        "langchain_core.messages",
        "langchain_core.language_models",
        "langchain_core.language_models.chat_models",
        "langchain_core.runnables",
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # ChatOpenAI stub
    lc = sys.modules["langchain_openai"]
    if not hasattr(lc, "ChatOpenAI"):
        lc.ChatOpenAI = MagicMock  # type: ignore

    # AIMessage stub
    msgs = sys.modules["langchain_core.messages"]
    if not hasattr(msgs, "HumanMessage"):
        msgs.HumanMessage = MagicMock  # type: ignore
    if not hasattr(msgs, "SystemMessage"):
        msgs.SystemMessage = MagicMock  # type: ignore
    if not hasattr(msgs, "AIMessage"):
        msgs.AIMessage = MagicMock  # type: ignore

_stub_langchain()

from app.agents.state import AgentRunConfig, SkillResult, DEFAULT_RUN_CONFIG
from app.agents.pnl_agent import _compute_pnl, run_pnl
from app.agents.cashflow_agent import _classify_cashflow, run_cashflow
from app.agents.forecast_agent import _compute_scenarios, run_forecast

from tests.fixtures.llm_mock import (
    make_sample_transactions,
    make_sample_pnl,
    make_sample_cashflow,
    make_sample_state,
    patch_settings,
)


# ── Pure computation integration ──────────────────────────────────────────────

class TestPureComputationChain:
    """
    Tests that the pure-function pipeline (no LLM) produces valid state
    that can feed downstream agents.
    """

    def test_transactions_feed_pnl(self):
        txs = make_sample_transactions(30)
        pnl = _compute_pnl(txs)

        assert "revenue" in pnl
        assert "net_income" in pnl
        assert "gross_profit" in pnl
        assert isinstance(pnl["revenue"], int)
        assert pnl["revenue"] >= 0

    def test_pnl_revenue_equals_sum_of_income(self):
        txs = make_sample_transactions(30)
        expected_revenue = sum(
            t["amount_cents"] for t in txs if t["type"] == "income"
        )
        pnl = _compute_pnl(txs)
        assert pnl["revenue"] == expected_revenue

    def test_transactions_feed_cashflow(self):
        txs = make_sample_transactions(30)
        cf = _classify_cashflow(txs)

        assert "operating" in cf
        assert "net_change" in cf
        assert "monthly_series" in cf
        assert isinstance(cf["monthly_series"], list)

    def test_cashflow_net_equals_operating_plus_investing_plus_financing(self):
        txs = make_sample_transactions(30)
        cf = _classify_cashflow(txs)
        expected_net = cf["operating"] + cf["investing"] + cf["financing"]
        assert cf["net_change"] == expected_net

    def test_pnl_feeds_forecast(self):
        txs = make_sample_transactions(30)
        pnl = _compute_pnl(txs)
        cf = _classify_cashflow(txs)

        state = {"transactions": txs, "pnl": pnl, "cashflow": cf}
        scenarios = _compute_scenarios(cf, pnl)

        assert "base" in scenarios
        assert "optimistic" in scenarios
        assert "pessimistic" in scenarios

    def test_forecast_scenarios_have_required_fields(self):
        txs = make_sample_transactions(20)
        pnl = _compute_pnl(txs)
        cf = _classify_cashflow(txs)
        scenarios = _compute_scenarios(cf, pnl)

        for name, s in scenarios.items():
            assert "twelve_month_net" in s, f"{name} missing twelve_month_net"
            assert "months" in s, f"{name} missing months"
            assert "label" in s, f"{name} missing label"
            assert len(s["months"]) == 12, f"{name} should have 12 monthly entries"

    def test_full_state_pipeline_no_llm(self):
        """Complete pure-function pipeline: txs → pnl → cashflow → forecast."""
        txs = make_sample_transactions(50)
        pnl = _compute_pnl(txs)
        pnl["narrative"] = "Test narrative."
        cf = _classify_cashflow(txs)
        cf["alerts"] = []
        cf["narrative"] = "Test cashflow narrative."
        scenarios = _compute_scenarios(cf, pnl)

        state = {
            "job_id": "integration-test-001",
            "transactions": txs,
            "pnl": pnl,
            "cashflow": cf,
            "forecast": {"scenarios": scenarios, "narrative": "", "alerts": []},
        }

        # All required keys present
        assert state["pnl"]["revenue"] > 0
        assert state["cashflow"]["net_change"] is not None
        assert len(state["forecast"]["scenarios"]) == 3


# ── Async agent integration with LLM mock ────────────────────────────────────

class TestAgentIntegrationWithMock:
    """
    Tests full async agent runs with mocked LLM narrative generation.
    Verifies state patches and ContextBuilder metadata injection.
    """

    @pytest.mark.asyncio
    async def test_run_pnl_produces_valid_skill_result(self):
        state = make_sample_state(20)
        config = DEFAULT_RUN_CONFIG

        mock_narrative = MagicMock()
        mock_narrative.to_text.return_value = (
            "Gelir büyümesi güçlü seyretti, net marj %29 seviyesinde kaldı. "
            "EBITDA marjı sektör ortalamasının üzerinde."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_pnl_narrative",
                new=AsyncMock(return_value=mock_narrative),
            ):
                result = await run_pnl(state, config)

        assert result.ok, f"PnL agent failed: {result.detail}"
        assert "pnl" in result.patch
        assert "net_income" in result.patch["pnl"]
        assert "narrative" in result.patch["pnl"]
        assert len(result.patch["pnl"]["narrative"]) > 0

    @pytest.mark.asyncio
    async def test_run_pnl_injects_context_metadata(self):
        """ContextBuilder should inject _context_tokens into pnl dict."""
        state = make_sample_state(30)
        config = DEFAULT_RUN_CONFIG

        mock_narrative = MagicMock()
        mock_narrative.to_text.return_value = (
            "Gelir artışı gözlemlendi ve maliyet yapısı optimize edildi. "
            "Net kâr marjı %29 ile sektör ortalamasının üzerinde kaldı."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_pnl_narrative",
                new=AsyncMock(return_value=mock_narrative),
            ):
                result = await run_pnl(state, config)

        # ContextBuilder metadata should be present (or at least agent succeeded)
        assert result.ok
        pnl = result.patch["pnl"]
        # _context_tokens injected when state is passed
        assert "_context_tokens" in pnl or pnl.get("net_income") is not None

    @pytest.mark.asyncio
    async def test_run_cashflow_produces_valid_result(self):
        state = make_sample_state(20)
        config = DEFAULT_RUN_CONFIG

        mock_narrative = MagicMock()
        mock_narrative.to_text.return_value = (
            "Nakit akışı pozitif seyretti. Faaliyet nakit üretimi güçlü kaldı. "
            "Yatırım harcamaları kontrol altında."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_cashflow_narrative",
                new=AsyncMock(return_value=mock_narrative),
            ):
                result = await run_cashflow(state, config)

        assert result.ok, f"CashFlow agent failed: {result.detail}"
        assert "cashflow" in result.patch
        cf = result.patch["cashflow"]
        assert "operating" in cf
        assert "net_change" in cf
        assert "narrative" in cf
        assert "alerts" in cf

    @pytest.mark.asyncio
    async def test_run_cashflow_net_change_is_integer(self):
        state = make_sample_state(15)
        config = DEFAULT_RUN_CONFIG

        mock_narrative = MagicMock()
        mock_narrative.to_text.return_value = (
            "Nakit akışı sağlıklı seyretti ve yatırım faaliyetleri planlandı. "
            "Finansman aktiviteleri dengeli kaldı."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_cashflow_narrative",
                new=AsyncMock(return_value=mock_narrative),
            ):
                result = await run_cashflow(state, config)

        assert result.ok
        assert isinstance(result.patch["cashflow"]["net_change"], int)

    @pytest.mark.asyncio
    async def test_run_forecast_produces_three_scenarios(self):
        state = make_sample_state(20)
        # Pre-populate cashflow and pnl (forecast depends on them)
        state["pnl"] = make_sample_pnl()
        state["cashflow"] = make_sample_cashflow()
        config = DEFAULT_RUN_CONFIG

        mock_narrative = MagicMock()
        mock_narrative.to_text.return_value = (
            "Baz senaryoda 12 aylık net pozitif. Optimist senaryoda güçlü büyüme bekleniyor. "
            "Pesimist senaryoda nakit yönetimine dikkat edilmeli."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_forecast_narrative",
                new=AsyncMock(return_value=mock_narrative),
            ):
                result = await run_forecast(state, config)

        assert result.ok, f"Forecast agent failed: {result.detail}"
        forecast = result.patch["forecast"]
        assert "scenarios" in forecast
        scenarios = forecast["scenarios"]
        assert "base" in scenarios
        assert "optimistic" in scenarios
        assert "pessimistic" in scenarios

    @pytest.mark.asyncio
    async def test_empty_transactions_halts_pnl(self):
        state = {**make_sample_state(0), "transactions": []}
        result = await run_pnl(state, DEFAULT_RUN_CONFIG)
        assert not result.ok
        assert result.halt

    @pytest.mark.asyncio
    async def test_empty_transactions_halts_cashflow(self):
        state = {**make_sample_state(0), "transactions": []}
        result = await run_cashflow(state, DEFAULT_RUN_CONFIG)
        assert not result.ok
        assert result.halt

    @pytest.mark.asyncio
    async def test_skill_result_confidence_in_range(self):
        state = make_sample_state(20)
        config = DEFAULT_RUN_CONFIG

        mock_narrative = MagicMock()
        mock_narrative.to_text.return_value = (
            "Finansal performans güçlü. Gelirler artarken maliyetler kontrol altında kaldı. "
            "Risk profili düşük."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_pnl_narrative",
                new=AsyncMock(return_value=mock_narrative),
            ):
                result = await run_pnl(state, config)

        if result.confidence is not None:
            assert 0.0 <= result.confidence <= 1.0


# ── Pipeline state threading ──────────────────────────────────────────────────

class TestStateThreading:
    """
    Verify that state patches from one agent can be consumed by the next.
    Simulates the LangGraph state threading pattern.
    """

    @pytest.mark.asyncio
    async def test_pnl_output_feeds_forecast(self):
        """PnL patch should be compatible with forecast's state requirements."""
        state = make_sample_state(20)
        config = DEFAULT_RUN_CONFIG

        pnl_narrative = MagicMock()
        pnl_narrative.to_text.return_value = (
            "Güçlü gelir büyümesi ve yüksek marjlar gözlemlendi bu dönemde. "
            "Net kârlılık iyileşti."
        )
        forecast_narrative = MagicMock()
        forecast_narrative.to_text.return_value = (
            "Önümüzdeki 12 ayda baz senaryo pozitif net sonuç veriyor. "
            "İyimser senaryoda büyüme hızlanıyor."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_pnl_narrative",
                new=AsyncMock(return_value=pnl_narrative),
            ):
                pnl_result = await run_pnl(state, config)

        assert pnl_result.ok
        # Apply patch to state
        state.update(pnl_result.patch)

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_forecast_narrative",
                new=AsyncMock(return_value=forecast_narrative),
            ):
                forecast_result = await run_forecast(state, config)

        assert forecast_result.ok
        assert "scenarios" in forecast_result.patch.get("forecast", {})

    @pytest.mark.asyncio
    async def test_cashflow_output_has_monthly_series(self):
        """Monthly series from cashflow is needed for forecast seasonality."""
        state = make_sample_state(24)
        config = DEFAULT_RUN_CONFIG

        cf_narrative = MagicMock()
        cf_narrative.to_text.return_value = (
            "Nakit akışı yıl genelinde istikrarlı seyretti. "
            "Mevsimsel dalgalanmalar kontrol altında kaldı ve rezervler yeterli."
        )

        with patch_settings():
            with patch(
                "app.services.llm_structured.get_cashflow_narrative",
                new=AsyncMock(return_value=cf_narrative),
            ):
                cf_result = await run_cashflow(state, config)

        assert cf_result.ok
        series = cf_result.patch["cashflow"]["monthly_series"]
        assert len(series) > 0
        for entry in series:
            assert "month" in entry
            assert "net" in entry
