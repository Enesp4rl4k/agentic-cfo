"""
Unit tests for TCMB macroeconomic indicators and stress testing API (/api/v1/macro).
"""
import pytest

from tests.api_helpers import bellek_istemcisi, kullanici


@pytest.mark.asyncio
async def test_get_tcmb_indicators():
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "macro@test.com")
        assert org_id is not None

        res = await client.get("/api/v1/macro/tcmb", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json().get("data")
        assert data is not None
        assert "usd_try" in data
        assert "eur_try" in data
        assert "policy_rate_pct" in data
        assert "inflation_pct" in data
        assert "real_cost_of_capital" in data
        assert isinstance(data["usd_try"], (int, float))
        assert data["usd_try"] > 0


SHOCK = {
    "usd_shock_pct": 20.0,
    "eur_shock_pct": 20.0,
    "interest_rate_delta_bp": 600.0,
    "payment_delay_days": 20,
}


@pytest.mark.asyncio
async def test_simulate_without_cfo_analysis_returns_no_result():
    """A fresh org has no analysis: no invented company, an explicit reason."""
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "simulate@test.com")
        assert org_id is not None

        res = await client.post("/api/v1/macro/simulate", headers=headers, json=SHOCK)
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["current_macro"]["data_source"] in {
            "tcmb_api", "redis_cache", "static_fallback",
        }
        assert data["shock_inputs"]["eur_shock_pct"] == 20.0
        assert data["simulation_result"] is None
        assert data["baseline_missing_reason"] == "no_cfo_analysis"


@pytest.mark.asyncio
async def test_simulate_uses_the_orgs_own_cfo_result():
    from app.services.company_context import get_company_context, save_company_context

    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "simulate2@test.com")
        async with client._maker() as db:  # type: ignore[attr-defined]
            ctx = await get_company_context(org_id, db)
            ctx.update_agent_result("cfo", {
                "pnl": {"revenue": 1_200_000.0, "total_opex": 600_000.0,
                        "net_income": -120_000.0},
                "cashflow": {"monthly_series": [{}] * 12},
                "forecast": {"scenarios": {"base": {"runway_months": 8}}},
            })
            await save_company_context(ctx, db)

        res = await client.post("/api/v1/macro/simulate", headers=headers, json=SHOCK)
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        sim = data["simulation_result"]
        assert data["baseline_missing_reason"] is None
        assert sim["baseline_runway_months"] == 8.0
        assert sim["stressed_runway_months"] < 8.0
        assert sim["additional_fx_cost_lira"] == 2_500.0  # ₺50k/mo × 25% × 20%
        assert sim["data_source"] == "estimated"
        assert sim["recommendations"]
