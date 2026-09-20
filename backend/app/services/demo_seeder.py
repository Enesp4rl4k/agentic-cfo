"""
Demo Data Seeder & Playground Engine (Phase 4 & Onboarding).

Generates rich, realistic synthetic transactions, P&L, and e-Fatura records
for instant onboarding exploration across 3 industry archetypes:
1. SaaS Startup (B2B Recurring Revenue & Software Costs)
2. E-Commerce Scaleup (High Volume Daily Sales & Ad Spend)
3. Manufacturing SME (Raw Materials, Factory OpEx & Export Invoices)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.financial import amount_to_cents


@dataclass
class DemoScenarioData:
    scenario_id: str
    company_name: str
    industry: str
    currency: str
    transactions: list[dict[str, Any]] = field(default_factory=list)
    invoices: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, int] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


class DemoSeeder:
    """Produces instant, rich company datasets for testing and onboarding."""

    @classmethod
    def seed_scenario(
        cls,
        scenario_type: str = "saas_startup",
        base_date: datetime | None = None,
    ) -> DemoScenarioData:
        """
        Generate synthetic demo data for a given scenario.
        """
        dt = base_date or datetime.now()
        cur_year = dt.year
        cur_month = dt.month

        if scenario_type == "ecommerce_scaleup":
            return cls._seed_ecommerce(cur_year, cur_month)
        elif scenario_type == "manufacturing_sme":
            return cls._seed_manufacturing(cur_year, cur_month)
        else:
            return cls._seed_saas(cur_year, cur_month)

    @classmethod
    def _seed_saas(cls, year: int, month: int) -> DemoScenarioData:
        transactions = []
        invoices = []

        # Inflows (MRR from enterprise customers)
        customers = [
            ("Alpha Bank Tech", 150000.0),
            ("Trendy Retail A.Ş.", 85000.0),
            ("FinTech Labs Global", 120000.0),
            ("E-Commerce Portal", 65000.0),
            ("B2B Logis A.Ş.", 45000.0),
        ]
        for name, amt in customers:
            tx_cents = amount_to_cents(amt)
            tx_date = f"{year:04d}-{month:02d}-{random.randint(2, 10):02d}"
            transactions.append({
                "id": f"tx-saas-in-{random.randint(1000, 9999)}",
                "amount_cents": tx_cents,
                "type": "income",
                "category": "revenue",
                "vendor": name,
                "description": f"SaaS Kurumsal Yıllık Lisans: {name}",
                "transaction_date": tx_date,
                "confidence": 1.0,
            })
            invoices.append({
                "invoice_id": f"inv-saas-{random.randint(1000, 9999)}",
                "invoice_number": f"GIB{year}0000{random.randint(100, 999)}",
                "amount_cents": tx_cents,
                "gross_amount": amt,
                "counterparty": name,
                "direction": "outbound",
            })

        # Outflows (Salaries, AWS, Tools)
        expenses = [
            ("Bordro & Yazılımcı Maaşları", 180000.0, "payroll"),
            ("Amazon Web Services (AWS) Cloud", 45000.0, "software"),
            ("OpenAI API & Model Hosting", 25000.0, "software"),
            ("Levent Ofis Kira Bedeli", 35000.0, "rent"),
            ("Google Ads & Pazarlama", 30000.0, "marketing"),
        ]
        for desc, amt, cat in expenses:
            tx_cents = amount_to_cents(amt)
            tx_date = f"{year:04d}-{month:02d}-{random.randint(12, 25):02d}"
            transactions.append({
                "id": f"tx-saas-out-{random.randint(1000, 9999)}",
                "amount_cents": tx_cents,
                "type": "expense",
                "category": cat,
                "vendor": desc.split()[0],
                "description": desc,
                "transaction_date": tx_date,
                "confidence": 1.0,
            })

        tot_in = sum(t["amount_cents"] for t in transactions if t["type"] == "income")
        tot_out = sum(t["amount_cents"] for t in transactions if t["type"] == "expense")

        return DemoScenarioData(
            scenario_id="saas_startup",
            company_name="CloudMatrix Yazılım A.Ş.",
            industry="B2B SaaS / Enterprise AI",
            currency="TRY",
            transactions=transactions,
            invoices=invoices,
            budget={"revenue": tot_in, "cogs": 0, "operating_expenses": tot_out},
            summary={
                "mrr_try": (tot_in / 100),
                "burn_try": (tot_out / 100),
                "net_profit_try": ((tot_in - tot_out) / 100),
                "runway_months": 24.0,
            },
        )

    @classmethod
    def _seed_ecommerce(cls, year: int, month: int) -> DemoScenarioData:
        transactions = []
        invoices = []

        # High volume daily sales
        total_sales_cents = amount_to_cents(1250000.0)
        transactions.append({
            "id": "tx-ecom-in-1",
            "amount_cents": total_sales_cents,
            "type": "income",
            "category": "revenue",
            "vendor": "İyzico / PayTR / Trendyol Marketplace",
            "description": "E-Ticaret Pazaryeri ve Web Satış Hasılatı",
            "transaction_date": f"{year:04d}-{month:02d}-15",
            "confidence": 1.0,
        })

        # COGS & Marketing
        transactions.append({
            "id": "tx-ecom-out-1",
            "amount_cents": amount_to_cents(650000.0),
            "type": "expense",
            "category": "cogs",
            "vendor": "Tedarikçi Tekstil Ltd.",
            "description": "Stok ve Ürün Tedarik Bedeli",
            "transaction_date": f"{year:04d}-{month:02d}-10",
            "confidence": 1.0,
        })
        transactions.append({
            "id": "tx-ecom-out-2",
            "amount_cents": amount_to_cents(250000.0),
            "type": "expense",
            "category": "marketing",
            "vendor": "Meta & Google Ads",
            "description": "Dijital Performans Reklam Harcamaları",
            "transaction_date": f"{year:04d}-{month:02d}-20",
            "confidence": 1.0,
        })

        return DemoScenarioData(
            scenario_id="ecommerce_scaleup",
            company_name="ModaTrend E-Ticaret A.Ş.",
            industry="D2C E-Commerce & Retail",
            currency="TRY",
            transactions=transactions,
            invoices=invoices,
            summary={"monthly_gmv": 1250000.0, "gross_margin_pct": 48.0},
        )

    @classmethod
    def _seed_manufacturing(cls, year: int, month: int) -> DemoScenarioData:
        transactions = []
        transactions.append({
            "id": "tx-mfg-in-1",
            "amount_cents": amount_to_cents(2500000.0),
            "type": "income",
            "category": "revenue",
            "vendor": "Avrupa İhracat Müşterisi (DE)",
            "description": "Sanayi Parça İhracat Hasılatı",
            "transaction_date": f"{year:04d}-{month:02d}-12",
            "confidence": 1.0,
        })
        transactions.append({
            "id": "tx-mfg-out-1",
            "amount_cents": amount_to_cents(1400000.0),
            "type": "expense",
            "category": "cogs",
            "vendor": "Demir Çelik Sanayi A.Ş.",
            "description": "Hammadde ve Saç Alımı",
            "transaction_date": f"{year:04d}-{month:02d}-05",
            "confidence": 1.0,
        })

        return DemoScenarioData(
            scenario_id="manufacturing_sme",
            company_name="Anadolu Makine Sanayi ve Ticaret A.Ş.",
            industry="Sanayi & İmalat",
            currency="TRY",
            transactions=transactions,
        )
