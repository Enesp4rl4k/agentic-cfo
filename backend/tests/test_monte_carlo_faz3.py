"""Faz 3: Nakit Radarı Monte Carlo 'What-If' Simülatörü Doğrulama Testleri.

Doğrulamalar:
1. Simülasyon Motoru: İşe alım (SGK/işveren yükü dahil), borç öteleme, ciro şoku ve capex senaryoları.
2. 10.000 iterasyonluk Monte Carlo istatistikleri (kasa açık olasılığı, VaR %95, p10 <= p50 <= p90).
3. API Endpoint'i: POST /api/v1/simulation/what-if uçtan uca istek ve yanıt doğrulaması.
"""

from __future__ import annotations

import pytest

from app.services.monte_carlo import (
    ScenarioParam,
    run_monte_carlo_simulation,
)
from tests.api_helpers import bellek_istemcisi, kullanici


def _sample_baseline_weeks() -> list[dict]:
    # 13 haftalık deterministik akış
    weeks = []
    for i in range(13):
        weeks.append(
            {
                "week": i + 1,
                "inflow_cents": 10000000,  # ₺100.000 giriş
                "outflow_cents": 8000000,  # ₺80.000 çıkış
                "net_cents": 2000000,  # +₺20.000 net
                "end_balance_cents": 50000000 + (i + 1) * 2000000,
            }
        )
    return weeks


def test_monte_carlo_hire_headcount_scenario():
    """3.1: Personel işe alımı ve SGK işveren çarpanının nakit akışına etkisi."""
    base = _sample_baseline_weeks()
    starting_cash = 20000000  # ₺200.000 açılış kasası

    # 3 yeni personel, net ₺50.000 maaş (5.000.000 kuruş)
    scenarios = [
        ScenarioParam(
            scenario_type="hire_headcount",
            headcount=3,
            net_monthly_salary_cents=5000000,
            start_week=2,
        )
    ]

    res = run_monte_carlo_simulation(
        baseline_weeks=base,
        starting_cash_cents=starting_cash,
        scenarios=scenarios,
        iterations=2000,
        seed=123,
    )

    assert res.iterations == 2000
    assert len(res.weeks) == 13
    assert len(res.insights) >= 2

    # Yüzdelik dağılım tutarlılığı: P10 <= P50 <= P90
    for w in res.weeks:
        assert w.p10_cents <= w.p50_cents <= w.p90_cents, f"Hafta {w.week} persentil sırası bozuk"


def test_monte_carlo_revenue_shock_and_defer_payable():
    """3.1: %30 ciro düşüşü ve borç öteleme kombinasyonu."""
    base = _sample_baseline_weeks()
    starting_cash = 5000000  # ₺50.000 düşük kasa

    scenarios = [
        # %35 ciro şoku ve 14 gün gecikme
        ScenarioParam(
            scenario_type="revenue_shock",
            percentage_change=-35.0,
            delay_days=14,
        ),
        # ₺50.000 borcu 1. haftadan 8. haftaya öteleme
        ScenarioParam(
            scenario_type="defer_payable",
            amount_cents=5000000,
            from_week=1,
            to_week=8,
        ),
    ]

    res = run_monte_carlo_simulation(
        baseline_weeks=base,
        starting_cash_cents=starting_cash,
        scenarios=scenarios,
        iterations=2000,
        seed=999,
    )

    # Düşük başlangıç ve sert daralma açık olasılığını artırmalı
    assert res.cash_deficit_probability_pct > 0.0
    assert any("ötelendi" in ins for ins in res.insights)
    assert any("azalış" in ins for ins in res.insights)


@pytest.mark.asyncio
async def test_api_what_if_simulation_endpoint():
    """3.2: POST /api/v1/simulation/what-if API testi."""
    async with bellek_istemcisi() as client:
        headers, _org_id, _user_id = await kullanici(client, "patron@simcorp.com")

        resp = await client.post(
            "/api/v1/simulation/what-if",
            headers=headers,
            json={
                "scenarios": [
                    {
                        "scenario_type": "hire_headcount",
                        "headcount": 2,
                        "net_monthly_salary_cents": 4000000,
                        "start_week": 1,
                    },
                    {
                        "scenario_type": "capex_investment",
                        "amount_cents": 10000000,
                        "target_week": 4,
                    },
                ],
                "iterations": 1000,
            },
        )
        assert resp.status_code == 200, f"Hata: {resp.text}"
        data = resp.json()["data"]
        sim = data["simulated"]
        assert sim["iterations"] == 1000
        assert "cash_deficit_probability_pct" in sim
        assert "var_95_cents" in sim
        assert len(sim["weeks"]) == 13
        assert len(sim["insights"]) >= 2
