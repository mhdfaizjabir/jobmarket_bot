"""
retrieval.py
------------
Hybrid retrieval layer on top of the existing Qdrant vector search: BM25
keyword search + Reciprocal Rank Fusion (RRF), with an optional cross-encoder
reranking pass over the fused candidates.

No new persistent index — BM25 is rebuilt on the fly over whatever row-level
DataFrame subset the caller has already scoped (dump_ids + explicit filters),
which guarantees it can never surface a row outside the same scope the vector
search and SQL layers already enforce. Cheap at this corpus size (~1s for the
full ~30k-row corpus, proportionally less once scoping narrows it — see
RAG/tests/test_retrieval.py's benchmark-adjacent sanity check).

Both layers degrade gracefully so hybrid retrieval never breaks plain vector
search: `bm25_results` returns [] on an empty/errored scope, and the reranker
falls back to a no-op if the model can't be loaded (no network on first run,
disk issue, etc.) — set ENABLE_HYBRID_RETRIEVAL=false / ENABLE_RERANKER=false
to disable either outright.
"""

import os
import re
import time

import pandas as pd
from rank_bm25 import BM25Okapi

from config import get_logger
from observability import record_metric
from vector_store import _build_doc_text, _build_metadata

logger = get_logger(__name__)

ENABLE_HYBRID_RETRIEVAL = os.getenv("ENABLE_HYBRID_RETRIEVAL", "true").lower() != "false"
ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "true").lower() != "false"
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")

_RRF_K = 60
# Words plus Arabic script — the corpus is bilingual (see vector_store.py's
# _ar_content merge), so a Latin-only \w tokenizer would silently drop every
# Arabic-source posting from BM25 scoring.
_TOKEN_RE = re.compile(r"[\w؀-ۿ]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def bm25_results(query: str, df: pd.DataFrame, top_k: int) -> list[dict]:
    """
    BM25 keyword search over an already-scoped DataFrame subset. Returns
    results in the same shape VectorStore.search() returns, so they can be
    fused with vector hits via fuse_results().
    """
    if df is None or df.empty or not query.strip():
        return []

    rows = list(df.iterrows())
    texts = [_build_doc_text(row) for _, row in rows]
    tokenized = [_tokenize(t) for t in texts]
    if not any(tokenized):
        return []

    try:
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(_tokenize(query))
    except Exception:
        logger.exception("BM25 scoring failed — continuing with vector-only retrieval")
        return []

    order = sorted(range(len(texts)), key=lambda i: scores[i], reverse=True)
    results: list[dict] = []
    for i in order[: top_k * 3]:  # generous pool; fuse_results/rerank trim further
        if scores[i] <= 0:
            break
        results.append({
            "document": texts[i],
            "metadata": _build_metadata(rows[i][1]),
            "distance": 1.0,  # BM25 has no cosine distance; RRF ignores this field
        })
        if len(results) >= top_k:
            break
    return results


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def _result_key(r: dict) -> tuple:
    """Identity for 'the same posting' across independently-ranked lists —
    mirrors the (job_title, company) identity the existing cross-timeline
    dedup in rag_engine.py already uses, with _timeline added to reduce
    collisions between genuinely distinct postings that share a title+company."""
    m = r.get("metadata", {})
    return (
        str(m.get("job_title", "")).lower().strip(),
        str(m.get("company", "")).lower().strip(),
        str(m.get("_timeline", "")).lower().strip(),
    )


def fuse_results(result_lists: list[list[dict]], top_k: int, k: int = _RRF_K) -> list[dict]:
    """
    Standard RRF: score(d) = sum over lists containing d of 1/(k + rank + 1).
    When a key appears in more than one list, the dict from whichever list
    was passed first wins for the returned payload — pass vector results
    first so a real cosine distance surfaces over BM25's placeholder one.
    """
    scores: dict[tuple, float] = {}
    payload: dict[tuple, dict] = {}
    for results in result_lists:
        for rank, r in enumerate(results):
            key = _result_key(r)
            if not any(key):
                continue  # no job_title/company/timeline at all — can't dedupe safely, skip
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            payload.setdefault(key, r)
    ranked_keys = sorted(scores, key=lambda kk: scores[kk], reverse=True)
    return [payload[kk] for kk in ranked_keys[:top_k]]


# ---------------------------------------------------------------------------
# Cross-encoder reranking (lazy-loaded, optional)
# ---------------------------------------------------------------------------

class _Reranker:
    """Lazy-loaded multilingual cross-encoder singleton. Loaded once, on first
    use — not at import time — so a module that only wants bm25_results/
    fuse_results never pays for it, and a failed load degrades to a no-op
    instead of taking retrieval down."""

    def __init__(self):
        self._model = None
        self._load_failed = not ENABLE_RERANKER

    def _ensure_loaded(self):
        if self._model is not None or self._load_failed:
            return
        try:
            from sentence_transformers import CrossEncoder
            t0 = time.perf_counter()
            self._model = CrossEncoder(RERANKER_MODEL)
            logger.info("Reranker loaded (%s) in %.1fs", RERANKER_MODEL, time.perf_counter() - t0)
        except Exception:
            logger.exception("Reranker failed to load — continuing without reranking")
            self._load_failed = True

    @property
    def available(self) -> bool:
        self._ensure_loaded()
        return self._model is not None

    def predict(self, pairs: list[tuple[str, str]]):
        return self._model.predict(pairs, show_progress_bar=False)


_reranker = _Reranker()


def reranker_available() -> bool:
    """Cheap check callers can use to skip reranking work entirely (e.g. to
    avoid paying tokenization cost) without triggering a load attempt."""
    return _reranker.available


def warm_up_reranker() -> None:
    """
    Force the reranker to load now rather than lazily on a random user's
    first chat message. Call once at server startup, right after the
    embedding model loads — same rationale as VectorStore eager-loading
    SentenceTransformer in its own __init__. A no-op if ENABLE_RERANKER=false
    or the model fails to load (logged, not raised — retrieval still works
    via BM25+vector fusion without reranking).
    """
    if _reranker.available:
        logger.info("Reranker warm-up complete.")


def rerank_results(query: str, results: list[dict], top_k: int) -> list[dict]:
    """Rerank `results` by cross-encoder relevance to `query`. Returns the
    input truncated to top_k, unranked, if the reranker isn't available."""
    if not results:
        return results
    if not _reranker.available:
        return results[:top_k]

    pairs = [(query, r.get("document", "")) for r in results]
    t0 = time.perf_counter()
    try:
        scores = _reranker.predict(pairs)
    except Exception:
        logger.exception("Reranker inference failed — falling back to input order")
        return results[:top_k]
    record_metric("reranker_duration_ms", (time.perf_counter() - t0) * 1000)

    order = sorted(range(len(results)), key=lambda i: scores[i], reverse=True)
    return [results[i] for i in order[:top_k]]
