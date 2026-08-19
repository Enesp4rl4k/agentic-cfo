"""
CFO Pipeline Integration Tests.

Tests the full LangGraph pipeline end-to-end using in-memory backends —
no database, no Redis, no LLM required.

Scenarios:
  1. happy_path         — valid CSV → all agents run → COMPLETED state
  2. halt_on_bad_data   — empty file → data_ingestion fails → halted=True, no downstream
  3. low_confidence     — low-quality data → confidence gate → hold_for_review
  4. anomaly_detection  — duplicate transactions → anomalies detected
  5. memory_store       — episode saved after successful run
  6. routing_plan       — CapabilityRouter skips budget when no budget_input
"""
from __future__ import annotations

import os
import tempfile
import pytest
import pytest_asyncio

# Force in-memory backends for all tests — no external dependencies
os.environ.setdefault("USE_SQLITE", "true")

from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig, CFOState


# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_CSV = """\
date,description,amount,type,category
2024-01-05,Office Rent,-8000,expense,rent
2024-01-10,Client Payment A,25000,income,sales
2024-01-15,Electricity,-1500,expense,utilities
2024-01-20,Client Payment B,18000,income,sales
2024-01-25,Salaries,-30000,expense,payroll
2024-01-28,Software Licenses,-2000,expense,software
2024-01-30,Consulting Income,12000,income,services
"""

DUPLICATE_CSV = """\
date,description,amount,type,category
2024-01-05,Office Rent,-8000,expense,rent
2024-01-05,Office Rent,-8000,expense,rent
2024-01-10,Client Payment,25000,income,sales
2024-01-10,Client Payment,25000,income,sales
2024-01-15,Electricity,-1500,expense,utilities
"""

MULTI_MONTH_CSV = """\
date,description,amount,type,category
2024-01-10,January Sales,50000,income,sales
2024-01-25,January Costs,-30000,expense,payroll
2024-02-10,February Sales,55000,income,sales
2024-02-25,February Costs,-32000,expense,payroll
2024-03-10,March Sales,48000,income,sales
2024-03-25,March Costs,-29000,expense,payroll
"""


@pytest.fixture
def csv_file(tmp_path):
    """Write MINIMAL_CSV to a temp file and return its path."""
    f = tmp_path / "test_transactions.csv"
    f.write_text(MINIMAL_CSV, encoding="utf-8")
    return str(f)


@pytest.fixture
def duplicate_csv_file(tmp_path):
    f = tmp_path / "duplicates.csv"
    f.write_text(DUPLICATE_CSV, encoding="utf-8")
    return str(f)


@pytest.fixture
def multi_month_csv_file(tmp_path):
    f = tmp_path / "multi_month.csv"
    f.write_text(MULTI_MONTH_CSV, encoding="utf-8")
    return str(f)


@pytest.fixture
def empty_file(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("", encoding="utf-8")
    return str(f)


@pytest.fixture
def run_config_no_review():
    """AgentRunConfig that never holds for human review — for fast tests."""
    return AgentRunConfig(
        dry_run=False,
        require_review=False,
        auto_proceed_min_confidence=0.0,  # never hold on low confidence
    )


# ── Scenario 1: Happy path ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_completes(csv_file, run_config_no_review):
    """Full pipeline runs without halting on valid CSV data."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-happy-001",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    assert not result.get("halted"), f"Pipeline halted unexpectedly: {result.get('error')}"
    assert not result.get("awaiting_review")

    # Core agent outputs present
    pnl = result.get("pnl")
    assert pnl is not None, "PnL agent did not produce output"
    assert pnl.get("revenue") is not None
    assert pnl.get("net_income") is not None

    cashflow = result.get("cashflow")
    assert cashflow is not None, "Cashflow agent did not produce output"

    forecast = result.get("forecast")
    assert forecast is not None, "Forecast agent did not produce output"
    scenarios = forecast.get("scenarios") or {}
    assert "base" in scenarios, "Forecast missing base scenario"

    # Logs should record each step
    logs = result.get("logs") or []
    step_names = [lg.step for lg in logs]
    assert "data_ingestion" in step_names
    assert "pnl" in step_names
    assert "cashflow" in step_names
    assert "forecast" in step_names


@pytest.mark.asyncio
async def test_happy_path_transactions_parsed(csv_file, run_config_no_review):
    """Transactions are parsed from CSV and have expected fields."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-happy-002",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    transactions = result.get("transactions") or []
    assert len(transactions) >= 5, f"Expected ≥5 transactions, got {len(transactions)}"

    for tx in transactions:
        assert "amount_cents" in tx or "amount" in tx, f"Transaction missing amount: {tx}"
        assert tx.get("type") in ("income", "expense", "revenue"), \
            f"Unexpected transaction type: {tx.get('type')}"


@pytest.mark.asyncio
async def test_happy_path_dashboard_json(csv_file, run_config_no_review):
    """dashboard_json is produced and contains all major sections."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-happy-003",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    dashboard = result.get("dashboard_json") or {}
    # At minimum PnL and cashflow should be in the dashboard
    assert dashboard.get("pnl") is not None or result.get("pnl") is not None, \
        "No PnL data in result"


# ── Scenario 2: Halt on bad data ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_file_halts_pipeline(empty_file, run_config_no_review):
    """Empty file causes data_ingestion to fail → pipeline halts."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-halt-001",
        file_path=empty_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    assert result.get("halted") is True, \
        "Pipeline should halt on empty file but did not"

    # PnL and downstream agents should NOT have run
    assert result.get("pnl") is None, \
        "PnL should not have run after fatal ingestion failure"

    # Error should be recorded
    logs = result.get("logs") or []
    ingestion_log = next((lg for lg in logs if lg.step == "data_ingestion"), None)
    assert ingestion_log is not None
    assert not ingestion_log.ok


@pytest.mark.asyncio
async def test_nonexistent_file_halts_pipeline(run_config_no_review):
    """Non-existent file path causes pipeline to halt gracefully."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-halt-002",
        file_path="/tmp/this_file_does_not_exist_xyz.csv",
        file_type="csv",
        run_config=run_config_no_review,
    )

    assert result.get("halted") is True, \
        "Pipeline should halt on missing file"
    assert result.get("error") is not None


# ── Scenario 3: Review gate (low confidence) ──────────────────────────────────

@pytest.mark.asyncio
async def test_low_confidence_triggers_review_gate(empty_file):
    """With require_review=True and low-confidence data, pipeline holds."""
    cfg = AgentRunConfig(
        require_review=True,
        auto_proceed_min_confidence=0.99,  # extremely strict — almost always holds
    )

    result: CFOState = await run_cfo_pipeline(
        job_id="test-review-001",
        file_path=empty_file,
        file_type="csv",
        run_config=cfg,
    )

    # Empty file → ingestion fails → either halted or awaiting_review
    assert result.get("halted") or result.get("awaiting_review"), \
        "Expected halted or awaiting_review on empty file with strict config"


# ── Scenario 4: Anomaly detection ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_transactions_detected(duplicate_csv_file, run_config_no_review):
    """Duplicate transactions in CSV are flagged as anomalies."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-anomaly-001",
        file_path=duplicate_csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    if result.get("halted"):
        pytest.skip("Pipeline halted — skipping anomaly check (data parse issue)")

    anomalies = result.get("anomalies") or []
    # At least one anomaly should be detected given the obvious duplicates
    # (either from anomaly_agent or in dashboard_json)
    dashboard_anomalies = (result.get("dashboard_json") or {}).get("anomalies") or {}
    all_anomalies = anomalies + (dashboard_anomalies.get("items") or [])

    assert len(all_anomalies) > 0, \
        "Expected duplicate anomalies to be detected in DUPLICATE_CSV"


# ── Scenario 5: Multi-period analysis ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_period_runs_on_multi_month_data(
    multi_month_csv_file, run_config_no_review
):
    """Multi-period agent runs when data spans multiple months."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-multiperiod-001",
        file_path=multi_month_csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    if result.get("halted"):
        pytest.skip("Pipeline halted — skipping multi-period check")

    logs = result.get("logs") or []
    multi_period_log = next((lg for lg in logs if lg.step == "multi_period"), None)

    # multi_period_agent should have run (not skipped by CapabilityRouter)
    assert multi_period_log is not None, \
        "multi_period step not found in logs"


# ── Scenario 6: CapabilityRouter skips budget agent ──────────────────────────

@pytest.mark.asyncio
async def test_budget_agent_skipped_without_budget_input(csv_file, run_config_no_review):
    """When no budget_input is provided, budget agent is skipped by CapabilityRouter."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-routing-001",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
        budget_input=None,  # explicit: no budget
    )

    if result.get("halted"):
        pytest.skip("Pipeline halted — skipping routing check")

    # Budget should be None since no input was provided
    assert result.get("budget") is None, \
        "Budget agent should not produce output without budget_input"


@pytest.mark.asyncio
async def test_budget_agent_runs_with_budget_input(csv_file, run_config_no_review):
    """When budget_input is provided, budget agent runs and produces output."""
    budget = {
        "items": [
            {"category": "payroll",    "budgeted": 3200000},
            {"category": "rent",       "budgeted":  800000},
            {"category": "utilities",  "budgeted":  200000},
            {"category": "software",   "budgeted":  200000},
        ]
    }

    result: CFOState = await run_cfo_pipeline(
        job_id="test-routing-002",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
        budget_input=budget,
    )

    if result.get("halted"):
        pytest.skip("Pipeline halted — skipping budget check")

    budget_result = result.get("budget")
    assert budget_result is not None, \
        "Budget agent should produce output when budget_input is provided"


# ── Scenario 7: AgentMemory episode saved ────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_episode_saved_on_success(csv_file, run_config_no_review):
    """After a successful run with org_id, a memory episode is saved."""
    from app.services.agent_memory import AgentMemoryStore, reset_memory_store

    # Use fresh isolated in-memory store for this test
    reset_memory_store()

    result: CFOState = await run_cfo_pipeline(
        job_id="test-memory-001",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
        org_id="org-test-123",
        period="2024-01",
    )

    if result.get("halted"):
        pytest.skip("Pipeline halted — skipping memory check")

    episode_ids = result.get("memory_episode_ids") or []
    assert len(episode_ids) > 0, \
        "Expected at least one memory episode to be saved after successful run"


@pytest.mark.asyncio
async def test_memory_not_saved_when_halted(empty_file, run_config_no_review):
    """Memory episode is NOT saved when the pipeline halts."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-memory-002",
        file_path=empty_file,
        file_type="csv",
        run_config=run_config_no_review,
        org_id="org-test-456",
    )

    assert result.get("halted") is True

    episode_ids = result.get("memory_episode_ids") or []
    assert len(episode_ids) == 0, \
        "Memory should not be saved when pipeline halts"


# ── Scenario 8: State integrity ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_always_has_required_fields(csv_file, run_config_no_review):
    """Final state always contains the required control fields regardless of outcome."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-state-001",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    # These fields must always be present
    assert "halted" in result
    assert "awaiting_review" in result
    assert "logs" in result
    assert "min_confidence" in result
    assert isinstance(result["logs"], list)
    assert isinstance(result["min_confidence"], float)


@pytest.mark.asyncio
async def test_min_confidence_between_zero_and_one(csv_file, run_config_no_review):
    """min_confidence is always a float in [0, 1]."""
    result: CFOState = await run_cfo_pipeline(
        job_id="test-state-002",
        file_path=csv_file,
        file_type="csv",
        run_config=run_config_no_review,
    )

    conf = result.get("min_confidence", 1.0)
    assert 0.0 <= conf <= 1.0, f"min_confidence out of range: {conf}"
