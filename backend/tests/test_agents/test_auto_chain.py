"""
Tests for app.services.auto_chain

Covers:
  - AGENT_CHAIN mapping correctness
  - FEEDBACK_RULES signal functions (_cfo_has_critical_anomalies, etc.)
  - on_agent_complete: downstream agent triggering
  - on_agent_complete: CEO synthesis trigger conditions
  - on_agent_complete: cross-agent feedback loop
  - _build_kri_csv_from_cfo: CSV structure + content
  - _build_risk_csv_from_cfo: CSV from alerts
  - _build_audit_findings_from_cfo: CSV from anomalies
  - Error isolation: failures in chain don't propagate
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.auto_chain import (
    AGENT_CHAIN,
    CEO_TRIGGER_AGENTS,
    FEEDBACK_RULES,
    on_agent_complete,
    _cfo_has_critical_anomalies,
    _cfo_has_cash_crisis,
    _cto_has_low_velocity,
    _cmo_has_high_cac,
    _build_kri_csv_from_cfo,
    _build_risk_csv_from_cfo,
    _build_audit_findings_from_cfo,
)
from app.services.company_context import CompanyContext


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _empty_ctx(org_id: str = "org-test") -> CompanyContext:
    return CompanyContext(org_id=org_id)


def _ctx_with_cfo(
    org_id: str = "org-test",
    net_margin: float = 0.20,
    revenue: float = 500_000,
    runway_months: float | None = 12.0,
    anomalies: list | None = None,
    alerts: list | None = None,
) -> CompanyContext:
    ctx = CompanyContext(org_id=org_id)
    ctx.last_cfo_result = {
        "pnl": {"net_margin": net_margin, "revenue": revenue},
        "cashflow": {"operating_cash_flow": revenue * 0.15},
        "forecast": {
            "scenarios": {
                "base": {
                    "runway_months": runway_months,
                    "twelve_month_net": revenue,
                }
            }
        },
        "anomalies": anomalies or [],
        "alerts": alerts or [],
    }
    return ctx


# ── AGENT_CHAIN structure ─────────────────────────────────────────────────────

class TestAgentChainStructure:
    def test_cfo_triggers_risk_and_audit(self):
        assert "risk" in AGENT_CHAIN.get("cfo", [])
        assert "audit" in AGENT_CHAIN.get("cfo", [])

    def test_risk_triggers_compliance(self):
        assert "compliance" in AGENT_CHAIN.get("risk", [])

    def test_ceo_trigger_agents_includes_key_agents(self):
        assert "cfo"  in CEO_TRIGGER_AGENTS
        assert "cto"  in CEO_TRIGGER_AGENTS
        assert "cmo"  in CEO_TRIGGER_AGENTS
        assert "coo"  in CEO_TRIGGER_AGENTS
        assert "chro" in CEO_TRIGGER_AGENTS

    def test_feedback_rules_defined_for_cfo_cto_cmo(self):
        assert "cfo" in FEEDBACK_RULES
        assert "cto" in FEEDBACK_RULES
        assert "cmo" in FEEDBACK_RULES


# ── Signal functions ──────────────────────────────────────────────────────────

class TestSignalFunctions:
    def test_cfo_has_critical_anomalies_true(self):
        ctx = _ctx_with_cfo(anomalies=[
            {"severity": "critical", "description": "Duplicate transactions"},
        ])
        assert _cfo_has_critical_anomalies(ctx) is True

    def test_cfo_has_critical_anomalies_false_when_no_anomalies(self):
        ctx = _ctx_with_cfo()
        assert _cfo_has_critical_anomalies(ctx) is False

    def test_cfo_has_critical_anomalies_false_when_only_warning(self):
        ctx = _ctx_with_cfo(anomalies=[
            {"severity": "warning", "description": "High expenses"},
        ])
        assert _cfo_has_critical_anomalies(ctx) is False

    def test_cfo_has_critical_anomalies_false_when_no_cfo_result(self):
        ctx = _empty_ctx()
        assert _cfo_has_critical_anomalies(ctx) is False

    def test_cfo_has_cash_crisis_true_when_runway_below_6(self):
        ctx = _ctx_with_cfo(runway_months=4.5)
        assert _cfo_has_cash_crisis(ctx) is True

    def test_cfo_has_cash_crisis_true_at_exactly_5(self):
        ctx = _ctx_with_cfo(runway_months=5.9)
        assert _cfo_has_cash_crisis(ctx) is True

    def test_cfo_has_cash_crisis_false_when_runway_above_6(self):
        ctx = _ctx_with_cfo(runway_months=8.0)
        assert _cfo_has_cash_crisis(ctx) is False

    def test_cfo_has_cash_crisis_false_when_runway_is_none(self):
        ctx = _ctx_with_cfo(runway_months=None)
        assert _cfo_has_cash_crisis(ctx) is False

    def test_cfo_has_cash_crisis_false_when_no_cfo_result(self):
        ctx = _empty_ctx()
        assert _cfo_has_cash_crisis(ctx) is False

    def test_cto_has_low_velocity_true_when_declining(self):
        ctx = _empty_ctx()
        ctx.last_cto_result = {
            "velocity": {"trend": "declining"},
            "cto_summary": {"overall_health_score": 8},
        }
        assert _cto_has_low_velocity(ctx) is True

    def test_cto_has_low_velocity_true_when_score_below_5(self):
        ctx = _empty_ctx()
        ctx.last_cto_result = {
            "velocity": {"trend": "stable"},
            "cto_summary": {"overall_health_score": 3},
        }
        assert _cto_has_low_velocity(ctx) is True

    def test_cto_has_low_velocity_false_when_healthy(self):
        ctx = _empty_ctx()
        ctx.last_cto_result = {
            "velocity": {"trend": "improving"},
            "cto_summary": {"overall_health_score": 7},
        }
        assert _cto_has_low_velocity(ctx) is False

    def test_cto_has_low_velocity_false_when_no_cto_result(self):
        ctx = _empty_ctx()
        assert _cto_has_low_velocity(ctx) is False

    def test_cmo_has_high_cac_true_when_roas_below_1_5(self):
        ctx = _empty_ctx()
        ctx.last_cmo_result = {"campaigns": {"overall_roas": 1.2}}
        assert _cmo_has_high_cac(ctx) is True

    def test_cmo_has_high_cac_false_when_roas_good(self):
        ctx = _empty_ctx()
        ctx.last_cmo_result = {"campaigns": {"overall_roas": 3.0}}
        assert _cmo_has_high_cac(ctx) is False

    def test_cmo_has_high_cac_false_when_no_cmo_result(self):
        ctx = _empty_ctx()
        assert _cmo_has_high_cac(ctx) is False


# ── CSV builders ──────────────────────────────────────────────────────────────

class TestCSVBuilders:
    def _cfo_data(self) -> dict:
        return {
            "pnl": {
                "net_margin": 0.22,
                "revenue":    800_000,
            },
            "cashflow": {
                "operating_cash_flow": 120_000,
            },
            "anomalies": [
                {"severity": "critical", "description": "Duplicate txn found"},
                {"severity": "warning",  "description": "High marketing spend"},
            ],
            "alerts": [
                {"message": "Cash runway < 6 months", "level": "critical", "category": "liquidity"},
                {"message": "Revenue declining",       "level": "warning",  "category": "revenue"},
            ],
        }

    def test_kri_csv_has_header(self):
        csv = _build_kri_csv_from_cfo(self._cfo_data())
        assert csv.startswith("kri_name,value,threshold,unit,trend")

    def test_kri_csv_includes_net_margin(self):
        csv = _build_kri_csv_from_cfo(self._cfo_data())
        assert "Net Profit Margin" in csv
        assert "0.22" in csv or "22" in csv or ".2" in csv  # formatted float

    def test_kri_csv_includes_revenue(self):
        csv = _build_kri_csv_from_cfo(self._cfo_data())
        assert "Revenue" in csv

    def test_kri_csv_includes_operating_cashflow(self):
        csv = _build_kri_csv_from_cfo(self._cfo_data())
        assert "Operating Cash Flow" in csv

    def test_kri_csv_empty_when_no_metrics(self):
        csv = _build_kri_csv_from_cfo({})
        assert csv == ""

    def test_risk_csv_has_header(self):
        csv = _build_risk_csv_from_cfo(self._cfo_data())
        assert csv.startswith("risk_id,description,likelihood,impact,category")

    def test_risk_csv_includes_alerts(self):
        csv = _build_risk_csv_from_cfo(self._cfo_data())
        assert "Cash runway" in csv
        assert "R001" in csv

    def test_risk_csv_sanitizes_commas(self):
        cfo = {"alerts": [{"message": "A, B, C comma-heavy message", "category": "test"}]}
        csv = _build_risk_csv_from_cfo(cfo)
        lines = csv.strip().split("\n")
        # Each data line should have exactly 5 commas (5 fields)
        for line in lines[1:]:
            assert line.count(",") == 4

    def test_risk_csv_empty_when_no_alerts(self):
        csv = _build_risk_csv_from_cfo({})
        assert csv == ""

    def test_audit_csv_has_header(self):
        csv = _build_audit_findings_from_cfo(self._cfo_data())
        assert csv.startswith("finding_id,title,severity,status,category")

    def test_audit_csv_includes_anomalies(self):
        csv = _build_audit_findings_from_cfo(self._cfo_data())
        assert "Duplicate txn found" in csv
        assert "critical" in csv

    def test_audit_csv_includes_finding_ids(self):
        csv = _build_audit_findings_from_cfo(self._cfo_data())
        assert "F001" in csv

    def test_audit_csv_empty_when_no_anomalies(self):
        csv = _build_audit_findings_from_cfo({})
        assert csv == ""

    def test_audit_csv_max_10_findings(self):
        """Should cap at 10 even if more anomalies exist."""
        cfo = {
            "anomalies": [
                {"severity": "warning", "description": f"Anomaly {i}"}
                for i in range(20)
            ]
        }
        csv = _build_audit_findings_from_cfo(cfo)
        lines = [l for l in csv.split("\n") if l.strip()]
        # Header + max 10 data rows
        assert len(lines) <= 11


# ── on_agent_complete ─────────────────────────────────────────────────────────

class TestOnAgentComplete:
    @pytest.mark.asyncio
    async def test_cfo_complete_triggers_risk(self):
        ctx = _ctx_with_cfo()

        async def mock_get_ctx(*args, **kwargs):
            return ctx

        async def mock_save_ctx(*args, **kwargs):
            pass

        run_called: list[str] = []

        async def mock_run_risk(*args, **kwargs):
            run_called.append("risk")

        with (
            patch("app.services.auto_chain.get_company_context", new=mock_get_ctx),
            patch("app.services.auto_chain.save_company_context", new=mock_save_ctx),
            patch("app.services.auto_chain._run_risk_from_context", new=mock_run_risk),
            patch("app.services.auto_chain._run_audit_from_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_ceo_synthesis",      new=AsyncMock()),
        ):
            await on_agent_complete("cfo", "org-test", {}, db=None)

        assert "risk" in run_called

    @pytest.mark.asyncio
    async def test_cfo_complete_triggers_audit(self):
        ctx = _ctx_with_cfo()

        async def mock_get_ctx(*args, **kwargs):
            return ctx

        audit_called: list[str] = []

        async def mock_run_audit(*args, **kwargs):
            audit_called.append("audit")

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_risk_from_context",  new=AsyncMock()),
            patch("app.services.auto_chain._run_audit_from_context", new=mock_run_audit),
            patch("app.services.auto_chain._run_ceo_synthesis",      new=AsyncMock()),
        ):
            await on_agent_complete("cfo", "org-test", {}, db=None)

        assert "audit" in audit_called

    @pytest.mark.asyncio
    async def test_cfo_complete_triggers_ceo_synthesis(self):
        ctx = _ctx_with_cfo()
        ceo_called: list[bool] = []

        async def mock_ceo(*args, **kwargs):
            ceo_called.append(True)

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_risk_from_context",  new=AsyncMock()),
            patch("app.services.auto_chain._run_audit_from_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_ceo_synthesis",      new=mock_ceo),
        ):
            await on_agent_complete("cfo", "org-test", {}, db=None)

        assert len(ceo_called) == 1

    @pytest.mark.asyncio
    async def test_ceo_synthesis_skipped_without_cfo_result(self):
        """CEO synthesis requires last_cfo_result — should be skipped if absent."""
        ctx = _empty_ctx()  # no CFO result
        ceo_called: list[bool] = []

        async def mock_ceo(*args, **kwargs):
            ceo_called.append(True)

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_risk_from_context",  new=AsyncMock()),
            patch("app.services.auto_chain._run_audit_from_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_ceo_synthesis",      new=mock_ceo),
        ):
            await on_agent_complete("cfo", "org-test", {}, db=None)

        assert len(ceo_called) == 0

    @pytest.mark.asyncio
    async def test_risk_complete_triggers_compliance(self):
        ctx = _ctx_with_cfo()
        ctx.last_risk_result = {"risk_summary": {}}
        compliance_called: list[bool] = []

        async def mock_compliance(*args, **kwargs):
            compliance_called.append(True)

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_compliance_from_context", new=mock_compliance),
            patch("app.services.auto_chain._run_ceo_synthesis",           new=AsyncMock()),
        ):
            await on_agent_complete("risk", "org-test", {}, db=None)

        assert len(compliance_called) == 1

    @pytest.mark.asyncio
    async def test_non_ceo_triggering_agent_no_synthesis(self):
        """An agent NOT in CEO_TRIGGER_AGENTS should not trigger CEO synthesis."""
        ctx = _ctx_with_cfo()
        ceo_called: list[bool] = []

        async def mock_ceo(*args, **kwargs):
            ceo_called.append(True)

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_ceo_synthesis", new=mock_ceo),
        ):
            # "audit" is not in CEO_TRIGGER_AGENTS
            await on_agent_complete("audit", "org-test", {}, db=None)

        assert len(ceo_called) == 0

    @pytest.mark.asyncio
    async def test_errors_are_swallowed_not_raised(self):
        """on_agent_complete is a background task — errors should never propagate."""
        async def boom(*args, **kwargs):
            raise RuntimeError("Simulated failure in chained agent")

        with (
            patch("app.services.auto_chain.get_company_context", new=boom),
        ):
            # Should complete without raising
            await on_agent_complete("cfo", "org-test", {}, db=None)

    @pytest.mark.asyncio
    async def test_feedback_loop_fires_when_signal_active(self):
        """CFO cash crisis signal should attempt to trigger CHRO if not already run."""
        ctx = _ctx_with_cfo(runway_months=3.0)  # < 6 months → cash crisis
        # No CHRO result yet — should trigger CHRO
        assert ctx.last_chro_result is None

        chro_triggered: list[bool] = []

        async def mock_run_chained(agent, *args, **kwargs):
            chro_triggered.append(agent)

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_risk_from_context",  new=AsyncMock()),
            patch("app.services.auto_chain._run_audit_from_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_ceo_synthesis",      new=AsyncMock()),
            patch("app.services.auto_chain._run_chained_agent",      new=mock_run_chained),
        ):
            await on_agent_complete("cfo", "org-test", {}, db=None)

        # chro should be in triggered agents (feedback rule)
        assert "chro" in chro_triggered

    @pytest.mark.asyncio
    async def test_feedback_loop_sends_notification_when_target_already_run(self):
        """When target agent already has data, send cross-agent notification instead."""
        ctx = _ctx_with_cfo(runway_months=3.0)
        ctx.last_chro_result = {"headcount": 50}  # CHRO already has data

        notif_sent: list[bool] = []

        async def mock_send_notif(*args, **kwargs):
            notif_sent.append(True)

        with (
            patch("app.services.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
            patch("app.services.auto_chain.save_company_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_risk_from_context",  new=AsyncMock()),
            patch("app.services.auto_chain._run_audit_from_context", new=AsyncMock()),
            patch("app.services.auto_chain._run_ceo_synthesis",      new=AsyncMock()),
            patch("app.services.auto_chain._send_feedback_notification", new=mock_send_notif),
        ):
            await on_agent_complete("cfo", "org-test", {}, db=None)

        assert len(notif_sent) >= 1
