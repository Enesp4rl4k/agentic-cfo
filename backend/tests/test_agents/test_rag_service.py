"""
Tests for RAG v1 service helpers.
"""
import app.services.rag_service as rag
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


async def test_embedding_runs_before_the_transaction_opens(monkeypatch) -> None:
    """The slow network call must not sit inside the write transaction.

    `index_job_text` used to execute the DELETE first and embed after —
    on SQLite that held the single-writer lock for the whole embedding
    round-trip, blocking every other writer (DDIA Ch.7: keep write
    transactions short). The pin: the first DB statement comes after the
    embed call.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    order: list[str] = []

    def _embed_spy(texts: list[str]) -> list[list[float]] | None:
        order.append("embed")
        return None  # tests have no API key → TF-IDF path

    monkeypatch.setattr(rag, "_embed_texts", _embed_spy)

    async with maker() as db:
        real_execute = db.execute

        async def _execute_spy(*args, **kwargs):
            order.append("db")
            return await real_execute(*args, **kwargs)

        monkeypatch.setattr(db, "execute", _execute_spy)
        written = await rag.index_job_text(
            db,
            org_id="org-1",
            job_id="job-1",
            source_type="upload",
            raw_text="x" * 3000,
        )
        await db.rollback()

    await engine.dispose()

    assert written >= 1
    assert order[0] == "embed"      # BEFORE any statement touches the txn
    assert "db" in order            # the delete still ran afterwards

