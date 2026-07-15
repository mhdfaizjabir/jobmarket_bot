"""Unit tests for retrieval.py — BM25 keyword search, Reciprocal Rank Fusion,
and the optional cross-encoder reranker. Reranker tests are skipped (not
failed) if the model can't be loaded — e.g. no network in an offline CI
runner — mirroring the `live` fixture's skip-if-unreachable pattern."""

import pandas as pd
import pytest

from retrieval import bm25_results, fuse_results, rerank_results, reranker_available


def _row(job_title, company, category="Technology", timeline="2026-05"):
    return {
        "job_title": job_title, "company": company, "category": category,
        "location": "Doha, Qatar", "career_level": "Mid", "employment_type": "Full-Time",
        "education": "Bachelor", "salary": "", "_timeline": timeline,
        "_source_file": "x.xlsx", "_country": "Qatar", "_source": "Bayt", "_dump_id": "d1",
    }


@pytest.fixture
def postings_df() -> pd.DataFrame:
    return pd.DataFrame([
        _row("Senior Software Engineer", "Ooredoo"),
        _row("Python Backend Developer", "Vodafone Qatar"),
        _row("Sales Executive", "Al Rayyan Bank", category="Finance"),
        _row("Registered Nurse", "Hamad Medical Corporation", category="Healthcare"),
        _row("Civil Engineer", "Qatar Foundation", category="Construction"),
    ])


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def test_bm25_results_ranks_keyword_matches_first(postings_df):
    results = bm25_results("software engineer python", postings_df, top_k=5)
    assert results
    titles = [r["metadata"]["job_title"] for r in results]
    assert titles[0] in ("Senior Software Engineer", "Python Backend Developer")


def test_bm25_results_empty_query_or_df():
    assert bm25_results("", pd.DataFrame([_row("Software Engineer", "X")]), top_k=5) == []
    assert bm25_results("software engineer", pd.DataFrame(), top_k=5) == []
    assert bm25_results("software engineer", None, top_k=5) == []


def test_bm25_results_no_keyword_overlap_returns_empty(postings_df):
    # BM25 scores are 0 for a query with zero term overlap with the corpus —
    # bm25_results should drop those rather than returning noise.
    results = bm25_results("zzqqxx nonexistent gibberish term", postings_df, top_k=5)
    assert results == []


def test_bm25_results_respects_top_k(postings_df):
    results = bm25_results("engineer manager developer nurse bank qatar", postings_df, top_k=2)
    assert len(results) <= 2


def test_bm25_results_shape_matches_vector_search(postings_df):
    results = bm25_results("software engineer", postings_df, top_k=3)
    for r in results:
        assert set(r.keys()) == {"document", "metadata", "distance"}
        assert isinstance(r["document"], str) and r["document"]
        assert isinstance(r["metadata"], dict)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def _hit(title, company, timeline="2026-05", distance=0.2):
    return {
        "document": f"Job Title: {title}",
        "metadata": {"job_title": title, "company": company, "_timeline": timeline},
        "distance": distance,
    }


def test_fuse_results_promotes_items_in_both_lists():
    # "Senior Software Engineer" ranks #2 in vector, #1 in BM25 — should end
    # up ranked above an item that only appears in one list at #1.
    vector = [_hit("Python Backend Developer", "Vodafone"), _hit("Senior Software Engineer", "Ooredoo")]
    bm25   = [_hit("Senior Software Engineer", "Ooredoo"), _hit("Civil Engineer", "Qatar Foundation")]
    fused = fuse_results([vector, bm25], top_k=5)
    keys = [(r["metadata"]["job_title"], r["metadata"]["company"]) for r in fused]
    assert keys[0] == ("Senior Software Engineer", "Ooredoo")


def test_fuse_results_prefers_first_list_payload_on_collision():
    vector = [_hit("Senior Software Engineer", "Ooredoo", distance=0.15)]
    bm25   = [_hit("Senior Software Engineer", "Ooredoo", distance=1.0)]
    fused = fuse_results([vector, bm25], top_k=5)
    assert len(fused) == 1
    assert fused[0]["distance"] == 0.15  # vector's real cosine distance, not BM25's placeholder


def test_fuse_results_respects_top_k():
    vector = [_hit(f"Role {i}", f"Company {i}") for i in range(10)]
    fused = fuse_results([vector], top_k=3)
    assert len(fused) == 3


def test_fuse_results_skips_hits_with_no_identity():
    # A hit with no job_title/company/timeline at all can't be safely deduped —
    # must be dropped rather than colliding with every other empty-key hit.
    empty = {"document": "", "metadata": {}, "distance": 0.5}
    fused = fuse_results([[empty, empty]], top_k=5)
    assert fused == []


def test_fuse_results_empty_lists():
    assert fuse_results([], top_k=5) == []
    assert fuse_results([[], []], top_k=5) == []


# ---------------------------------------------------------------------------
# Reranker (skipped, not failed, if the model can't load — e.g. offline CI)
# ---------------------------------------------------------------------------

def test_rerank_results_empty_input_is_noop():
    assert rerank_results("software engineer", [], top_k=5) == []


def test_rerank_results_orders_by_relevance():
    if not reranker_available():
        pytest.skip("Reranker model unavailable (no network / not cached) — skipping, not failing")
    results = [
        _hit("Sales Executive", "Al Rayyan Bank"),
        _hit("Senior Software Engineer", "Ooredoo"),
    ]
    reranked = rerank_results("software engineer job in Qatar", results, top_k=2)
    assert reranked[0]["metadata"]["job_title"] == "Senior Software Engineer"


def test_rerank_results_truncates_to_top_k_when_unavailable(monkeypatch):
    import retrieval
    monkeypatch.setattr(retrieval._reranker, "_load_failed", True)
    monkeypatch.setattr(retrieval._reranker, "_model", None)
    results = [_hit(f"Role {i}", f"Company {i}") for i in range(5)]
    out = rerank_results("query", results, top_k=2)
    assert out == results[:2]
