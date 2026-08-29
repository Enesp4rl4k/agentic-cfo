"""Catalog of live data connectors (what is wired vs regional-pack stubs)."""
from __future__ import annotations

from typing import Any

CONNECTOR_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "billing_stripe",
        "label": "Stripe Revenue",
        "live": True,
        "produces": "canonical_csv",
        "pack": None,
    },
    {
        "id": "crm_export",
        "label": "CRM export (HubSpot/Salesforce CSV)",
        "live": True,
        "produces": "canonical_csv",
        "pack": None,
    },
    {
        "id": "hr_export",
        "label": "HR / payroll CSV",
        "live": True,
        "produces": "canonical_csv",
        "pack": None,
    },
    {
        "id": "github_activity",
        "label": "GitHub activity (CTO velocity)",
        "live": True,
        "produces": "cto_overlay",
        "pack": None,
    },
    {
        "id": "erp_parasut",
        "label": "Paraşüt",
        "live": True,
        "produces": "canonical_csv",
        "pack": "tr",
    },
    {
        "id": "erp_logo_tiger",
        "label": "Logo Tiger",
        "live": False,
        "produces": "canonical_csv",
        "pack": "tr",
    },
    {
        "id": "open_banking",
        "label": "Open Banking",
        "live": False,
        "produces": "canonical_csv",
        "pack": None,
    },
]


def list_connectors(*, live_only: bool = False) -> list[dict[str, Any]]:
    rows = CONNECTOR_REGISTRY
    if live_only:
        rows = [r for r in rows if r.get("live")]
    return list(rows)
