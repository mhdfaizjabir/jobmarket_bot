"""Shared test setup: make the RAG package importable and define live-server helpers."""

import os
import sys
from pathlib import Path

import pytest

# Tests import service modules directly (filter_registry, session, ...) —
# add the RAG directory to sys.path regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API_BASE = os.getenv("TEST_API_BASE", "http://localhost:8000")


def _server_reachable() -> bool:
    try:
        import requests
        return requests.get(f"{API_BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def api_base() -> str:
    if not _server_reachable():
        pytest.skip(f"API server not reachable at {API_BASE} — start it to run live tests")
    return API_BASE
