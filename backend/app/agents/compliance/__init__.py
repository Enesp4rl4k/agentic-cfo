"""Compliance agent package."""

__all__ = ["compliance_graph", "run_compliance_pipeline"]


def __getattr__(name: str):
    if name in ("run_compliance_pipeline", "compliance_graph"):
        from app.agents.compliance.orchestrator import (  # noqa: F401
            compliance_graph,
            run_compliance_pipeline,
        )
        return locals()[name]
    raise AttributeError(f"module 'app.agents.compliance' has no attribute {name!r}")
