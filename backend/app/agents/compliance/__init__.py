"""Compliance agent package."""

__all__ = ["run_compliance_pipeline", "compliance_graph"]


def __getattr__(name: str):
    if name in ("run_compliance_pipeline", "compliance_graph"):
        from app.agents.compliance.orchestrator import (
            run_compliance_pipeline,
            compliance_graph,
        )
        return locals()[name]
    raise AttributeError(f"module 'app.agents.compliance' has no attribute {name!r}")
