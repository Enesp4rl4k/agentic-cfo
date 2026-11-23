"""The ONE place a runway is read for display: its value, its basis and the sentence that says both.

The scenario field `forecast.scenarios.base.runway_months` is a bare number: it has no basis. Every consumer
that shows it, ranks risks by it, or hands it to a model takes the runway from here instead, as `RunwayView`,
built from `forecast.runway` (the `runway.compute_runway` block, as `chat_agent._runway_line` already reads it):

- known    -> the number with "(tarih) ekstresine göre";
- assumed  -> the number with the runway's own assumption sentence, and no "kritik" on its own authority;
- unknown  -> "bilinmiyor": no number, no severity word.

A forecast that carries a number but no runway block (an older stored report) is `unverified`: shown with
that said, never as proven. `tests/test_architecture_fitness.py` fails when a module outside this one reads
the scenario field directly (a short allowlist names the producers and the numeric-only readers).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.runway import (
    COMPUTED,
    NOT_BURNING,
    RUNWAY_WATCH_MONTHS,
    cash_gone,
    cash_gone_phrase,
    is_attention,
    is_comfortable,
    is_within,
    level_for_months,
    level_severity,
    months_phrase,
)
from app.services.runway import _date_tr as date_tr

PROMPT_RULE = (
    "Nakit ömrünün dayanağı 'kanıtlı' değilse (varsayım, doğrulanmamış ya da bilinmiyor) onu kesin bir olgu "
    "gibi tekrarlama; dayanağı söyle. 'Kritik' sözcüğünü yalnızca dayanağı kanıtlı olan nakit ömrü için kullan."
)


@dataclass(frozen=True)
class RunwayView:
    months: float | None
    basis: str                      # "known" | "assumed" | "unverified" | "unknown"
    as_of: str | None = None
    message: str = ""               # the runway block's own sentence (carries every assumption)
    identity_uncertain: bool = False
    sentence: str | None = None     # a sentence already built upstream (carried in a financial summary)
    reasons: tuple[str, ...] = ()   # why it is only assumed, one sentence each (the runway block's `reasons`)
    balance_cents: int | None = None  # the balance the runway starts from (<= 0: the cash is already gone)
    from_block: bool = False        # the runway block stands behind the number: its own class is the class
    block_level: str | None = None
    block_attention: bool = False
    scenario: bool = False          # a what-if row (optimistic, pessimistic): an assumption, so never critical

    @property
    def proven(self) -> bool:
        return self.basis == "known" and self.months is not None and not self.identity_uncertain

    @property
    def level(self) -> str | None:
        """The ONE class ("critical" | "warning" | None): the block's own when it stands behind the number, else the
        service's classifier over the figure. Critical only when proven: an assumed runway is capped at warning."""
        if self.months is None:
            return None
        if self.scenario:
            return level_for_months(self.months, proven=False)
        if self.from_block:
            return self.block_level  # the block already capped it for an assumed balance / open identity question
        return level_for_months(self.months, proven=self.proven)

    @property
    def severity(self) -> str | None:
        """The class in the alerts' and risks' vocabulary: "critical" | "high" | None."""
        return level_severity(self.level)

    @property
    def attention(self) -> bool:
        """Low enough to be said first, known or assumed (never as 'kritik' unless proven)."""
        return self.block_attention if self.from_block and not self.scenario else is_attention(self.months)

    @property
    def watch(self) -> bool:
        return is_within(self.months, RUNWAY_WATCH_MONTHS)

    @property
    def comfortable(self) -> bool:
        return is_comfortable(self.months)

    @property
    def label(self) -> str:
        """The word that goes with the class: KRİTİK (proven) | DİKKAT (low, assumed) | Uyarı | "" (none)."""
        if self.level == "critical":
            return "KRİTİK"
        if self.attention:
            return "DİKKAT"
        return "Uyarı" if self.level else ""

    @property
    def gone(self) -> bool:
        return cash_gone(self.balance_cents)

    def short(self) -> str:
        if self.months is None:
            return "bilinmiyor"
        if self.gone:
            return cash_gone_phrase("known" if self.proven else "assumed")
        return months_phrase(self.months)

    def text(self) -> str:
        """The figure with the basis it rests on: what a sentence may say about the runway."""
        if self.months is None:
            return "bilinmiyor"
        if self.sentence:
            return self.sentence
        if self.proven:
            when = f" ({date_tr(self.as_of)} ekstresine göre)" if self.as_of else ""
            return f"{self.short()}{when}"
        if self.basis == "unverified":
            return f"{self.short()} (dayanağı kayıtlı değil, doğrulanmadı)"
        if self.reasons:   # each reason keeps its OWN sentence: an old balance is not "weak evidence"
            return f"{self.short()} (varsayıma dayanıyor: {' '.join(self.reasons)})"
        return f"{self.short()} (varsayıma dayanıyor: {self.message})" if self.message else f"{self.short()} (varsayıma dayanıyor)"

    def cap(self, severity: str) -> str:
        """No critical on an unproven runway's authority."""
        return "high" if severity == "critical" and not self.proven else severity

    def fin_fields(self) -> dict[str, Any]:
        """The keys the CEO agents' financial summary carries beside the bare number."""
        return {
            "runway_basis": self.basis, "runway_text": self.text(), "runway_proven": self.proven,
            "runway_level": self.level, "runway_attention": self.attention,
        }

    def prompt_line(self) -> str:
        return f"Nakit ömrü: {self.text()}. {PROMPT_RULE}"


def runway_for_display(forecast: dict[str, Any] | None, scenario: str = "base") -> RunwayView:
    """The runway of a stored forecast scenario, with its basis. Missing everything -> unknown."""
    forecast = forecast or {}
    base = (forecast.get("scenarios") or {}).get(scenario) or {}
    value = base.get("runway_months")
    months = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    block = forecast.get("runway")
    if not isinstance(block, dict) or not block.get("status"):
        return RunwayView(months, "unverified" if months is not None else "unknown")
    if months is not None and block.get("status") not in (COMPUTED, NOT_BURNING):
        months = None  # a number the runway block itself does not stand behind
    if months is None:
        return RunwayView(None, "unknown", message=str(block.get("message") or ""))
    basis = "assumed" if (block.get("basis") != "known" or block.get("balance_basis") == "assumed") else "known"
    standing = block.get("status") == COMPUTED
    return RunwayView(
        months, basis, as_of=block.get("as_of"), message=str(block.get("message") or ""),
        identity_uncertain=bool(block.get("identity_uncertain")),
        reasons=tuple(str(r["text"]) for r in block.get("reasons") or [] if isinstance(r, dict) and r.get("text")),
        balance_cents=block.get("opening_cash_cents") if standing else None,
        scenario=scenario != "base", from_block=True, block_level=block.get("level") if standing else None,
        block_attention=bool(block.get("attention")) and standing,
    )


def view_from_fin(fin: dict[str, Any]) -> RunwayView:
    """A CEO-agent `financial_summary` carries the view's fields; rebuild the view's words from them."""
    months = fin.get("cash_runway_months")
    if not isinstance(months, (int, float)) or isinstance(months, bool):
        return RunwayView(None, "unknown")
    basis = fin.get("runway_basis") or "unverified"
    if basis == "known" and fin.get("runway_proven") is False:
        basis = "assumed"  # e.g. an open account-identity question
    view = RunwayView(float(months), basis, sentence=fin.get("runway_text") or None)
    if "runway_level" not in fin:  # a summary from before the class was carried: classify the figure itself
        return view
    return RunwayView(
        view.months, view.basis, sentence=view.sentence,
        from_block=True, block_level=fin.get("runway_level"), block_attention=bool(fin.get("runway_attention")),
    )
