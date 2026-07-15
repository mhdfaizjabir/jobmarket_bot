"""Regression tests for the Sprint 8 semantic-hit dump-scoping bug: the chat
transparency panel (`get_retrieval_info`) could show sources from a
country/timeline/dump the user never selected, even though the SQL-backed
answer numbers were always correctly scoped. See PROJECT_SPEC.md Sprint 8 log.

Covers the two pure helpers the fix is built on — `_merge_dump_filter` (Qdrant
where-clause construction, with a dump-only fallback filter) and `_dump_scoped`
(the local safety net applied regardless of which Qdrant code path ran)."""

from rag_engine import _dump_scoped, _merge_dump_filter


def test_merge_dump_filter_no_dumps_is_noop():
    where = {"sector": {"$eq": "Technology"}}
    combined, dump_only = _merge_dump_filter(where, None)
    assert combined == where
    assert dump_only is None


def test_merge_dump_filter_adds_dump_scope_with_no_existing_where():
    combined, dump_only = _merge_dump_filter(None, ["qatar_may_2026"])
    assert combined == {"_dump_id": {"$in": ["qatar_may_2026"]}}
    assert dump_only == {"_dump_id": {"$in": ["qatar_may_2026"]}}


def test_merge_dump_filter_combines_with_existing_where():
    where = {"sector": {"$eq": "Technology"}}
    combined, dump_only = _merge_dump_filter(where, ["qatar_may_2026"])
    assert combined == {
        "$and": [
            {"sector": {"$eq": "Technology"}},
            {"_dump_id": {"$in": ["qatar_may_2026"]}},
        ]
    }
    # The dump-only fallback never includes the other filter — it's the
    # retry used when the *combined* query fails server-side.
    assert dump_only == {"_dump_id": {"$in": ["qatar_may_2026"]}}


def _hit(dump_id: str) -> dict:
    return {"metadata": {"_dump_id": dump_id}, "document": "", "distance": 0.1}


def test_dump_scoped_filters_out_unselected_dumps():
    results = [_hit("qatar_may_2026"), _hit("uae_may_2026"), _hit("qatar_may_2026")]
    scoped = _dump_scoped(results, ["qatar_may_2026"])
    assert len(scoped) == 2
    assert all(r["metadata"]["_dump_id"] == "qatar_may_2026" for r in scoped)


def test_dump_scoped_noop_when_no_active_dumps():
    # Mirrors the "All datasets selected" state — nothing to scope out.
    results = [_hit("qatar_may_2026"), _hit("uae_may_2026")]
    assert _dump_scoped(results, None) == results
    assert _dump_scoped(results, []) == results


def test_dump_scoped_handles_missing_dump_id_in_metadata():
    # A point embedded before `_dump_id` was captured into the payload —
    # must be excluded, not treated as an implicit match.
    results = [{"metadata": {}, "document": "", "distance": 0.1}, _hit("qatar_may_2026")]
    scoped = _dump_scoped(results, ["qatar_may_2026"])
    assert len(scoped) == 1
    assert scoped[0]["metadata"]["_dump_id"] == "qatar_may_2026"
