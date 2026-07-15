"""
session.py
----------
In-memory session store with TTL and automatic cleanup.
Each session tracks chat history for one user tab/browser.
"""

import time
import uuid
from threading import Lock

SESSION_TTL  = 2 * 60 * 60   # 2 hours of inactivity → session expired
MAX_MESSAGES = 20             # keep last N messages per session to bound memory
MAX_SESSIONS = 10_000         # hard cap on concurrent sessions — bounds memory
                             # against a session-flood (append auto-creates, and
                             # rate limiting only throttles per-IP, not globally)


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._lock = Lock()

    def _evict_if_full(self):
        """Drop the least-recently-seen session when at capacity. Caller holds the lock."""
        if len(self._sessions) < MAX_SESSIONS:
            return
        oldest = min(self._sessions, key=lambda s: self._sessions[s]["last_seen"])
        del self._sessions[oldest]

    def create(self) -> str:
        """Create a new session and return its ID."""
        sid = str(uuid.uuid4())
        with self._lock:
            self._evict_if_full()
            self._sessions[sid] = {"messages": [], "last_seen": time.time()}
        return sid

    def get_history(self, sid: str) -> list[dict]:
        """Return message history for a session (empty list if not found)."""
        with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return []
            session["last_seen"] = time.time()
            return list(session["messages"])

    def append(self, sid: str, role: str, content: str):
        """Append one message to a session, creating it if needed."""
        with self._lock:
            if sid not in self._sessions:
                self._evict_if_full()
                self._sessions[sid] = {"messages": [], "last_seen": time.time()}
            session = self._sessions[sid]
            session["messages"].append({"role": role, "content": content})
            session["last_seen"] = time.time()
            if len(session["messages"]) > MAX_MESSAGES:
                session["messages"] = session["messages"][-MAX_MESSAGES:]

    def clear(self, sid: str):
        """Clear history for a session (keeps session alive)."""
        with self._lock:
            if sid in self._sessions:
                self._sessions[sid]["messages"] = []

    def cleanup(self):
        """Remove sessions idle longer than TTL. Call periodically."""
        cutoff = time.time() - SESSION_TTL
        with self._lock:
            expired = [sid for sid, s in self._sessions.items()
                       if s["last_seen"] < cutoff]
            for sid in expired:
                del self._sessions[sid]
        return len(expired)

    def stats(self) -> dict:
        with self._lock:
            return {"active_sessions": len(self._sessions)}
