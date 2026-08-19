"""
Tests for RAG v1 service helpers.
"""
from app.services.rag_service import _chunk_text, _tfidf_similarity


def test_chunk_text_splits_large_input() -> None:
    text = "A" * 5000
    chunks = _chunk_text(text, max_chars=1000, overlap_chars=100)
    assert len(chunks) >= 5
    assert all(len(c) <= 1000 for c in chunks)


def test_chunk_text_empty_input() -> None:
    assert _chunk_text("") == []
    assert _chunk_text("   \n\t  ") == []


def test_tfidf_similarity_ranks_relevant_doc_first() -> None:
    docs = [
        "nakit akisi artis gostermedi bu ay giderler yukseldi",
        "sunucu performans metriği ve deployment gecikmesi",
    ]
    scores = _tfidf_similarity("nakit akisi gider", docs)
    assert len(scores) == 2
    assert scores[0] > scores[1]

