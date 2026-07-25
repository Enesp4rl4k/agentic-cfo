"""
NL Query Engine — Phase 6.1

Parses natural language financial questions into structured queries,
executes them against dashboard/analysis data, and returns Turkish explanations.

Architecture:
  UserQuery (Turkish/English)
    → IntentClassifier    (rule-based + keyword, no LLM cost)
    → MetricExtractor     (finds metric name, time filter, dimension)
    → QueryExecutor       (fetches data from DB/dashboard JSON)
    → InsightGenerator    (LLM → Turkish explanation + follow-ups)

Supported intents:
  - metric_lookup    : "Nakit akışım ne?"
  - comparison       : "En yüksek gider kategorim hangisi?"
  - trend            : "Gelir geçen aya göre nasıl değişti?"
  - forecast_query   : "3 ay sonra nakit durumum ne olur?"
  - scenario         : "Kira %20 artarsa ne olur?"
  - anomaly_query    : "Bu ayki anomaliler neler?"
  - runway_query     : "Paramız ne zaman biter?"

Usage:
    result = await nl_query(query="Nakit akışım ne?", job_id="...", db=db)
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Intent patterns (rule-based, zero LLM cost) ───────────────────────────────

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("runway_query",   [
        r"ne zaman biter", r"runway", r"kaç ay", r"kac ay", r"para biter",
        r"nakit tüken", r"ne kadar dayanır",
    ]),
    ("scenario",       [
        r"artarsa", r"azalırsa", r"düşerse", r"artarsa ne", r"kesersek",
        r"what if", r"if .* increase", r"if .* decrease",
        r"değişirse", r"olursa ne", r"etkisi ne",
    ]),
    ("forecast_query", [
        r"tahmin", r"forecast", r"gelecek ay", r"gelecek \d+ ay",
        r"sonra ne", r"ilerleyen", r"projeksyon",
        r"\d+ ay sonra", r"ay sonra ne", r"ileriki ay",
    ]),
    ("anomaly_query",  [
        r"anomali", r"anormal", r"şüpheli", r"duplikat", r"fraud",
        r"unusual", r"olağandışı", r"tekrar eden",
    ]),
    ("trend",          [
        r"geçen ay", r"önceki ay", r"değişti", r"büyüme", r"düşüş", r"artış",
        r"trend", r"yüzde kaç", r"nasıl değişti", r"kıyasla",
    ]),
    ("comparison",     [
        r"en yüksek", r"en düşük", r"en pahalı", r"en fazla", r"en az",
        r"hangisi", r"karşılaştır", r"fark", r"top", r"highest", r"lowest",
    ]),
    ("metric_lookup",  [
        r"ciro", r"gelir", r"gider", r"kâr", r"kar", r"brüt", r"net", r"ebitda",
        r"nakit", r"akış", r"vergi", r"maaş", r"kira", r"ne kadar", r"kaç",
        r"revenue", r"profit", r"cash", r"expense", r"margin",
    ]),
]


def classify_intent(query: str) -> str:
    q_lower = query.lower()
    for intent, patterns in _INTENT_PATTERNS:
        for pat in patterns:
            if re.search(pat, q_lower):
                return intent
    return "metric_lookup"  # default


# ── Metric extraction ─────────────────────────────────────────────────────────

_METRIC_MAP: dict[str, tuple[str, str]] = {
    # Turkish keyword → (path_in_dashboard, display_name)
    "gelir":           ("pnl.revenue",           "Gelir"),
    "ciro":            ("pnl.revenue",           "Ciro"),
    "brüt kâr":        ("pnl.gross_profit",      "Brüt Kâr"),
    "brüt kar":        ("pnl.gross_profit",      "Brüt Kâr"),
    "net kâr":         ("pnl.net_income",        "Net Kâr"),
    "net kar":         ("pnl.net_income",        "Net Kâr"),
    "ebitda":          ("pnl.ebitda",            "FAVÖK"),
    "nakit akış":      ("cashflow.net_change",   "Net Nakit Akışı"),
    "nakit":           ("cashflow.net_change",   "Net Nakit"),
    "faaliyet nakit":  ("cashflow.operating",    "Faaliyet Nakit Akışı"),
    "maaş":            ("pnl.opex.salary",       "Maaş Giderleri"),
    "kira":            ("pnl.opex.rent",         "Kira Giderleri"),
    "pazarlama":       ("pnl.opex.marketing",    "Pazarlama Giderleri"),
    "teknoloji":       ("pnl.opex.technology",   "Teknoloji Giderleri"),
    "vergi":           ("pnl.tax",               "Vergi"),
    "revenue":         ("pnl.revenue",           "Revenue"),
    "profit":          ("pnl.net_income",        "Net Income"),
    "cash":            ("cashflow.net_change",   "Net Cash"),
}


def extract_metric(query: str) -> tuple[str | None, str | None]:
    """Returns (path, display_name) or (None, None)."""
    q_lower = query.lower()
    # Longest match first to avoid partial matches
    for kw in sorted(_METRIC_MAP, key=len, reverse=True):
        if kw in q_lower:
            return _METRIC_MAP[kw]
    return None, None


def get_nested(data: dict, path: str) -> Any:
    """Traverse dot-separated path in nested dict."""
    parts = path.split(".")
    current = data
    for p in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(p)
    return current


# ── Query executor ─────────────────────────────────────────────────────────────

def execute_nl_query(
    query: str,
    dashboard: dict[str, Any],
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Execute a natural language query against dashboard data.

    Returns structured result:
    {
      "intent": str,
      "metric_path": str | None,
      "metric_display": str | None,
      "value": Any,
      "context": dict,
      "raw_query": str,
    }
    """
    intent = classify_intent(query)
    metric_path, metric_display = extract_metric(query)

    value: Any = None
    context: dict[str, Any] = {}

    if intent == "metric_lookup" and metric_path:
        value = get_nested(dashboard, metric_path)
        context["metric"] = metric_display

    elif intent == "runway_query":
        forecast = dashboard.get("forecast") or {}
        scenarios = forecast.get("scenarios") or {}
        base = scenarios.get("base") or {}
        value = base.get("runway_months")
        context["scenario"] = "Baz"
        context["twelve_month_net"] = base.get("twelve_month_net")
        mc = forecast.get("monte_carlo") or {}
        if mc:
            context["runway_risk_pct"] = mc.get("runway_risk_pct")

    elif intent == "comparison":
        pnl = dashboard.get("pnl") or {}
        opex = pnl.get("opex") or {}
        if opex:
            sorted_opex = sorted(opex.items(), key=lambda x: x[1] or 0, reverse=True)
            value = sorted_opex[:3]  # Top 3
            context["type"] = "top_3_expenses"

    elif intent == "trend":
        cashflow = dashboard.get("cashflow") or {}
        series = cashflow.get("monthly_series") or []
        if len(series) >= 2:
            last = series[-1]
            prev = series[-2]
            net_change = last["net"] - prev["net"]
            pct = ((last["net"] - prev["net"]) / abs(prev["net"]) * 100) if prev["net"] != 0 else 0
            value = {"last_month": last, "prev_month": prev, "net_change": net_change, "pct_change": round(pct, 1)}
            context["type"] = "month_over_month"

    elif intent == "forecast_query":
        forecast = dashboard.get("forecast") or {}
        scenarios = forecast.get("scenarios") or {}
        value = {k: {
            "label": v.get("label"),
            "twelve_month_net": v.get("twelve_month_net"),
            "runway_months": v.get("runway_months"),
        } for k, v in scenarios.items()}
        mc = forecast.get("monte_carlo") or {}
        if mc:
            context["monte_carlo_p50"] = mc.get("p50_12m_net")
            context["monte_carlo_p10"] = mc.get("p10_12m_net")
            context["monte_carlo_p90"] = mc.get("p90_12m_net")

    elif intent == "anomaly_query":
        value = dashboard.get("anomalies") or []
        context["count"] = len(value)

    elif intent == "scenario":
        # Extract % and subject from query for what-if hint
        pct_match = re.search(r"(%\s*\d+|\d+\s*%|yüzde\s*\d+)", query.lower())
        pct = pct_match.group(0) if pct_match else "?"
        context["type"] = "scenario_hint"
        context["detected_pct"] = pct
        value = None  # LLM will handle full scenario simulation

    return {
        "intent":          intent,
        "metric_path":     metric_path,
        "metric_display":  metric_display,
        "value":           value,
        "context":         context,
        "raw_query":       query,
    }


# ── Insight generator ──────────────────────────────────────────────────────────

async def generate_nl_insight(
    query: str,
    query_result: dict[str, Any],
    dashboard: dict[str, Any],
    transactions: list[dict[str, Any]],
    settings: Any,
) -> dict[str, Any]:
    """
    Use LLM to generate a Turkish explanation for the query result.
    Also suggests 2-3 follow-up questions.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.3,
        max_tokens=600,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    # Build compact context
    pnl = dashboard.get("pnl") or {}
    cf  = dashboard.get("cashflow") or {}
    fc  = dashboard.get("forecast") or {}

    def fmt(v: Any) -> str:
        if isinstance(v, (int, float)):
            return f"{v / 100:,.0f} TL" if abs(v) > 100 else f"{v:.2f}"
        return str(v)

    compact_context = (
        f"Gelir: {fmt(pnl.get('revenue', 0))} | "
        f"Net Kâr: {fmt(pnl.get('net_income', 0))} ({pnl.get('net_margin', 0)*100:.1f}%) | "
        f"Net Nakit: {fmt(cf.get('net_change', 0))} | "
        f"Intent: {query_result['intent']} | "
        f"Sorgu sonucu: {str(query_result['value'])[:300]}"
    )

    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir CFO asistanısın. Kullanıcının finansal sorusuna "
            "Türkçe, kısa ve net bir cevap ver. "
            "Yanıt şu yapıda olsun:\n"
            "1. Direkt yanıt (1-2 cümle, rakam içermeli)\n"
            "2. Kısa yorum (1 cümle — iyi mi, kötü mü, neden?)\n"
            "3. Öneri veya sonraki adım (1 cümle)\n"
            "4. Takip soruları: 2 kısa soru öner (JSON array olarak, 'follow_ups' anahtarıyla)\n\n"
            "Yanıtını şu JSON formatında ver:\n"
            '{"answer": "...", "follow_ups": ["soru1", "soru2"]}'
        )),
        HumanMessage(content=(
            f"Kullanıcı sorusu: {query}\n\n"
            f"Finansal bağlam: {compact_context}"
        )),
    ]

    try:
        import json
        response = await llm.ainvoke(messages)
        content = response.content.strip()

        # Try to parse JSON response
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            answer = parsed.get("answer", content)
            follow_ups = parsed.get("follow_ups", [])
        else:
            answer = content
            follow_ups = []

        return {
            "answer":     answer,
            "follow_ups": follow_ups[:3],
            "intent":     query_result["intent"],
            "value":      query_result["value"],
            "context":    query_result["context"],
        }

    except Exception as exc:
        logger.warning("NL insight generation failed: %s", exc)
        # Fallback: return raw value as text
        val = query_result.get("value")
        if isinstance(val, (int, float)) and val > 1000:
            answer = f"{query_result.get('metric_display', 'Değer')}: {val/100:,.0f} TL"
        elif val is not None:
            answer = f"Sonuç: {val}"
        else:
            answer = "Bu soruyu yanıtlamak için yeterli veri bulunamadı."

        return {
            "answer":     answer,
            "follow_ups": [],
            "intent":     query_result["intent"],
            "value":      val,
            "context":    query_result["context"],
        }
