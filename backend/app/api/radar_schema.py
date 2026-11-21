"""The cash radar as the API publishes it.

`services.cash_radar` builds frozen dataclasses whose week and shortfall lists
hold plain dicts (`asdict(RadarItem)`, the action dicts), so a schema generated
from them says "a list of anything". These models name what is in the lists.
`tests/test_api_contract.py` checks they carry exactly the dataclasses' fields,
so a field added to the radar cannot be dropped from the response unnoticed.
"""
from __future__ import annotations

from pydantic import BaseModel


class RadarItemOut(BaseModel):
    id: str
    counterparty: str | None
    description: str | None
    amount_cents: int
    due_date: str | None
    expected_date: str
    delay_days: int
    is_overdue: bool
    instrument: str = "invoice"
    rescheduled: bool = False


class RadarWeekOut(BaseModel):
    week: int
    start_date: str
    end_date: str
    inflow_cents: int
    outflow_cents: int
    net_cents: int
    end_balance_cents: int
    receivables: list[RadarItemOut]
    payables: list[RadarItemOut]


class RadarActionOut(BaseModel):
    type: str
    title: str
    detail: str
    amount_cents: int


class ShortfallOut(BaseModel):
    week: int
    week_start: str
    week_end: str
    shortfall_cents: int
    driver: str
    actions: list[RadarActionOut]


class CashRadarOut(BaseModel):
    anchor_date: str
    starting_cash_cents: int | None
    starting_cash_as_of: str | None
    weeks: list[RadarWeekOut]
    shortfall: ShortfallOut | None
    overdue_receivables: list[RadarItemOut]
    overdue_payables_cents: int
    undated_receivables_cents: int
    undated_payables_cents: int
    beyond_horizon_cents: int
    other_currency_items: int
    not_included: list[str]
    recurring_payables_cents: int = 0
    tax_obligations_cents: int = 0
