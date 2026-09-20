"""Provenance labelling for kernel-derived (non-measured) analytics.

Several C-level kernels (CTO / CHRO / CMO / COO, and partly Risk / Audit)
synthesise metrics from CFO financials multiplied by fixed sector benchmarks
when no real domain data source is connected. This module is the single place
that:

  * declares that provenance on API responses (`provenance_block`), and
  * decides whether a result is solid enough to drive downstream automation
    (`is_synthetic`).

Nothing here changes what the kernels compute — it only makes the basis of a
number explicit so the UI can badge it and the auto-chain can refuse to act on
a fabricated figure.
"""
from __future__ import annotations

from typing import Any

# `data_source` values that mean "extrapolated from CFO financials, not measured".
SYNTHETIC_SOURCES = frozenset({"estimated", "benchmark", "derived"})

_BASIS = {
    "real": "connected or pasted domain data",
    "estimated": "CFO financials x sector benchmarks",
    "benchmark": "sector benchmark assumptions - not analysis",
    "derived": "inferred from other agents' outputs",
    "rule_based": "deterministic rule / catalog evaluation",
}


def is_synthetic(data_source: str | None) -> bool:
    """True when the figure was extrapolated rather than measured/connected."""
    return (data_source or "benchmark") in SYNTHETIC_SOURCES


def provenance_block(
    data_source: str | None, confidence: float | None = None
) -> dict[str, Any]:
    ds = data_source or "benchmark"
    return {
        "data_source": ds,
        "confidence": confidence,
        "synthetic": is_synthetic(ds),
        "basis": _BASIS.get(ds, _BASIS["benchmark"]),
    }


def attach_provenance(result: dict[str, Any]) -> dict[str, Any]:
    """Add a top-level ``provenance`` block to a kernel ``{ok, output, ...}`` dict.

    Reads ``data_source`` / ``confidence`` from the kernel's ``output`` (or
    ``posture`` for the risk kernel). Safe on dicts that carry neither.
    """
    out = result.get("output") or result.get("posture") or {}
    result["provenance"] = provenance_block(
        out.get("data_source"), out.get("confidence")
    )
    return result
