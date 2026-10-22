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


@pytest.mark.asyncio
async def test_simulate_macro_shock():
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "simulate@test.com")
        assert org_id is not None

        body = {
            "usd_shock_pct": 20.0,
            "eur_shock_pct": 20.0,
            "interest_rate_delta_bp": 600.0,
            "payment_delay_days": 20,
        }
        res = await client.post("/api/v1/macro/simulate", headers=headers, json=body)
        assert res.status_code == 200, res.text
        data = res.json().get("data")
        assert data is not None
        assert "current_macro" in data
        assert "shock_inputs" in data
        assert "simulation_result" in data

        sim = data["simulation_result"]
        assert "baseline_runway_months" in sim
        assert "stressed_runway_months" in sim
        assert "runway_delta_months" in sim
        assert "monthly_cost_increase_lira" in sim
        assert "risk_level" in sim
        assert "recommendations" in sim

        # Shock should contract runway (stressed runway <= baseline runway)
        assert sim["stressed_runway_months"] <= sim["baseline_runway_months"]
        assert sim["runway_delta_months"] <= 0
        assert len(sim["recommendations"]) >= 1
