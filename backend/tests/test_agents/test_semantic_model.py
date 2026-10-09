"""Tests for canonical semantic model, projectors, brief, bridge preference."""
from __future__ import annotations

from app.services.semantic.brief import CONFIDENCE_GATE, build_from_snapshot, compute_health_score
from app.services.semantic.catalog import METRIC_CATALOG, catalog_list, is_known_metric
from app.services.semantic.projectors import (
    merge_metrics,
    project_from_cfo,
    project_from_cmo,
)
from app.services.semantic.types import (
    CompanySemanticSnapshot,
    MetricPoint,
    Period,
)


def test_semantic_catalog_stable_ids() -> None:
    assert is_known_metric("finance.revenue")
    assert is_known_metric("finance.runway_months")
    assert is_known_metric("growth.overall_roas")
    assert "finance.revenue" in METRIC_CATALOG
    ids = {m["metric_id"] for m in catalog_list()}
    assert "people.headcount" in ids
    assert "risk.overall_score" in ids


def test_project_from_cfo_shapes() -> None:
    flat = {
        "pnl": {"revenue": 1_000_000, "net_margin": 0.12, "gross_margin": 0.4},
        "cashflow": {"operating": 50_000},
        "forecast": {"scenarios": {"base": {"runway_months": 8}}},
        "anomalies": [{"severity": "critical"}, {"severity": "low"}],
    }
    pts = project_from_cfo(flat, currency="USD", job_id="j1")
    mmap = {p.metric_id: p for p in pts}
    assert "finance.revenue" in mmap
    assert mmap["finance.runway_months"].value == 8
    assert mmap["finance.critical_anomalies"].value == 1

    nested = {
        "dashboard": {
            "pnl": {"revenue_cents": 2_500_000, "net_margin": 0.05},
            "forecast": {"scenarios": {"base": {"runway_months": 4}}},
        },
        "anomalies": [],
    }
    pts2 = project_from_cfo(nested, currency="USD")
    mmap2 = {p.metric_id: p for p in pts2}
    assert mmap2["finance.revenue"].value == 2_500_000
    assert mmap2["finance.runway_months"].value == 4


def test_project_from_cfo_converts_lira_scalars_to_cents() -> None:
    """Report.data scalars are lira; catalog unit is cents → ×100 at the boundary."""
    flat = {
        "pnl": {"revenue": 1_000_000, "ebitda": 250_000},
        "cashflow": {"operating": 300_000},
    }
    pts = project_from_cfo(flat, currency="USD")
    mmap = {p.metric_id: p for p in pts}
    assert mmap["finance.revenue"].unit == "cents"
    assert mmap["finance.revenue"].value == 100_000_000       # 1_000_000 lira
    assert mmap["finance.ebitda"].value == 25_000_000         # 250_000 lira
    assert mmap["finance.operating_cashflow"].value == 30_000_000  # 300_000 lira


def test_merge_metrics_later_wins() -> None:
    a = [MetricPoint("finance.revenue", 1, "cents", source_agent="cfo")]
    b = [MetricPoint("finance.revenue", 2, "cents", source_agent="canonical", data_source="canonical")]
    merged = merge_metrics(a, b)
    assert len(merged) == 1
    assert merged[0].value == 2
    assert merged[0].data_source == "canonical"


def test_decision_brief_confidence_gate() -> None:
    snap = CompanySemanticSnapshot(
        org_id="org-1",
        period=Period(key="2026-08"),
        currency="USD",
        locale="en-US",
        metrics=[
            MetricPoint("finance.runway_months", 2.0, "months", confidence=0.9),
            MetricPoint("finance.critical_anomalies", 0, "count", confidence=1.0),
            MetricPoint("finance.net_margin", 0.1, "ratio", confidence=0.85),
        ],
    )
    brief = build_from_snapshot(snap)
    assert brief.health_score >= 0
    assert brief.awaiting_review is True  # critical runway finding
    assert any(f.severity == "critical" for f in brief.findings)
    assert brief.recommendation is not None
    assert CONFIDENCE_GATE == 0.80

    healthy = CompanySemanticSnapshot(
        org_id="org-1",
        period=Period(key="2026-08"),
        currency="USD",
        locale="en-US",
        metrics=[
            MetricPoint("finance.runway_months", 14.0, "months", confidence=0.95),
            MetricPoint("finance.critical_anomalies", 0, "count", confidence=1.0),
            MetricPoint("finance.net_margin", 0.2, "ratio", confidence=0.95),
            MetricPoint("growth.overall_roas", 3.0, "ratio", confidence=0.9),
        ],
    )
    score, _ = compute_health_score(healthy)
    assert score >= 50
    brief2 = build_from_snapshot(healthy)
    assert brief2.awaiting_review is False or all(f.severity != "critical" for f in brief2.findings)


def test_decision_brief_localizes_turkish() -> None:
    """Brief copy follows the org locale carried on the snapshot (tr-TR → Turkish)."""

    def snap(locale: str) -> CompanySemanticSnapshot:
        return CompanySemanticSnapshot(
            org_id="org-1",
            period=Period(key="2026-08"),
            currency="TRY" if locale.startswith("tr") else "USD",
            locale=locale,
            metrics=[
                MetricPoint("finance.runway_months", 4.0, "months", confidence=0.9),
                MetricPoint("finance.net_margin", 0.1, "ratio", confidence=0.85),
            ],
        )

    tr_brief = build_from_snapshot(snap("tr-TR"))
    assert tr_brief.headline.startswith("Şirket sağlığı")
    assert any("Nakit koşu süresi" in f.statement for f in tr_brief.findings)
    assert tr_brief.options[0].title == "Nakit koşusunu koru"
    assert tr_brief.recommendation is not None
    assert tr_brief.recommendation.title == "Nakit koşusunu koru"

    en_brief = build_from_snapshot(snap("en-US"))
    assert en_brief.headline.startswith("Company health")
    assert any("Cash runway" in f.statement for f in en_brief.findings)
    assert en_brief.options[0].title == "Protect runway"


def test_project_from_cmo() -> None:
    pts = project_from_cmo(
        {"campaigns": {"overall_roas": 1.2, "blended_cac_cents": 15000, "total_conversions": 40}}
    )
    ids = {p.metric_id for p in pts}
    assert "growth.overall_roas" in ids
    assert "growth.blended_cac" in ids


def test_semantic_store_roundtrip_types() -> None:
    snap = CompanySemanticSnapshot(
        org_id="o1",
        period=Period(key="2026-Q1", grain="quarter"),
        currency="EUR",
        locale="en-GB",
        metrics=[MetricPoint("finance.revenue", 100, "cents")],
    )
    raw = snap.to_dict()
    back = CompanySemanticSnapshot.from_dict(raw)
    assert back.org_id == "o1"
    assert back.period.key == "2026-Q1"
    assert back.currency == "EUR"
    assert back.metrics[0].value == 100


def test_bridge_prefers_semantic() -> None:
    """__cfo_summary should prefer semantic values when injected."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    async def _run() -> None:
        semantic_snap = CompanySemanticSnapshot(
            org_id="org-1",
            period=Period(key="2026-08"),
            currency="USD",
            locale="en-US",
            metrics=[
                MetricPoint("finance.revenue", 999, "cents"),
                MetricPoint("finance.runway_months", 11, "months"),
                MetricPoint("finance.net_margin", 0.22, "ratio"),
                MetricPoint("finance.critical_anomalies", 0, "count"),
            ],
        )
        mock_ctx = MagicMock()
        mock_ctx.reporting_period = "2026-08"
        mock_ctx.last_cfo_result = {
            "pnl": {"revenue": 1, "net_margin": 0.01},
            "forecast": {"scenarios": {"base": {"runway_months": 3}}},
            "anomalies": [],
        }
        mock_ctx.last_cto_result = None
        mock_ctx.last_cmo_result = None
        mock_ctx.last_chro_result = None

        with patch(
            "app.services.company_context.get_company_context",
            new=AsyncMock(return_value=mock_ctx),
        ), patch(
            "app.services.semantic.store.get_semantic_snapshot",
            new=AsyncMock(return_value=semantic_snap),
        ), patch(
            "app.services.semantic.store.get_latest_semantic_snapshot",
            new=AsyncMock(return_value=None),
        ):
            from app.services.agent_context_bridge import enrich_state

            enriched = await enrich_state("risk", {}, "org-1", db=None)

        assert enriched["__semantic_metrics"]["finance.revenue"] == 999
        assert enriched["__cfo_summary"]["revenue"] == 999
        assert enriched["__cfo_summary"]["runway_months"] == 11

    asyncio.run(_run())


def test_conductor_metric_signals() -> None:
    from app.platform.conductor import signals_from_company_context

    signals = signals_from_company_context(
        {"semantic_metrics": {"finance.revenue": 1, "growth.overall_roas": 2.0}}
    )
    assert "metric:finance.revenue" in signals
    assert "cfo_result" in signals
    assert "campaign_csv" in signals


def test_period_date_bounds() -> None:
    from app.services.semantic.store import period_date_bounds, resolve_period_key

    p = resolve_period_key("2026-08")
    start, end = period_date_bounds(p)
    assert start is not None and end is not None
    assert start.year == 2026 and start.month == 8 and start.day == 1
    assert end.month == 8 and end.day == 31

    q = resolve_period_key("2026-Q1")
    qs, qe = period_date_bounds(q)
    assert qs is not None and qe is not None
    assert qs.month == 1
    assert qe.month == 3


def test_brief_includes_agent_conflicts() -> None:
    snap = CompanySemanticSnapshot(
        org_id="org-1",
        period=Period(key="2026-08"),
        currency="USD",
        locale="en-US",
        metrics=[
            MetricPoint("finance.runway_months", 14.0, "months", confidence=0.95),
            MetricPoint("finance.critical_anomalies", 0, "count", confidence=1.0),
            MetricPoint("finance.net_margin", 0.2, "ratio", confidence=0.95),
            MetricPoint("growth.overall_roas", 3.0, "ratio", confidence=0.9),
        ],
    )
    conflicts = [
        {
            "topic": "runway_estimate",
            "agent_a": "cfo",
            "agent_b": "cmo",
            "consensus_score": 0.6,
        }
    ]
    brief = build_from_snapshot(snap, conflicts=conflicts)
    assert len(brief.conflicts) == 1
    assert any("runway_estimate" in f.statement for f in brief.findings)
    assert brief.awaiting_review is True


def test_list_semantic_snapshots_types() -> None:
    from app.services.semantic.store import list_semantic_snapshots

    assert callable(list_semantic_snapshots)


def test_approve_semantic_brief_exported() -> None:
    from app.services.semantic.store import approve_semantic_brief

    assert callable(approve_semantic_brief)


def test_brief_approve_clears_awaiting_review_flag() -> None:
    from app.services.semantic.brief import build_from_snapshot

    snap = CompanySemanticSnapshot(
        org_id="org-1",
        period=Period(key="2026-08"),
        currency="USD",
        locale="en-US",
        metrics=[
            MetricPoint("finance.runway_months", 2.0, "months", confidence=0.95),
            MetricPoint("finance.critical_anomalies", 1, "count", confidence=1.0),
        ],
    )
    brief = build_from_snapshot(snap)
    assert brief.awaiting_review is True
    brief.awaiting_review = False
    assert brief.awaiting_review is False
