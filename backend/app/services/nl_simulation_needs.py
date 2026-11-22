"""What a natural-language what-if must state, and the error for inputs the company's data lacks."""
from __future__ import annotations

from typing import Any


class NeedsInput(Exception):
    """The simulation cannot run: the question or the company's data lacks these inputs."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(", ".join(missing))
        self.missing = missing


def missing_assumptions(intent: str, params: dict[str, Any]) -> list[str]:
    """What the question must state for this simulation. An assumption is the user's, never filled in."""
    need: list[str] = []
    if intent == "headcount":
        if "count" not in params:
            need.append("kişi sayısı")
    elif intent == "marketing":
        if "amount_try" not in params:
            need.append("aylık bütçe artışı (tutar)")
        if "expected_roas" not in params:
            need.append("beklenen ROAS (varsayımınız)")
    elif intent == "cascade":
        trigger = params.get("trigger")
        if trigger is None:
            need.append("hangi senaryo (nakit, gelir, kilit kişi)")
        elif trigger == "cash_crisis" and "months" not in params:
            need.append("kalan nakit ömrü (ay)")
        elif trigger == "revenue_drop" and "pct" not in params:
            need.append("gelir düşüş oranı (%)")
        elif trigger == "key_person_loss" and "role_type" not in params:
            need.append("kilit kişinin rolü")
        elif trigger == "market_shock":
            need.append("kur artışı ve enflasyon varsayımları (bu soru biçimiyle girilemez)")
    elif intent == "cost_cut":
        if "pct" not in params:
            need.append("kesinti oranı (%)")
    elif intent == "price":
        if "pct" not in params:
            need.append("fiyat artışı oranı (%)")
        need.append("beklenen müşteri kaybı varsayımınız (bu soru biçimiyle girilemez)")
    return need
