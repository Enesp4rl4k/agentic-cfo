"""Pack-aware tax rate tables (international core + TR pack)."""
from __future__ import annotations

from typing import Any


# Generic rates by ISO country — illustrative defaults for the tax lens
GENERIC_TAX_BY_COUNTRY: dict[str, list[dict[str, Any]]] = {
    "US": [
        {"code": "sales_tax", "label": "Sales tax (est.)", "rate": 0.07},
        {"code": "federal_corp", "label": "Federal corporate (est.)", "rate": 0.21},
    ],
    "GB": [
        {"code": "vat", "label": "VAT standard", "rate": 0.20},
        {"code": "corp", "label": "Corporation tax (est.)", "rate": 0.25},
    ],
    "DE": [
        {"code": "vat", "label": "MwSt standard", "rate": 0.19},
        {"code": "corp", "label": "Corporate tax (est.)", "rate": 0.30},
    ],
    "AE": [
        {"code": "vat", "label": "VAT", "rate": 0.05},
        {"code": "corp", "label": "Corporate tax", "rate": 0.09},
    ],
}

TR_TAX_RATES: list[dict[str, Any]] = [
    {"code": "kdv_std", "label": "KDV (standard)", "rate": 0.20},
    {"code": "kdv_reduced", "label": "KDV (reduced)", "rate": 0.10},
    {"code": "stopaj", "label": "Stopaj (est.)", "rate": 0.20},
    {"code": "kurumlar", "label": "Kurumlar vergisi", "rate": 0.25},
]


def tax_rates_for_org(*, country_code: str, regional_packs: list[str] | None = None) -> dict[str, Any]:
    packs = [p.lower() for p in (regional_packs or [])]
    cc = (country_code or "US").upper()
    if "tr" in packs or cc == "TR":
        return {
            "country_code": "TR",
            "pack": "tr",
            "rates": TR_TAX_RATES,
            "source": "turkey_pack",
        }
    rates = GENERIC_TAX_BY_COUNTRY.get(cc) or GENERIC_TAX_BY_COUNTRY["US"]
    return {
        "country_code": cc if cc in GENERIC_TAX_BY_COUNTRY else "US",
        "pack": None,
        "rates": rates,
        "source": "generic",
    }
