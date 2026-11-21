"""Cash runway starts from the proven balance, and no analytical alert holds a run.

Before: the forecast counted cumulative monthly net flow from ZERO, so a company with
₺116.500 in the bank was told it had one month of cash, and `needs_review = has_critical`
held every such upload for approval. Now:

- the runway is the proven opening cash over the burn of the months actually present;
- no proven balance, too few months, or a default-based figure: no runway is claimed and
  nothing is critical;
- an analytical alert (however severe) is shown with its basis and holds nothing; what
  still holds a run is a data-integrity condition (see `TestWhatStillHolds`).

No network, no model: the narrative is stubbed.
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("USE_SQLITE", "true")

from app.agents import forecast_agent
from app.agents.forecast_agent import run_forecast
from app.agents.forecast_montecarlo import _monte_carlo_simulation
from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig
from app.services.cash_radar import _opening_cash
from app.services.runway import compute_runway, opening_cash_for
from tests.test_agents.test_reconciliation import _consistent_pnl, _txns

CFG = AgentRunConfig(require_review=True, auto_proceed_min_confidence=0.80)


def _days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def _series(nets: list[int]) -> list[dict[str, Any]]:
    out = []
    for i, net in enumerate(nets):
        income = 5_000_000 + max(net, 0)
        out.append({"month": f"2026-{i + 1:02d}", "in": income, "out": income - net, "net": net})
    return out


def _state(nets: list[int], balance_cents: int | None, *, as_of: str | None = None, esas: str | None = None) -> dict[str, Any]:
    cashflow: dict[str, Any] = {"monthly_series": _series(nets), "net_change": sum(nets)}
    if esas:
        cashflow["esas"] = esas
    return {
        "job_id": "t",
        "cashflow": cashflow,
        "pnl": {"revenue": 1},
        "opening_cash": (
            {"date": as_of or _days_ago(2), "balance_cents": balance_cents, "job_id": "j", "filename": "ekstre.csv"}
            if balance_cents is not None else None
        ),
    }


@pytest.fixture
def _no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent is called directly: its narrative is stubbed (the pipeline tests below use no key)."""

    async def narrative(*_a: Any, **_k: Any) -> str:
        return "özet"

    monkeypatch.setattr(forecast_agent, "_generate_forecast_narrative", narrative)


async def _forecast(state: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    result = await run_forecast(state, AgentRunConfig())  # type: ignore[arg-type]
    assert result.ok, result.detail
    return result, result.patch["forecast"]


@pytest.mark.usefixtures("_no_model")
class TestRunwayFromProvenBalance:
    async def test_counts_down_from_the_balance_not_from_zero(self) -> None:
        # ₺-30.000 a month for three months, ₺116.500 in the bank: about 3,9 months, not "1".
        result, fc = await _forecast(_state([-3_000_000] * 3, 11_650_000))
        runway = fc["runway"]
        assert runway["status"] == "computed"
        assert runway["opening_cash_cents"] == 11_650_000
        assert runway["avg_monthly_net_cents"] == -3_000_000
        assert runway["months_used"] == 3
        assert runway["runway_months"] == pytest.approx(3.9, abs=0.05)
        assert runway["level"] == "warning"
        assert result.needs_review is False

    async def test_basis_is_stated_in_the_message(self) -> None:
        _, fc = await _forecast(_state([-3_000_000] * 3, 11_650_000, as_of="2026-11-19"))
        message = fc["runway"]["message"]
        assert "19 Kasım 2026 ekstresindeki bakiyeye göre" in message
        assert "₺116.500" in message and "₺30.000" in message and "son 3 ayın" in message

    async def test_a_healthy_company_with_a_negative_month_is_not_critical(self) -> None:
        # The e2e statement's shape: net slightly negative on average, ₺116.500 in the bank.
        result, fc = await _forecast(_state([3_800_000, -1_200_000, -2_950_000], 11_650_000))
        assert not any(a["level"] == "critical" for a in fc["alerts"])
        assert result.needs_review is False
        assert fc["runway"]["runway_months"] is None and fc["runway"]["beyond_horizon"] is True  # "36 aydan uzun"

    async def test_scenario_runways_count_down_from_the_same_balance(self) -> None:
        _, fc = await _forecast(_state([-3_000_000] * 3, 11_650_000))
        assert fc["scenarios"]["base"]["runway_basis"] == "computed"
        assert fc["scenarios"]["pessimistic"]["runway_months"] is not None

    async def test_one_source_of_truth_with_the_cash_radar(self) -> None:
        # Same proven balance, same staleness rule as the radar: age and stale agree.
        today = datetime.now(UTC).date()
        for age in (2, 7, 8, 40):
            as_of = (today - timedelta(days=age)).isoformat()
            ours = opening_cash_for({"opening_cash": {"date": as_of, "balance_cents": 5}}, today)
            radar = _opening_cash({"date": as_of, "balance_cents": 5}, today)
            assert ours is not None and radar is not None
            assert (ours["age_days"], ours["stale"], ours["balance_cents"]) == (radar.age_days, radar.stale, radar.balance_cents)

    def test_the_newer_of_this_runs_statement_and_the_companys_balance_wins(self) -> None:
        rows = [
            {"type": "income", "amount_cents": 100, "balance_cents": 1_100, "transaction_date": "2026-11-18"},
            {"type": "expense", "amount_cents": 50, "balance_cents": 1_050, "transaction_date": "2026-11-19"},
        ]
        older = {"date": "2026-10-01", "balance_cents": 7}
        newer = {"date": "2026-11-25", "balance_cents": 9}
        today = date(2026, 11, 26)
        assert opening_cash_for({"transactions": rows, "opening_cash": older}, today)["balance_cents"] == 1_050  # type: ignore[index]
        assert opening_cash_for({"transactions": rows, "opening_cash": newer}, today)["balance_cents"] == 9  # type: ignore[index]

    async def test_a_stale_balance_is_labelled_not_hidden(self) -> None:
        _, fc = await _forecast(_state([-3_000_000] * 3, 11_650_000, as_of=_days_ago(40)))
        assert fc["runway"]["stale"] is True
        assert "gün önceki ekstreden" in fc["runway"]["message"]


@pytest.mark.usefixtures("_no_model")
class TestNothingIsInvented:
    async def test_no_proven_balance_means_no_runway_and_no_critical(self) -> None:
        result, fc = await _forecast(_state([-3_000_000] * 6, None))
        runway = fc["runway"]
        assert runway["status"] == "no_balance"
        assert runway["runway_months"] is None and runway["opening_cash_cents"] is None
        assert "Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı" in runway["message"]
        assert all(sc["runway_months"] is None for sc in fc["scenarios"].values())
        assert not any(a["level"] == "critical" for a in fc["alerts"])
        assert any(a["level"] == "info" and a["basis"] == "runway" for a in fc["alerts"])  # missing, said as missing
        assert result.needs_review is False

    async def test_short_history_is_stated_not_extrapolated(self) -> None:
        result, fc = await _forecast(_state([-9_000_000, -9_000_000], 11_650_000))
        runway = fc["runway"]
        assert runway["status"] == "insufficient_history"
        assert runway["months_used"] == 2 and runway["months_needed"] == 3
        assert runway["runway_months"] is None
        assert "en az 3 ay gerekir" in runway["message"]
        assert fc["limited_history"] is True
        assert all(sc["runway_months"] is None for sc in fc["scenarios"].values())
        assert not any(a["level"] == "critical" for a in fc["alerts"])
        assert result.needs_review is False

    async def test_a_company_that_is_not_burning_has_no_runway_to_claim(self) -> None:
        _, fc = await _forecast(_state([500_000, 400_000, 300_000], 11_650_000))
        assert fc["runway"]["status"] == "not_burning" and fc["runway"]["runway_months"] is None
        assert fc["runway"]["level"] is None

    async def test_accrual_months_are_not_a_cash_burn(self) -> None:
        _, fc = await _forecast(_state([-3_000_000] * 3, 11_650_000, esas="tahakkuk"))
        assert fc["runway"]["status"] == "not_cash_basis" and fc["runway"]["runway_months"] is None

    def test_compute_runway_without_balance_has_no_inputs(self) -> None:
        block = compute_runway(None, {"monthly_series": _series([-1, -1, -1])})
        assert block["opening_cash_cents"] is None and block["avg_monthly_net_cents"] is None


@pytest.mark.usefixtures("_no_model")
class TestDefaultsNeverAlert:
    def test_too_few_months_use_the_labelled_defaults(self) -> None:
        series = _series([-500_000] * 5)  # five months: fewer than the five returns a volatility needs
        out = _monte_carlo_simulation(series, opening_cash_cents=0)
        assert out["growth_basis"] == "varsayilan"
        assert (out["growth_mu"], out["growth_sigma"]) == (0.01, 0.05)

    async def test_a_default_based_simulation_cannot_alert_or_hold(self) -> None:
        # Five months, an empty balance: the stand-in growth shows a high share, which is not an alert.
        result, fc = await _forecast(_state([-500_000] * 5, 1_000))
        assert fc["monte_carlo"]["growth_basis"] == "varsayilan"
        assert not any(a.get("basis") == "monte_carlo" for a in fc["alerts"])
        assert result.needs_review is False

    async def test_a_measured_simulation_is_a_warning_at_most(self) -> None:
        nets = [100_000, -300_000, -100_000, -400_000, -100_000, -500_000, -200_000, -600_000]
        state = _state(nets, 1_000_000)
        state["cashflow"]["monthly_series"] = [
            {"month": f"2026-{i + 1:02d}", "in": a, "out": 900_000, "net": a - 900_000}
            for i, a in enumerate([1_000_000, 700_000, 900_000, 500_000, 800_000, 400_000, 600_000, 300_000])
        ]
        result, fc = await _forecast(state)
        mc_alerts = [a for a in fc["alerts"] if a.get("basis") == "monte_carlo"]
        assert fc["monte_carlo"]["growth_basis"] == "gecmis_aylar" and mc_alerts
        assert {a["level"] for a in mc_alerts} == {"warning"}
        assert result.needs_review is False

    def test_the_risk_share_counts_from_the_balance(self) -> None:
        series = [
            {"month": f"2026-{i + 1:02d}", "in": 1_000_000, "out": 900_000, "net": 100_000} for i in range(8)
        ]
        assert _monte_carlo_simulation(series, opening_cash_cents=None)["runway_risk_pct"] is None
        assert _monte_carlo_simulation(series, opening_cash_cents=50_000_000)["runway_risk_pct"] == 0.0


@pytest.mark.usefixtures("_no_model")
class TestBadNewsIsSurfacedNotHeld:
    async def test_a_genuinely_low_runway_is_critical_with_its_inputs(self) -> None:
        result, fc = await _forecast(_state([-5_000_000] * 3, 11_650_000, as_of="2026-11-19"))
        runway = fc["runway"]
        assert runway["level"] == "critical"
        assert runway["runway_months"] == pytest.approx(2.3, abs=0.05)
        critical = [a for a in fc["alerts"] if a["level"] == "critical"]
        assert len(critical) == 1 and critical[0]["basis"] == "runway"
        for fact in ("19 Kasım 2026", "₺116.500", "₺50.000", "son 3 ayın", "yaklaşık 2,3 ay"):
            assert fact in critical[0]["message"]
        # ... and the books are not withheld because of it.
        assert result.needs_review is False
        assert result.confidence >= 0.80

    async def test_a_cashflow_critical_alert_does_not_hold_either(self) -> None:
        from app.agents.cashflow_agent import run_cashflow

        rows = [
            {"type": "expense", "amount_cents": 3_000_000, "category": "rent", "transaction_date": f"2026-0{m}-05", "currency": "TRY"}
            for m in (1, 2, 3)
        ]
        result = await run_cashflow({"transactions": rows, "job_id": "t"}, AgentRunConfig())  # type: ignore[arg-type]
        assert any(a["level"] == "critical" for a in result.patch["cashflow"]["alerts"])
        assert result.needs_review is False and result.confidence >= 0.80


def _statement(path: Path, balances_by_month: list[tuple[int, str, int]], *, currency: bool = True) -> str:
    """A bank statement whose running balance chains. Rows: (days ago, text, signed lira)."""
    today = datetime.now(UTC).date()
    opening = 120_000
    lines = ["Tarih;Açıklama;Tutar;Bakiye" + (";Para Birimi" if currency else "")]
    balance = opening
    for ago, text, amount in sorted(balances_by_month, reverse=True):
        balance += amount
        d = today - timedelta(days=ago)
        tl = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        lines.append(f'{d.strftime("%d.%m.%Y")};{text};"{tl(amount)}";"{tl(balance)}"' + (";TRY" if currency else ""))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


HEALTHY = [
    (75, "Ofis kirası", -12_000), (70, "Satış tahsilatı - Mavi Tekstil", 50_000), (40, "Ofis kirası", -12_000),
    (20, "Personel maaş ödemesi", -30_000), (5, "Ofis kirası", -12_000), (2, "Danışmanlık geliri - Kara Holding", 12_500),
]
CASH_SHORT = [
    (100, "Satış tahsilatı", 20_000), (95, "Personel maaş ödemesi", -60_000), (70, "Ofis kirası", -30_000),
    (65, "Personel maaş ödemesi", -60_000), (40, "Ofis kirası", -30_000), (35, "Personel maaş ödemesi", -60_000),
    (10, "Ofis kirası", -30_000), (5, "Personel maaş ödemesi", -60_000),
]


class TestPipelineHolds:
    async def test_an_ordinary_statement_is_not_held_and_has_an_opening_balance(self, tmp_path: Path) -> None:
        path = _statement(tmp_path / "ekstre.csv", HEALTHY)
        result = await run_cfo_pipeline(job_id="healthy", file_path=path, file_type="csv", run_config=CFG)
        assert result["awaiting_review"] is False and not result.get("halted")
        assert result["verifier_verdict"]["action"] == "proceed"
        runway = result["forecast"]["runway"]
        assert runway["opening_cash_cents"] == 11_650_000  # the statement's closing balance
        assert runway["source_filename"] == "ekstre.csv"
        # The dashboard (what the forecast page reads) carries the runway with its basis.
        assert result["dashboard_json"]["forecast"]["runway"]["opening_cash_cents"] == 11_650_000
        # The cash-flow agent's own critical alerts are on the screen and did not hold it.
        assert any(a["level"] == "critical" for a in result["cashflow"]["alerts"])

    async def test_the_companys_proven_balance_is_used_when_the_file_has_none(self, tmp_path: Path) -> None:
        path = tmp_path / "hareketler.csv"
        path.write_text(
            "Tarih;Açıklama;Tutar;Para Birimi\n"
            + "\n".join(f"05.0{m}.2026;Kira;-12.000,00;TRY" for m in (1, 2, 3))
            + "\n",
            encoding="utf-8",
        )
        opening = {"date": _days_ago(1), "balance_cents": 9_000_000, "job_id": "old", "filename": "onceki.csv"}
        result = await run_cfo_pipeline(
            job_id="own-none", file_path=str(path), file_type="csv", run_config=CFG, opening_cash=opening
        )
        assert result["forecast"]["runway"]["opening_cash_cents"] == 9_000_000
        assert result["forecast"]["runway"]["source_filename"] == "onceki.csv"

    async def test_a_genuinely_cash_short_company_is_told_so_and_is_not_held(self, tmp_path: Path) -> None:
        path = _statement(tmp_path / "kisa.csv", CASH_SHORT)
        result = await run_cfo_pipeline(job_id="short", file_path=path, file_type="csv", run_config=CFG)
        runway = result["forecast"]["runway"]
        assert runway["status"] == "computed" and runway["level"] == "critical"
        assert runway["opening_cash_cents"] < 6_000_000 and runway["months_used"] == 3
        assert any(a["level"] == "critical" and a["basis"] == "runway" for a in result["forecast"]["alerts"])
        assert result["awaiting_review"] is False  # shown, not withheld


class TestWhatStillHolds:
    """Every remaining hold is a data-integrity condition a person can decide on THAT upload."""

    @pytest.mark.real_currency  # conftest assumes a base currency for org-less runs; this is the rule itself
    async def test_rows_without_a_currency_wait_for_a_person(self, tmp_path: Path) -> None:
        path = _statement(tmp_path / "paraBirimsiz.csv", HEALTHY, currency=False)
        result = await run_cfo_pipeline(job_id="nocur", file_path=path, file_type="csv", run_config=CFG)
        assert result["awaiting_review"] is True
        assert "kayıt incelemenizi bekliyor" in result["logs"][0].detail

    async def test_an_unreadable_file_is_held(self) -> None:
        bad = Path(__file__).resolve().parent.parent / "fixtures" / "tr_corpus" / "bozuk_veri.csv"
        result = await run_cfo_pipeline(job_id="bozuk", file_path=str(bad), file_type="csv", run_config=CFG)
        assert result["awaiting_review"] is True

    def test_low_confidence_holds_and_cannot_be_bypassed(self) -> None:
        from app.agents.verifier_node import evaluate_cfo_state

        verdict = evaluate_cfo_state(
            {"min_confidence": 0.7, "awaiting_review": False},  # type: ignore[arg-type]
            run_config=AgentRunConfig(require_review=False),
        )
        assert verdict.action == "hold_for_review"

    def test_a_step_that_asks_for_a_person_holds(self) -> None:
        from app.agents.verifier_node import evaluate_cfo_state

        assert evaluate_cfo_state({"min_confidence": 0.9, "awaiting_review": True}).action == "hold_for_review"  # type: ignore[arg-type]

    def test_a_narrative_quoting_an_ungrounded_figure_holds(self) -> None:
        from app.agents.reconciliation_node import reconcile_cfo_state

        pnl = _consistent_pnl()
        pnl["narrative"] = "Gelir 100000 TL; ancak beklenmedik 7500000 TL kayıp oluştu."
        assert reconcile_cfo_state({"pnl": pnl, "transactions": _txns()}).action == "hold_for_review"  # type: ignore[arg-type]

    def test_a_narrative_quoting_the_runways_own_inputs_is_grounded(self) -> None:
        from app.agents.reconciliation_node import reconcile_cfo_state

        pnl = _consistent_pnl()
        pnl["narrative"] = "Kasa 11650000 kuruş, aylık net çıkış 3000000."
        forecast = {"runway": {"opening_cash_cents": 11_650_000, "avg_monthly_net_cents": -3_000_000}}
        verdict = reconcile_cfo_state({"pnl": pnl, "forecast": forecast, "transactions": _txns()})  # type: ignore[arg-type]
        assert verdict.action == "proceed"

    def test_a_reconciliation_failure_halts(self) -> None:
        from app.agents.reconciliation_node import reconcile_cfo_state

        pnl = _consistent_pnl()
        pnl["net_income"] = 1
        assert reconcile_cfo_state({"pnl": pnl, "transactions": _txns()}).action == "halt"  # type: ignore[arg-type]

    def test_the_gate_holds_a_failed_step_and_an_unmeasured_run(self) -> None:
        from app.platform.run_gate import evaluate

        assert evaluate({"logs": [{"step": "x", "ok": False, "confidence": 0.9}]}).awaiting_review is True
        assert evaluate({"logs": []}).awaiting_review is True
        assert evaluate({"logs": [{"step": "forecast", "ok": True, "confidence": 0.85}], "min_confidence": 0.85}).awaiting_review is False


class TestAlertsApiReadsOnlyMeasuredRisk:
    def _alerts(self, mc: dict[str, Any]) -> list[Any]:
        from types import SimpleNamespace

        from app.api.alerts import _extract_raw_alerts

        job = SimpleNamespace(id="j", completed_at=None, updated_at=None, logs=[])
        return [a for a in _extract_raw_alerts(job, {"forecast": {"monte_carlo": mc}}) if a.source == "monte_carlo"]  # type: ignore[arg-type]

    def test_a_figure_counted_from_zero_or_from_defaults_raises_nothing(self) -> None:
        assert self._alerts({"runway_risk_pct": 90.0, "growth_basis": "gecmis_aylar"}) == []  # stored before: from zero
        assert self._alerts({"runway_risk_pct": 90.0, "runway_risk_basis": "opening_cash", "growth_basis": "varsayilan"}) == []
        assert self._alerts({"runway_risk_pct": None, "runway_risk_basis": None, "growth_basis": "gecmis_aylar"}) == []

    def test_a_measured_one_is_a_warning_even_when_very_high(self) -> None:
        got = self._alerts({"runway_risk_pct": 95.0, "runway_risk_basis": "opening_cash", "growth_basis": "gecmis_aylar"})
        assert [a.level for a in got] == ["warning"]
