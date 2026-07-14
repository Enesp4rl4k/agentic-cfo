"""
Financial Ratios Agent — Skill 10 of 10.

Responsibility: Compute the full suite of financial ratios from P&L, Cash Flow,
and Balance Sheet data. Benchmarks each ratio against SMB industry defaults.

Ratio categories:
  1. Liquidity Ratios      — short-term solvency
  2. Profitability Ratios  — earnings quality
  3. Leverage Ratios       — debt & capital structure
  4. Efficiency Ratios     — asset utilisation & working capital
  5. Cash Flow Ratios      — cash-based quality checks

Each ratio includes:
  - value:     computed float
  - benchmark: industry median for KOBİ (Turkish SMB)
  - status:    "good" | "warning" | "critical"
  - label:     human-readable name (Turkish + English)

GPT-4o synthesises a CFO-level ratio scorecard narrative.

done_when: state['financial_ratios']['liquidity'] is populated with at least
           current_ratio and quick_ratio.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)

# ── SMB Industry Benchmarks (Turkish KOBİ defaults) ─────────────────────────
# Source: TCMB sektör raporları + OECD SMB benchmarks
BENCHMARKS = {
    # Liquidity
    "current_ratio":          {"good": 1.5, "warning": 1.0,  "unit": "x"},
    "quick_ratio":            {"good": 1.0, "warning": 0.7,  "unit": "x"},
    "cash_ratio":             {"good": 0.5, "warning": 0.2,  "unit": "x"},
    # Profitability
    "gross_margin":           {"good": 0.30, "warning": 0.15, "unit": "%"},
    "net_margin":             {"good": 0.08, "warning": 0.02, "unit": "%"},
    "ebitda_margin":          {"good": 0.12, "warning": 0.05, "unit": "%"},
    "roa":                    {"good": 0.05, "warning": 0.01, "unit": "%"},
    "roe":                    {"good": 0.10, "warning": 0.04, "unit": "%"},
    "roce":                   {"good": 0.08, "warning": 0.03, "unit": "%"},
    # Leverage
    "debt_to_equity":         {"good": 1.0,  "warning": 2.0,  "unit": "x", "lower_is_better": False},
    "debt_ratio":             {"good": 0.4,  "warning": 0.6,  "unit": "%", "lower_is_better": False},
    "interest_coverage":      {"good": 3.0,  "warning": 1.5,  "unit": "x"},
    # Efficiency
    "asset_turnover":         {"good": 1.0,  "warning": 0.5,  "unit": "x"},
    "receivables_turnover":   {"good": 12.0, "warning": 8.0,  "unit": "x"},
    "inventory_turnover":     {"good": 8.0,  "warning": 4.0,  "unit": "x"},
    "payables_turnover":      {"good": 8.0,  "warning": 5.0,  "unit": "x"},
    "dso":                    {"good": 30,   "warning": 60,   "unit": "days", "lower_is_better": False},
    "dio":                    {"good": 45,   "warning": 90,   "unit": "days", "lower_is_better": False},
    "dpo":                    {"good": 30,   "warning": 45,   "unit": "days"},
    "cash_conversion_cycle":  {"good": 45,   "warning": 90,   "unit": "days", "lower_is_better": False},
    # Cash Flow
    "operating_cf_ratio":     {"good": 0.10, "warning": 0.0,  "unit": "x"},
    "cash_flow_coverage":     {"good": 1.5,  "warning": 1.0,  "unit": "x"},
}


def _status(name: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    bm = BENCHMARKS.get(name, {})
    lower_is_better = bm.get("lower_is_better", True)
    good = bm.get("good")
    warning = bm.get("warning")
    if good is None:
        return "n/a"
    if lower_is_better is False:
        # Higher is worse (e.g. debt_to_equity, DSO)
        if value <= good:
            return "good"
        elif value <= warning:
            return "warning"
        else:
            return "critical"
    else:
        # Higher is better
        if value >= good:
            return "good"
        elif value >= warning:
            return "warning"
        else:
            return "critical"


def _ratio(name: str, value: float | None) -> dict[str, Any]:
    bm = BENCHMARKS.get(name, {})
    return {
        "value": round(value, 4) if value is not None else None,
        "benchmark": bm.get("good"),
        "unit": bm.get("unit", "x"),
        "status": _status(name, value),
    }


def _safe_div(num: float, den: float, default: float | None = None) -> float | None:
    if den == 0:
        return default
    return num / den


def _compute_ratios(
    pnl: dict[str, Any],
    cashflow: dict[str, Any],
    bs: dict[str, Any],
) -> dict[str, Any]:
    """Pure computation — no LLM, no I/O."""

    # Shortcuts
    revenue = pnl.get("revenue", 0) or 1  # avoid div/0
    cogs = pnl.get("cogs", 0)
    gross_profit = pnl.get("gross_profit", 0)
    ebitda = pnl.get("ebitda", 0)
    net_income = pnl.get("net_income", 0)
    total_expenses = pnl.get("total_expenses", 0)
    loan_payments = pnl.get("loan_payments", 0)

    operating_cf = cashflow.get("operating", 0)
    net_cf = cashflow.get("net_change", 0)

    assets = bs.get("assets", {})
    liabilities = bs.get("liabilities", {})
    equity = bs.get("equity", {})

    total_assets = max(assets.get("total", 0), 1)
    total_liabilities = liabilities.get("total", 0)
    total_equity = max(equity.get("total", 0), 1)

    curr_assets = assets.get("current", {})
    curr_liabs = liabilities.get("current", {})

    cash = curr_assets.get("cash", 0)
    accounts_receivable = curr_assets.get("accounts_receivable", 0)
    inventory = curr_assets.get("inventory", 0)
    total_current_assets = curr_assets.get("total", 0)
    total_current_liabilities = max(curr_liabs.get("total", 0), 1)

    accounts_payable = max(curr_liabs.get("accounts_payable", 0), 1)
    short_term_debt = curr_liabs.get("short_term_debt", 0)

    # ── 1. Liquidity ─────────────────────────────────────────────────────────
    current_ratio = _safe_div(total_current_assets, total_current_liabilities)
    quick_ratio = _safe_div(total_current_assets - inventory, total_current_liabilities)
    cash_ratio = _safe_div(cash, total_current_liabilities)

    # ── 2. Profitability ──────────────────────────────────────────────────────
    gross_margin = _safe_div(gross_profit, revenue)
    net_margin = _safe_div(net_income, revenue)
    ebitda_margin = _safe_div(ebitda, revenue)
    roa = _safe_div(net_income, total_assets)
    roe = _safe_div(net_income, total_equity)
    # ROCE: EBIT / (Total Assets - Current Liabilities)
    capital_employed = max(total_assets - total_current_liabilities, 1)
    roce = _safe_div(ebitda, capital_employed)  # using EBITDA as EBIT proxy

    # ── 3. Leverage ───────────────────────────────────────────────────────────
    debt_to_equity = _safe_div(total_liabilities, total_equity)
    debt_ratio = _safe_div(total_liabilities, total_assets)
    # Interest coverage: EBITDA / interest expense
    # Proxy: ebitda / (loan_payments * 0.3) — assuming 30% of loan payments = interest
    interest_estimate = max(loan_payments * 0.3, 1)
    interest_coverage = _safe_div(ebitda, interest_estimate)

    # ── 4. Efficiency ─────────────────────────────────────────────────────────
    asset_turnover = _safe_div(revenue, total_assets)
    receivables_turnover = _safe_div(revenue, max(accounts_receivable, 1))
    inventory_turnover = _safe_div(cogs, max(inventory, 1))
    payables_turnover = _safe_div(total_expenses, accounts_payable)

    # Days metrics
    dso = _safe_div(accounts_receivable * 365, revenue)
    dio = _safe_div(inventory * 365, max(cogs, 1))
    dpo = _safe_div(accounts_payable * 365, total_expenses) if total_expenses else 0.0
    ccc = (dso or 0) + (dio or 0) - (dpo or 0)

    # ── 5. Cash Flow ──────────────────────────────────────────────────────────
    operating_cf_ratio = _safe_div(operating_cf, revenue)
    cash_flow_coverage = _safe_div(operating_cf, max(total_current_liabilities, 1))

    return {
        "liquidity": {
            "current_ratio": _ratio("current_ratio", current_ratio),
            "quick_ratio": _ratio("quick_ratio", quick_ratio),
            "cash_ratio": _ratio("cash_ratio", cash_ratio),
        },
        "profitability": {
            "gross_margin": _ratio("gross_margin", gross_margin),
            "net_margin": _ratio("net_margin", net_margin),
            "ebitda_margin": _ratio("ebitda_margin", ebitda_margin),
            "roa": _ratio("roa", roa),
            "roe": _ratio("roe", roe),
            "roce": _ratio("roce", roce),
        },
        "leverage": {
            "debt_to_equity": _ratio("debt_to_equity", debt_to_equity),
            "debt_ratio": _ratio("debt_ratio", debt_ratio),
            "interest_coverage": _ratio("interest_coverage", interest_coverage),
        },
        "efficiency": {
            "asset_turnover": _ratio("asset_turnover", asset_turnover),
            "receivables_turnover": _ratio("receivables_turnover", receivables_turnover),
            "inventory_turnover": _ratio("inventory_turnover", inventory_turnover),
            "payables_turnover": _ratio("payables_turnover", payables_turnover),
            "dso_days": _ratio("dso", dso),
            "dio_days": _ratio("dio", dio),
            "dpo_days": _ratio("dpo", dpo),
            "cash_conversion_cycle": _ratio("cash_conversion_cycle", ccc),
        },
        "cash_flow": {
            "operating_cf_ratio": _ratio("operating_cf_ratio", operating_cf_ratio),
            "cash_flow_coverage": _ratio("cash_flow_coverage", cash_flow_coverage),
        },
    }


def _build_scorecard(ratios: dict[str, Any]) -> dict[str, int]:
    """Count good/warning/critical across all ratios."""
    counts: dict[str, int] = {"good": 0, "warning": 0, "critical": 0, "na": 0}
    for category in ratios.values():
        for r in category.values():
            s = r.get("status", "n/a")
            if s == "good":
                counts["good"] += 1
            elif s == "warning":
                counts["warning"] += 1
            elif s == "critical":
                counts["critical"] += 1
            else:
                counts["na"] += 1
    return counts


async def _generate_ratios_narrative(
    ratios: dict[str, Any],
    scorecard: dict[str, int],
    lang: str,
    settings,
) -> str:
    from app.agents.i18n import get_language_instruction
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=800,
        api_key=settings.openai_api_key,
    )
    lang_instruction = get_language_instruction(lang)

    liq = ratios["liquidity"]
    prof = ratios["profitability"]
    lev = ratios["leverage"]
    eff = ratios["efficiency"]

    summary = (
        f"Scorecard: {scorecard['good']} good / {scorecard['warning']} warning / {scorecard['critical']} critical\n\n"
        f"LIQUIDITY:\n"
        f"  Current Ratio: {liq['current_ratio']['value']} (benchmark: ≥{liq['current_ratio']['benchmark']})\n"
        f"  Quick Ratio: {liq['quick_ratio']['value']} (benchmark: ≥{liq['quick_ratio']['benchmark']})\n\n"
        f"PROFITABILITY:\n"
        f"  Gross Margin: {prof['gross_margin']['value']:.1%} (benchmark: ≥{prof['gross_margin']['benchmark']:.0%})\n"
        f"  Net Margin: {prof['net_margin']['value']:.1%} (benchmark: ≥{prof['net_margin']['benchmark']:.0%})\n"
        f"  ROE: {prof['roe']['value']:.1%} (benchmark: ≥{prof['roe']['benchmark']:.0%})\n"
        f"  ROCE: {prof['roce']['value']:.1%} (benchmark: ≥{prof['roce']['benchmark']:.0%})\n\n"
        f"BORÇ YAPISI:\n"
        f"  Borç/Öz Kaynak: {lev['debt_to_equity']['value']:.2f}x (hedef: ≤{lev['debt_to_equity']['benchmark']}x)\n"
        f"  Faiz Karşılama: {lev['interest_coverage']['value']:.1f}x (hedef: ≥{lev['interest_coverage']['benchmark']}x)\n\n"
        f"VERİMLİLİK:\n"
        f"  Alacak Devir Süresi: {eff['dso_days']['value']:.0f} gün\n"
        f"  Nakit Dönüşüm Döngüsü: {eff['cash_conversion_cycle']['value']:.0f} gün\n"
    )

    messages = [
        SystemMessage(content=(
            "You are an experienced CFO and financial analyst. "
            "Evaluate the financial ratio scorecard below. "
            "Identify the most critical issues and strengths. "
            f"Provide 3 concrete recommendations for management (5-7 sentences). {lang_instruction}"
        )),
        HumanMessage(content=f"Financial Ratio Summary:\n{summary}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_financial_ratios(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """
    Financial Ratios Skill.
    done_when: state['financial_ratios']['liquidity']['current_ratio'] is populated.
    """
    from app.agents.i18n import validate_language
    pnl = state.get("pnl", {})
    cashflow = state.get("cashflow", {})
    bs = state.get("balance_sheet", {})

    if not pnl:
        return SkillResult(
            ok=False,
            detail="P&L data missing — cannot compute financial ratios.",
            halt=False,
        )

    if not bs:
        return SkillResult(
            ok=False,
            detail="Balance sheet data missing — some ratios cannot be computed.",
            halt=False,
        )

    try:
        settings = get_settings()
        lang = validate_language(config.language)
        ratios = _compute_ratios(pnl, cashflow, bs)
        scorecard = _build_scorecard(ratios)
        narrative = await _generate_ratios_narrative(ratios, scorecard, lang, settings)

        has_critical = scorecard["critical"] >= 3
        confidence = 0.88 if not has_critical else 0.75

        financial_ratios = {
            **ratios,
            "scorecard": scorecard,
            "narrative": narrative,
            "narrative_lang": lang,
        }

        return SkillResult(
            ok=True,
            patch={"financial_ratios": financial_ratios},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Financial ratios: {scorecard['good']} good, "
                f"{scorecard['warning']} warning, "
                f"{scorecard['critical']} critical [{lang}]"
            ),
        )
    except Exception as exc:
        logger.exception("Financial ratios agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Financial ratios error: {exc}")
