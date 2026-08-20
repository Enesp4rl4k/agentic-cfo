"""RAG retrieval layer — pluggable retriever interface."""

from app.services.rag.retriever import (
    EmbeddingRagRetriever,
    RagRetriever,
    TfidfRagRetriever,
    get_rag_retriever,
)

from app.services.rag.grounding_validator import (
    apply_disclaimer,
    validate_grounding,
)

__all__ = [
    "EmbeddingRagRetriever",
    "RagRetriever",
    "TfidfRagRetriever",
    "get_rag_retriever",
    "validate_grounding",
    "apply_disclaimer",
]
