"""
Context Engineering — ContextBuilder

Solves the core LLM context problem in agentic pipelines:
  - Raw transaction lists can be 2000+ rows (>> LLM context window)
  - Each agent only needs a specific *slice* of CFOState
  - Sending the full state wastes tokens and increases hallucination risk

Design:
  - Token budget enforced per call (default 4096 prompt tokens)
  - Slice-based: each agent declares which fields it needs
  - Priority-ordered: high-value summaries first, raw rows last / truncated
  - Deterministic: same input → same output (no random sampling)
  - Observable: returns ContextResult with token counts for telemetry

Token counting strategy:
  - Exact tiktoken (cl100k_base) when available
  - Character-based fallback: 1 token ≈ 4 chars (safe approximation)

Usage:
    ctx = ContextBuilder(budget=4096)
    result = ctx.build_pnl_context(state, sector="tech")
    prompt = result.text  # ready to send to LLM
    print(result.token_count, result.truncated)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Token counting ────────────────────────────────────────────────────────────

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))

except ImportError:
    def _count_tokens(text: str) -> int:
        # Safe fallback: 1 token ≈ 4 characters
        return max(1, len(text) // 4)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ContextResult:
    text: str
    token_count: int
    budget: int
    truncated: bool
    slices_included: list[str] = field(default_factory=list)
    slices_dropped: list[str] = field(default_factory=list)

    @property
    def utilization(self) -> float:
        """Fraction of budget used (0.0–1.0)."""
        return self.token_count / self.budget if self.budget > 0 else 0.0

    def __repr__(self) -> str:
        trunc = " [TRUNCATED]" if self.truncated else ""
        return (
            f"ContextResult({self.token_count}/{self.budget} tokens{trunc}, "
            f"slices={self.slices_included})"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_currency(cents: int | float | None) -> str:
    if cents is None:
        return "N/A"
    return f"₺{cents / 100:,.0f}"


def _summarise_transactions(
    txs: list[dict[str, Any]],
    max_rows: int = 50,
    sort_by_amount: bool = True,
) -> str:
    """
    Produce a compact CSV-like summary of transactions.
    Sorted by abs(amount) descending so the most significant rows come first.
    """
    if not txs:
        return "(no transactions)"

    rows = txs
    if sort_by_amount:
        rows = sorted(txs, key=lambda t: abs(t.get("amount_cents", 0) or 0), reverse=True)

    truncated = len(rows) > max_rows
    rows = rows[:max_rows]

    lines = ["date,type,category,vendor,amount_TRY"]
    for t in rows:
        amount_try = (t.get("amount_cents") or 0) / 100
        line = (
            f"{t.get('transaction_date', '')[:10]},"
            f"{t.get('type', '')},"
            f"{t.get('category', '')},"
            f"{(t.get('vendor') or t.get('description') or '')[:30]},"
            f"{amount_try:.2f}"
        )
        lines.append(line)

    suffix = f"\n... ({len(txs) - max_rows} more rows truncated)" if truncated else ""
    return "\n".join(lines) + suffix


def _summarise_pnl(pnl: dict[str, Any]) -> str:
    if not pnl:
        return "(no P&L data)"
    opex_lines = "\n".join(
        f"  {k}: {_fmt_currency(v)}"
        for k, v in (pnl.get("opex") or {}).items()
        if v
    )
    return (
        f"Revenue:      {_fmt_currency(pnl.get('revenue'))}\n"
        f"COGS:         {_fmt_currency(pnl.get('cogs'))}\n"
        f"Gross Profit: {_fmt_currency(pnl.get('gross_profit'))} "
        f"({pnl.get('gross_margin', 0) * 100:.1f}%)\n"
        f"OPEX:\n{opex_lines}\n"
        f"EBITDA:       {_fmt_currency(pnl.get('ebitda'))} "
        f"({pnl.get('ebitda_margin', 0) * 100:.1f}%)\n"
        f"Net Income:   {_fmt_currency(pnl.get('net_income'))} "
        f"({pnl.get('net_margin', 0) * 100:.1f}%)"
    )


def _summarise_cashflow(cf: dict[str, Any]) -> str:
    if not cf:
        return "(no cash flow data)"
    monthly = cf.get("monthly_series") or []
    recent = monthly[-3:] if len(monthly) >= 3 else monthly
    recent_lines = "\n".join(
        f"  {m.get('month', '?')}: in={_fmt_currency(m.get('in'))}, "
        f"out={_fmt_currency(m.get('out'))}, net={_fmt_currency(m.get('net'))}"
        for m in recent
    )
    return (
        f"Operating:  {_fmt_currency(cf.get('operating'))}\n"
        f"Investing:  {_fmt_currency(cf.get('investing'))}\n"
        f"Financing:  {_fmt_currency(cf.get('financing'))}\n"
        f"Net Change: {_fmt_currency(cf.get('net_change'))}\n"
        f"Last 3 months:\n{recent_lines}"
    )


def _summarise_forecast(fc: dict[str, Any]) -> str:
    if not fc:
        return "(no forecast data)"
    scenarios = fc.get("scenarios") or {}
    lines = []
    for name, s in scenarios.items():
        lines.append(
            f"  {name}: 12mo_net={_fmt_currency(s.get('twelve_month_net'))}, "
            f"runway={s.get('runway_months', 'stable')} months"
        )
    return "Forecast scenarios:\n" + "\n".join(lines)


def _summarise_anomalies(anomalies: list[dict[str, Any]], max_items: int = 10) -> str:
    if not anomalies:
        return "(no anomalies detected)"
    critical = [a for a in anomalies if a.get("severity") == "critical"]
    high = [a for a in anomalies if a.get("severity") == "high"]
    top = (critical + high + anomalies)[:max_items]
    lines = [f"Total: {len(anomalies)} anomalies ({len(critical)} critical, {len(high)} high)"]
    for a in top:
        lines.append(
            f"  [{a.get('severity', '?').upper()}] {a.get('title', a.get('anomaly_type', '?'))}"
        )
    return "\n".join(lines)


def _summarise_alerts(alerts: list[dict[str, Any]], max_items: int = 8) -> str:
    if not alerts:
        return "(no alerts)"
    critical = [a for a in alerts if a.get("level") == "critical"]
    top = (critical + alerts)[:max_items]
    lines = [f"Total: {len(alerts)} alerts"]
    for a in top:
        lines.append(f"  [{a.get('level', '?').upper()}] {a.get('message', '')}")
    return "\n".join(lines)


# ── ContextBuilder ────────────────────────────────────────────────────────────

class ContextBuilder:
    """
    Assembles a token-budgeted LLM prompt context from CFOState.

    Each `build_*` method:
    1. Defines an ordered list of (name, text) slices
    2. Greedily fills up to `budget` tokens (highest priority first)
    3. Returns a ContextResult with the assembled text + metadata
    """

    def __init__(self, budget: int = 4096) -> None:
        self.budget = budget

    def _assemble(self, slices: list[tuple[str, str]]) -> ContextResult:
        """
        Greedily assemble slices within token budget.
        Each slice is (name, text). Order = priority.
        """
        included: list[str] = []
        dropped: list[str] = []
        parts: list[str] = []
        used = 0

        for name, text in slices:
            cost = _count_tokens(text)
            if used + cost <= self.budget:
                parts.append(text)
                included.append(name)
                used += cost
            else:
                # Try to fit a truncated version (50% of remaining budget)
                remaining = self.budget - used
                if remaining > 50:
                    # Truncate by characters (rough, avoids re-tokenizing)
                    char_limit = remaining * 4  # 1 token ≈ 4 chars
                    truncated_text = text[:char_limit] + "\n[...truncated]"
                    cost2 = _count_tokens(truncated_text)
                    if used + cost2 <= self.budget:
                        parts.append(truncated_text)
                        included.append(f"{name}(truncated)")
                        used += cost2
                        continue
                dropped.append(name)

        full_text = "\n\n".join(parts)
        return ContextResult(
            text=full_text,
            token_count=used,
            budget=self.budget,
            truncated=len(dropped) > 0,
            slices_included=included,
            slices_dropped=dropped,
        )

    # ── Agent-specific context builders ──────────────────────────────────────

    def build_pnl_context(
        self,
        state: dict[str, Any],
        sector: str = "default",
        benchmark_lines: str | None = None,
    ) -> ContextResult:
        """Context for PnL narrative generation."""
        txs = state.get("transactions") or []
        pnl = state.get("pnl") or {}

        tx_summary = _summarise_transactions(txs, max_rows=30)
        pnl_summary = _summarise_pnl(pnl)

        slices: list[tuple[str, str]] = [
            ("system_role", (
                "You are a Chief Financial Officer (CFO). "
                "Provide a concise, data-driven financial narrative in Turkish. "
                f"Industry sector: {sector}."
            )),
            ("pnl_summary", f"## P&L Summary\n{pnl_summary}"),
        ]

        if benchmark_lines:
            slices.append(("benchmark", f"## Industry Benchmarks\n{benchmark_lines}"))

        slices.append(("transactions_sample", f"## Top Transactions (by amount)\n{tx_summary}"))
        slices.append(("instruction", (
            "Write a 3-4 sentence CFO commentary covering: "
            "revenue quality, margin health, key risks, and one recommendation. "
            "Use specific numbers. Respond in Turkish."
        )))

        result = self._assemble(slices)
        logger.debug("PnL context: %s", result)
        return result

    def build_cashflow_context(self, state: dict[str, Any]) -> ContextResult:
        """Context for CashFlow narrative generation."""
        cf = state.get("cashflow") or {}
        txs = state.get("transactions") or []

        slices: list[tuple[str, str]] = [
            ("system_role", (
                "You are a CFO analyzing cash flow. "
                "Provide a concise Turkish narrative."
            )),
            ("cashflow_summary", f"## Cash Flow Summary\n{_summarise_cashflow(cf)}"),
            ("alerts", f"## Cash Flow Alerts\n{_summarise_alerts(cf.get('alerts') or [])}"),
            ("transactions_sample", f"## Top Cash Transactions\n{_summarise_transactions(txs, max_rows=20)}"),
            ("instruction", (
                "Write a 3-4 sentence CFO commentary on: "
                "operating cash generation, liquidity risk, burn rate trend. "
                "Respond in Turkish."
            )),
        ]

        result = self._assemble(slices)
        logger.debug("CashFlow context: %s", result)
        return result

    def build_forecast_context(self, state: dict[str, Any]) -> ContextResult:
        """Context for Forecast narrative generation."""
        fc = state.get("forecast") or {}
        cf = state.get("cashflow") or {}
        pnl = state.get("pnl") or {}

        slices: list[tuple[str, str]] = [
            ("system_role", (
                "You are a CFO providing a forward-looking financial assessment. "
                "Respond in Turkish."
            )),
            ("pnl_snapshot", f"## Current P&L Snapshot\n{_summarise_pnl(pnl)}"),
            ("cashflow_snapshot", f"## Current Cash Position\n{_summarise_cashflow(cf)}"),
            ("forecast_scenarios", f"## 12-Month Forecast Scenarios\n{_summarise_forecast(fc)}"),
            ("instruction", (
                "Write a 3-4 sentence executive forecast commentary covering: "
                "base case outlook, key upside risk, key downside risk, cash runway. "
                "Respond in Turkish."
            )),
        ]

        result = self._assemble(slices)
        logger.debug("Forecast context: %s", result)
        return result

    def build_anomaly_context(self, state: dict[str, Any]) -> ContextResult:
        """Context for anomaly narrative generation."""
        anomalies = state.get("anomalies") or []
        pnl = state.get("pnl") or {}

        # Top 15 anomalies with full evidence
        top_anomalies = sorted(
            anomalies,
            key=lambda a: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                a.get("severity", "low"), 3
            ),
        )[:15]

        anomaly_detail = json.dumps(
            [
                {
                    "type":        a.get("anomaly_type"),
                    "severity":    a.get("severity"),
                    "title":       a.get("title"),
                    "description": a.get("description"),
                    "confidence":  a.get("confidence"),
                }
                for a in top_anomalies
            ],
            ensure_ascii=False,
            indent=2,
        )

        slices: list[tuple[str, str]] = [
            ("system_role", "You are a CFO reviewing financial anomalies. Respond in Turkish."),
            ("pnl_snapshot", f"## Financial Context\n{_summarise_pnl(pnl)}"),
            ("anomaly_summary", f"## Anomalies (top 15)\n{anomaly_detail}"),
            ("instruction", (
                "Write a 3-4 sentence risk commentary covering: "
                "most critical anomalies, financial exposure estimate, immediate actions. "
                "Respond in Turkish."
            )),
        ]

        result = self._assemble(slices)
        logger.debug("Anomaly context: %s", result)
        return result

    def build_synthesis_context(self, state: dict[str, Any]) -> ContextResult:
        """
        Context for CEO synthesis agent.
        Highest-level summary across all domains — most aggressive truncation.
        """
        slices: list[tuple[str, str]] = [
            ("system_role", (
                "You are a CEO AI advisor. Synthesize financial intelligence into "
                "executive-level strategic insights. Respond in Turkish."
            )),
            ("pnl", f"## P&L\n{_summarise_pnl(state.get('pnl') or {})}"),
            ("cashflow", f"## Cash Flow\n{_summarise_cashflow(state.get('cashflow') or {})}"),
            ("forecast", f"## Forecast\n{_summarise_forecast(state.get('forecast') or {})}"),
            ("anomalies", f"## Anomalies\n{_summarise_anomalies(state.get('anomalies') or [])}"),
            ("alerts", f"## Alerts\n{_summarise_alerts(state.get('triggered_alerts') or [])}"),
            ("instruction", (
                "Write a 5-6 sentence CEO board briefing covering: "
                "financial health, key risks, strategic opportunities, recommended priorities. "
                "Respond in Turkish."
            )),
        ]

        result = self._assemble(slices)
        logger.debug("Synthesis context: %s", result)
        return result


# ── Module-level default instance ─────────────────────────────────────────────

_default_builder = ContextBuilder(budget=4096)


def get_context_builder(budget: int | None = None) -> ContextBuilder:
    """
    Return a ContextBuilder instance.
    Use the default (4096 tokens) or pass a custom budget.
    """
    if budget is None:
        return _default_builder
    return ContextBuilder(budget=budget)
