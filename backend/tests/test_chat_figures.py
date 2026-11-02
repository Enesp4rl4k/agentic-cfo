"""Plan v9 §K0 — chat reads the stored dashboard in lira.

The context builder divided the dashboard's lira by 100 again: on the demo
company (revenue ₺9.799.500, hand-summed from the file) the model read ₺97,995.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import _build_financial_context, dogrudan_cevap
from app.agents.data_ingestion import _tablo_ekstresi
from app.agents.pnl_agent import _compute_pnl
from app.agents.report_agent import _build_dashboard_json

DEMO = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"


@pytest.fixture
def dashboard() -> dict:
    txs = _tablo_ekstresi(str(DEMO))
    return _build_dashboard_json({"transactions": txs, "pnl": _compute_pnl(txs)})


def test_the_model_reads_the_real_revenue(dashboard):
    context = _build_financial_context(dashboard, [])
    assert "Revenue: ₺9,799,500" in context
    assert "EBITDA: ₺5,213,800" in context


def test_a_transaction_in_the_context_is_still_converted_from_kurus(dashboard):
    tx = {"amount_cents": 28_500_00, "type": "expense", "category": "rent",
          "description": "Kira", "transaction_date": "2024-01-08"}
    assert "₺28,500" in _build_financial_context(dashboard, [tx])


@pytest.mark.parametrize(("soru", "beklenen"), [
    ("Geçen yılki toplam gelirim ne kadar?", "₺9.799.500"),
    ("FAVÖK ne kadar?", "₺5.213.800"),
    ("Net kârım nedir?", "₺5.213.800"),
    ("En büyük gider kalemim hangisi?", "maaş ve ücretler"),
])
def test_questions_the_analysis_settles(dashboard, soru, beklenen):
    assert beklenen in (dogrudan_cevap(soru, dashboard) or "")


@pytest.mark.parametrize("soru", [
    "Geliri nasıl artırırım?",
    "Gelir neden düştü?",
    "Bu yıl hangi pazara açılmalıyız?",
])
def test_a_question_that_only_mentions_a_figure_is_not_answered_with_it(dashboard, soru):
    assert dogrudan_cevap(soru, dashboard) is None


def test_no_figure_no_answer():
    assert dogrudan_cevap("Toplam gelirim ne kadar?", {"pnl": {}}) is None
    assert dogrudan_cevap("En büyük gider hangisi?", {"pnl": {"opex": {}}}) is None
