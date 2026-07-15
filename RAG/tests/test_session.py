"""Unit tests for the in-memory session store — TTL, trimming, and the
flood-cap eviction added in the security sprint."""

import time

import session as session_module
from session import MAX_MESSAGES, SessionStore


def test_create_and_history():
    store = SessionStore()
    sid = store.create()
    assert store.get_history(sid) == []
    store.append(sid, "user", "hello")
    store.append(sid, "assistant", "hi")
    hist = store.get_history(sid)
    assert [m["role"] for m in hist] == ["user", "assistant"]


def test_unknown_session_returns_empty():
    assert SessionStore().get_history("does-not-exist") == []


def test_message_trimming():
    store = SessionStore()
    sid = store.create()
    for i in range(MAX_MESSAGES + 10):
        store.append(sid, "user", f"msg {i}")
    hist = store.get_history(sid)
    assert len(hist) == MAX_MESSAGES
    assert hist[-1]["content"] == f"msg {MAX_MESSAGES + 9}"   # newest kept


def test_clear_keeps_session():
    store = SessionStore()
    sid = store.create()
    store.append(sid, "user", "x")
    store.clear(sid)
    assert store.get_history(sid) == []


def test_ttl_cleanup():
    store = SessionStore()
    sid = store.create()
    # Age the session past TTL by rewriting last_seen directly.
    store._sessions[sid]["last_seen"] = time.time() - session_module.SESSION_TTL - 1
    removed = store.cleanup()
    assert removed == 1
    assert store.stats()["active_sessions"] == 0


def test_flood_cap_evicts_oldest(monkeypatch):
    monkeypatch.setattr(session_module, "MAX_SESSIONS", 3)
    store = SessionStore()
    sids = [store.create() for _ in range(3)]
    # Make the first the least-recently-seen, then overflow.
    store._sessions[sids[0]]["last_seen"] = time.time() - 999
    store.create()
    assert store.stats()["active_sessions"] == 3
    assert sids[0] not in store._sessions            # oldest evicted
    assert all(s in store._sessions for s in sids[1:])
