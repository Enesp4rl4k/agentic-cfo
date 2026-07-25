"""
Tests for AgentMemoryStore — memory engineering layer.
Pure tests, no DB setup required (uses in-memory backend).
"""
import time
import pytest
from app.services.agent_memory import (
    AgentMemoryStore,
    EpisodeRecord,
    _tfidf_similarity,
    _tokenise,
    get_memory_store,
)


# ── EpisodeRecord ─────────────────────────────────────────────────────────────

class TestEpisodeRecord:
    def test_auto_generates_id(self):
        ep = EpisodeRecord(org_id="org-1", agent="pnl_agent", period="2024-Q4", summary={})
        assert ep.id
        assert len(ep.id) == 16

    def test_id_is_deterministic_given_same_created_at(self):
        t = time.time()
        ep1 = EpisodeRecord("org-1", "pnl_agent", "2024-Q4", {}, created_at=t)
        ep2 = EpisodeRecord("org-1", "pnl_agent", "2024-Q4", {}, created_at=t)
        assert ep1.id == ep2.id

    def test_to_dict_serialises_summary(self):
        ep = EpisodeRecord("org-1", "pnl_agent", "2024-Q4", {"revenue": 100})
        d = ep.to_dict()
        assert isinstance(d["summary"], str)
        assert "revenue" in d["summary"]

    def test_from_dict_roundtrip(self):
        ep = EpisodeRecord("org-1", "pnl_agent", "2024-Q4", {"revenue": 100}, narrative="test")
        d = ep.to_dict()
        ep2 = EpisodeRecord.from_dict(d)
        assert ep2.org_id == ep.org_id
        assert ep2.agent == ep.agent
        assert ep2.summary == ep.summary
        assert ep2.narrative == ep.narrative

    def test_tags_serialise(self):
        ep = EpisodeRecord("org-1", "pnl", "2024-Q4", {}, tags=["a", "b"])
        d = ep.to_dict()
        ep2 = EpisodeRecord.from_dict(d)
        assert ep2.tags == ["a", "b"]


# ── TF-IDF similarity ─────────────────────────────────────────────────────────

class TestTfidfSimilarity:
    def test_identical_texts_score_one(self):
        scores = _tfidf_similarity("nakit akışı", ["nakit akışı"])
        assert scores[0] > 0.9

    def test_unrelated_texts_score_low(self):
        scores = _tfidf_similarity("nakit akışı", ["xyz abc def ghi jkl"])
        assert scores[0] < 0.5

    def test_partial_overlap_between_extremes(self):
        scores = _tfidf_similarity("gelir büyümesi", ["gelir artışı", "tamamen farklı"])
        assert scores[0] > scores[1]

    def test_empty_docs_returns_empty(self):
        scores = _tfidf_similarity("query", [])
        assert scores == []

    def test_returns_same_length_as_docs(self):
        docs = ["a", "b", "c", "d"]
        scores = _tfidf_similarity("test", docs)
        assert len(scores) == 4

    def test_scores_in_valid_range(self):
        scores = _tfidf_similarity("test query here", ["test", "query", "here", "other"])
        assert all(0.0 <= s <= 1.0 for s in scores)


class TestTokenise:
    def test_lowercases(self):
        assert "hello" in _tokenise("Hello World")

    def test_splits_words(self):
        tokens = _tokenise("one two three")
        assert len(tokens) == 3

    def test_handles_punctuation(self):
        tokens = _tokenise("hello, world!")
        assert "hello" in tokens
        assert "world" in tokens

    def test_empty_string(self):
        assert _tokenise("") == []


# ── AgentMemoryStore ──────────────────────────────────────────────────────────

def _make_episode(
    org_id: str = "org-1",
    agent: str = "pnl_agent",
    period: str = "2024-Q4",
    narrative: str = "Gelir güçlü büyüdü",
    confidence: float = 0.95,
    offset_secs: float = 0,
) -> EpisodeRecord:
    return EpisodeRecord(
        org_id=org_id,
        agent=agent,
        period=period,
        summary={"revenue": 480_000_00, "net_margin": 0.30},
        narrative=narrative,
        confidence=confidence,
        created_at=time.time() + offset_secs,
    )


class TestAgentMemoryStore:
    def test_save_and_retrieve(self):
        store = AgentMemoryStore(backend="memory")
        ep = _make_episode()
        store.save(ep)
        results = store.retrieve(org_id="org-1")
        assert len(results) == 1
        assert results[0].id == ep.id

    def test_retrieve_filters_by_org(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(org_id="org-1"))
        store.save(_make_episode(org_id="org-2"))
        results = store.retrieve(org_id="org-1")
        assert all(e.org_id == "org-1" for e in results)
        assert len(results) == 1

    def test_retrieve_filters_by_agent(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(agent="pnl_agent"))
        store.save(_make_episode(agent="cashflow_agent"))
        results = store.retrieve(org_id="org-1", agent="pnl_agent")
        assert all(e.agent == "pnl_agent" for e in results)

    def test_retrieve_top_k_limits_results(self):
        store = AgentMemoryStore(backend="memory")
        for i in range(10):
            store.save(_make_episode(period=f"2024-{i:02d}"))
        results = store.retrieve(org_id="org-1", top_k=3)
        assert len(results) <= 3

    def test_retrieve_by_recency_newest_first(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(period="2024-01", offset_secs=-100))
        store.save(_make_episode(period="2024-06", offset_secs=0))
        results = store.retrieve(org_id="org-1")
        assert results[0].period == "2024-06"

    def test_retrieve_with_similarity_query(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(narrative="Nakit akışı pozitif seyretti faaliyet geliri arttı"))
        store.save(_make_episode(narrative="Tamamen ilgisiz metin içeriği xyz"))
        results = store.retrieve(org_id="org-1", query="nakit akışı faaliyet")
        assert results[0].narrative.startswith("Nakit")

    def test_retrieve_filters_by_min_confidence(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(confidence=0.9))
        store.save(_make_episode(confidence=0.3))
        results = store.retrieve(org_id="org-1", min_confidence=0.7)
        assert all(e.confidence >= 0.7 for e in results)

    def test_format_for_context_returns_string(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode())
        episodes = store.retrieve(org_id="org-1")
        text = store.format_for_context(episodes)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_format_for_context_respects_max_chars(self):
        store = AgentMemoryStore(backend="memory")
        for i in range(20):
            store.save(_make_episode(period=f"2024-{i:02d}", narrative="x" * 200))
        episodes = store.retrieve(org_id="org-1", top_k=20)
        text = store.format_for_context(episodes, max_chars=200)
        assert len(text) <= 400  # generous tolerance for header

    def test_format_for_context_empty_episodes(self):
        store = AgentMemoryStore(backend="memory")
        assert store.format_for_context([]) == ""

    def test_clear_removes_all(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode())
        store.clear()
        assert store.retrieve(org_id="org-1") == []

    def test_clear_by_org_only_removes_that_org(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(org_id="org-1"))
        store.save(_make_episode(org_id="org-2"))
        store.clear(org_id="org-1")
        assert store.retrieve(org_id="org-1") == []
        assert len(store.retrieve(org_id="org-2")) == 1

    def test_stats_returns_counts(self):
        store = AgentMemoryStore(backend="memory")
        store.save(_make_episode(agent="pnl_agent"))
        store.save(_make_episode(agent="pnl_agent"))
        store.save(_make_episode(agent="cashflow_agent"))
        stats = store.stats(org_id="org-1")
        assert stats["total_episodes"] == 3
        assert stats["by_agent"]["pnl_agent"] == 2

    def test_stats_empty_org(self):
        store = AgentMemoryStore(backend="memory")
        stats = store.stats(org_id="nonexistent")
        assert stats["total_episodes"] == 0

    def test_sqlite_backend_persists(self, tmp_path):
        db = str(tmp_path / "test.db")
        store1 = AgentMemoryStore(backend="sqlite", db_path=db)
        store1.save(_make_episode())

        store2 = AgentMemoryStore(backend="sqlite", db_path=db)
        results = store2.retrieve(org_id="org-1")
        assert len(results) == 1

    def test_get_memory_store_returns_instance(self):
        store = get_memory_store()
        assert isinstance(store, AgentMemoryStore)
