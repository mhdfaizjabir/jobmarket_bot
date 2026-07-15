"""Schema-boundary tests for ChatRequest — malformed input must be rejected
before it can reach the SQL/Qdrant layers. Importing `server` is heavy
(pulls sentence-transformers) but exercises the real model, not a copy."""

import pytest
from pydantic import ValidationError

from server import ChatRequest


def _valid(**overrides):
    payload = {
        "question": "How many jobs?",
        "session_id": "abc-123_DEF",
        "dump_ids": ["qatar_may_2026"],
        "filters": {"sector": "Technology"},
    }
    payload.update(overrides)
    return payload


def test_valid_request_passes():
    req = ChatRequest(**_valid())
    assert req.filters == {"sector": "Technology"}


def test_defaults():
    req = ChatRequest(question="hi", session_id="s1")
    assert req.dump_ids == [] and req.filters == {}


@pytest.mark.parametrize("bad_sid", ["has spaces", "x'; DROP--", "<script>", "", "a" * 65])
def test_bad_session_id_rejected(bad_sid):
    with pytest.raises(ValidationError):
        ChatRequest(**_valid(session_id=bad_sid))


def test_too_many_dump_ids_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(**_valid(dump_ids=[f"d{i}" for i in range(101)]))


def test_malformed_dump_id_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(**_valid(dump_ids=["ok_id", "bad id!"]))


def test_too_many_filters_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(**_valid(filters={f"k{i}": "v" for i in range(21)}))


def test_long_filter_value_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(**_valid(filters={"sector": "x" * 201}))


def test_malformed_filter_key_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(**_valid(filters={"bad key!": "v"}))
