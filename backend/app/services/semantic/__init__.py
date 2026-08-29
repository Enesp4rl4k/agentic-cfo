"""Canonical company semantic model — metrics, snapshots, decision briefs."""
from __future__ import annotations

from app.services.semantic.brief import build_from_snapshot, enrich_brief_from_ceo_synthesis
from app.services.semantic.catalog import METRIC_CATALOG, catalog_list
from app.services.semantic.types import (
    CompanySemanticSnapshot,
    DecisionBrief,
    MetricPoint,
    Period,
)

__all__ = [
    "METRIC_CATALOG",
    "CompanySemanticSnapshot",
    "DecisionBrief",
    "MetricPoint",
    "Period",
    "build_from_snapshot",
    "catalog_list",
    "enrich_brief_from_ceo_synthesis",
    "get_latest_semantic_snapshot",
    "get_semantic_snapshot",
    "rebuild_semantic_snapshot",
]


def __getattr__(name: str):
    if name == "rebuild_semantic_snapshot":
        from app.services.semantic.rebuild import rebuild_semantic_snapshot

        return rebuild_semantic_snapshot
    if name == "get_semantic_snapshot":
        from app.services.semantic.store import get_semantic_snapshot

        return get_semantic_snapshot
    if name == "get_latest_semantic_snapshot":
        from app.services.semantic.store import get_latest_semantic_snapshot

        return get_latest_semantic_snapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
