"""Working capital is computed from the figures given, and the cash-flow
agent's version says it is an estimate.

`POST /analytics/working-capital` ignored every figure the page sent and
answered each company with the same four constants (current_ratio 1.5,
CCC 45 days, gap 150 000) — in a shape the page did not even read. The
cash-flow agent's CCC, meanwhile, is a band picked from average transaction
size while its docstring claimed "(AR / Revenue) × 365".
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.services.working_capital import CalismaSermayesiGirdisi, hesapla


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _headers(client, email: str = "wc@example.com") -> dict[str, str]:
    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": "StrongPassword123!", "full_name": "T"})
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": "StrongPassword123!"})
             ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_days_follow_the_formulas():
    # 365 000 TRY revenue → 1 000/day. 60 000 receivable → 60 days.
    s = hesapla(CalismaSermayesiGirdisi(alacaklar=60_000, yillik_ciro=365_000,
                                        borclar=30_000, yillik_smm=182_500, stok=18_250))
    d = s.to_dict()["metrikler"]
    assert d["dso"]["gun"] == 60.0
    assert d["dpo"]["gun"] == 60.0
    assert d["dio"]["gun"] == 36.5
    assert d["ccc"]["gun"] == 36.5  # 60 + 36.5 − 60
    assert d["dso"]["formul"] == "Alacaklar ÷ Yıllık ciro × 365"


def test_a_missing_denominator_leaves_the_metric_empty_and_names_the_input():
    s = hesapla(CalismaSermayesiGirdisi(alacaklar=10_000, yillik_ciro=0,
                                        borclar=5_000, yillik_smm=100_000))
    d = s.to_dict()
    assert d["metrikler"]["dso"]["gun"] is None and d["metrikler"]["ccc"]["gun"] is None
    assert "yıllık ciro" in d["eksik_girdiler"]
    assert "hesaplanamadı" in d["yorum"]


def test_no_sector_comparison_is_invented():
    d = hesapla(CalismaSermayesiGirdisi(alacaklar=1, yillik_ciro=365, borclar=1, yillik_smm=365)).to_dict()
    assert d["sektor_karsilastirmasi"] is None
    assert "sektör ortalaması verimiz yok" in d["sektor_karsilastirmasi_notu"]


async def test_the_endpoint_answers_from_the_figures_sent(client):
    headers = await _headers(client)
    r = await client.post("/api/v1/analytics/working-capital", headers=headers, json={
        "accounts_receivable_try": 60_000, "annual_revenue_try": 365_000,
        "accounts_payable_try": 30_000, "annual_cogs_try": 182_500, "inventory_try": 0,
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["metrikler"]["dso"]["gun"] == 60.0
    assert d["metrikler"]["ccc"]["gun"] == 0.0

    # A different company gets a different answer — the constants are gone.
    r2 = await client.post("/api/v1/analytics/working-capital", headers=headers, json={
        "accounts_receivable_try": 10_000, "annual_revenue_try": 365_000,
        "accounts_payable_try": 30_000, "annual_cogs_try": 182_500,
    })
    assert r2.json()["data"]["metrikler"]["dso"]["gun"] == 10.0


async def test_the_endpoint_needs_sign_in(client):
    r = await client.post("/api/v1/analytics/working-capital", json={
        "accounts_receivable_try": 1, "annual_revenue_try": 1,
        "accounts_payable_try": 1, "annual_cogs_try": 1,
    })
    assert r.status_code == 401


def test_the_cashflow_agents_cycle_declares_itself_an_estimate():
    from app.agents.cashflow_agent import _compute_ccc

    txs = [{"type": "income", "amount_cents": 50_000_00, "transaction_date": "2026-01-05"},
           {"type": "expense", "category": "cogs", "amount_cents": 20_000_00,
            "transaction_date": "2026-01-10"}]
    out = _compute_ccc(txs, total_revenue_cents=50_000_00, total_expenses_cents=20_000_00)
    assert out["olcum"] == "tahmin"
    assert out["dayanak"]
    assert out["interpretation"].startswith("Tahmini")
    assert "alacak/borç bakiyesi" in out["interpretation"]


def test_without_transactions_it_says_so_rather_than_estimating():
    from app.agents.cashflow_agent import _compute_ccc

    out = _compute_ccc([], total_revenue_cents=0, total_expenses_cents=0)
    assert out["olcum"] == "veri_yok" and out["ccc_days"] is None
