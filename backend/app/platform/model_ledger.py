"""The Model Gateway's in-process cost ledger: survives without a database, resets on restart."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Ledger:
    calls: int = 0
    ok_calls: int = 0
    total_cost_usd: float = 0.0
    unpriced_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    by_model: dict[str, dict[str, float]] = field(default_factory=dict)
    by_org: dict[str, dict[str, float]] = field(default_factory=dict)

    def record(self, res: Any, org_id: str | None, ok: bool) -> None:
        self.calls += 1
        if ok:
            self.ok_calls += 1
        cost = res.cost_usd or 0.0
        self.unpriced_calls += res.cost_usd is None
        self.total_cost_usd = round(self.total_cost_usd + cost, 6)
        self.total_input_tokens += res.input_tokens
        self.total_output_tokens += res.output_tokens
        m = self.by_model.setdefault(res.model, {"calls": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["cost_usd"] = round(m["cost_usd"] + cost, 6)
        key = org_id or "(none)"
        o = self.by_org.setdefault(key, {"calls": 0, "cost_usd": 0.0})
        o["calls"] += 1
        o["cost_usd"] = round(o["cost_usd"] + cost, 6)

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "ok_calls": self.ok_calls,
            "total_cost_usd": self.total_cost_usd,
            "unpriced_calls": self.unpriced_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "avg_cost_usd": round(self.total_cost_usd / self.calls, 6) if self.calls else 0.0,
            "by_model": self.by_model,
            "by_org": self.by_org,
        }

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]
