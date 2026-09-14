"""RAG retrieval layer — pluggable retriever interface."""

from app.services.rag.grounding_validator import (
    apply_disclaimer,
    no_evidence_verdict,
    validate_grounding,
)
from app.services.rag.retriever import (
    EmbeddingRagRetriever,
    HybridRagRetriever,
    RagRetriever,
    TfidfRagRetriever,
    get_rag_retriever,
    retrieve_dual_evidence,
)

__all__ = [
    "EmbeddingRagRetriever",
    "HybridRagRetriever",
    "RagRetriever",
    "TfidfRagRetriever",
    "apply_disclaimer",
    "get_rag_retriever",
    "no_evidence_verdict",
    "retrieve_dual_evidence",
    "validate_grounding",
]
