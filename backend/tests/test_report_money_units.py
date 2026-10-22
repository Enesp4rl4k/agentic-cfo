"""Unit-boundary pins for report formatters.

Contract (see decisionPacket loader fix): Report.data scalars are LIRA
(report_agent._fmt divides the pipeline's cents once); raw series
(monthly_series, months) stay KURUŞ; `*_cents` fields are true cents.
"""
from __future__ import annotations

from app.services.executive_report_pdf import _build_html, _fmt, _fmt_lira
from app.services.unified_report import _build_cfo_section, _fmt_tl


def test_formatters_disagree_only_on_the_unit() -> None:
    # kuruş input: divides once
    assert _fmt(500_000) == "₺5K"
    # lira input: never divides
    assert _fmt_lira(500_000) == "₺500K"
    # true-cents input (CTO/CMO *_cents fields): divides once
    assert _fmt_tl(500_000) == "₺5K"


def test_pdf_html_keeps_lira_scalars_undivided() -> None:
    dash = {
        "pnl": {
            "revenue": 1_000_000,          # lira
            "net_income": 120_000,         # lira
            "opex": {"technology": 250_000},  # lira
        },
        "cashflow": {
            "net_change": 75_000,          # lira
            "monthly_series": [            # kuruş (raw passthrough)
                {"month": "2026-01", "in": 500_000, "out": 300_000, "net": 200_000},
            ],
        },
        "forecast": {
            "scenarios": {"base": {"twelve_month_net": 1_200_000, "runway_months": 9}},
        },
        "anomalies": [],
    }
    html = _build_html(dash, "Acme", "2026-Q1", "2026-01-01T00:00:00+00:00")
    assert "₺1.0M" in html, "revenue 1M lira must not be divided to ₺10K"
    assert "₺10K" not in html, "revenue must not render 100× too small"
    assert "₺120K" in html, "net_income 120k lira"
    assert "₺75K" in html, "net_change 75k lira"
    assert "₺1.2M" in html, "twelve_month_net 1.2M lira"
    assert "₺2K" in html, "monthly_series net 200_000 kuruş = 2_000 lira"


def test_unified_cfo_section_keeps_lira_scalars() -> None:
    cfo = {
        "pnl": {"revenue": 1_000_000, "net_income": 120_000},
        "forecast": {
            "scenarios": {"base": {"twelve_month_net": 2_400_000, "runway_months": 10}},
        },
    }
    metrics = _build_cfo_section(cfo)["metrics"]
    assert metrics["revenue"] == "₺1.0M"
    assert metrics["net_income"] == "₺120K"
    assert metrics["forecast_12m"] == "₺2.4M"


def test_cascade_simulator_reads_report_scalars_as_lira() -> None:
    from app.services.cascade_simulator import CascadeSimulator

    sim = CascadeSimulator(
        pnl={"revenue": 12_000_000, "total_opex": 6_000_000},  # LIRA
        cashflow={"net_change": -300_000},                     # LIRA
        forecast={"scenarios": {"base": {"runway_months": 6}}},
    )
    assert sim.monthly_revenue == 1_000_000      # 12M lira / 12 — not 10_000
    assert sim.monthly_opex == 500_000           # 6M lira / 12 — not 5_000
    assert sim.cash_balance == 1_800_000         # |−300k| × 6 ay, lira — not 18_000


def test_cascade_simulator_kwargs_are_kurus() -> None:
    from app.services.cascade_simulator import CascadeSimulator

    sim = CascadeSimulator(
        revenue_monthly=500_000_00,   # 50M kuruş = 500k lira
        cash_balance=1_000_000_00,    # 100M kuruş = 1M lira
    )
    assert sim.monthly_revenue == 500_000
    assert sim.cash_balance == 1_000_000        # 100M kuruş = 1M lira
