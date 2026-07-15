"""Live API tests — run against a real server on localhost:8000 (auto-skipped
when it isn't up). These are the regression suite that has guarded every
sprint: security headers, error contract, metrics, and the dashboard↔chat
filter-consistency numbers."""

import json
import os

import pytest
import requests

pytestmark = pytest.mark.live


def test_health_shape(api_base):
    r = requests.get(f"{api_base}/health", timeout=10)
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "environment", "version", "postings", "vectors",
                "qdrant_status", "model_configured", "memory_mb"):
        assert key in body
    assert body["status"] == "ok"


def test_security_headers(api_base):
    r = requests.get(f"{api_base}/health", timeout=10)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'none'" in r.headers.get("Content-Security-Policy", "")
    assert r.headers.get("X-Request-ID")


def test_metrics_exposition(api_base):
    r = requests.get(f"{api_base}/metrics", timeout=10)
    assert r.status_code == 200
    assert "http_request_duration_ms" in r.text
    assert "app_info" in r.text


def test_404_error_contract(api_base):
    r = requests.get(f"{api_base}/api/nonexistent", timeout=10)
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error"] == "http_error"
    assert body["request_id"]


def test_oversized_body_rejected(api_base):
    r = requests.post(f"{api_base}/api/chat",
                      data=json.dumps({"question": "x" * 70000, "session_id": "s1"}),
                      headers={"Content-Type": "application/json"}, timeout=10)
    assert r.status_code == 413
    assert r.json()["error"] == "payload_too_large"


def test_malformed_session_rejected(api_base):
    r = requests.post(f"{api_base}/api/chat",
                      json={"question": "hi", "session_id": "bad id!!"}, timeout=10)
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_datasets_endpoint(api_base):
    r = requests.get(f"{api_base}/api/datasets", timeout=15)
    assert r.status_code == 200
    assert "dumps" in r.json()


def test_dashboard_filter_consistency(api_base):
    """The Sprint-1 regression: a sector filter must narrow the total, and the
    narrowed total must be strictly smaller than the unfiltered one."""
    dumps = requests.get(f"{api_base}/api/datasets", timeout=15).json()["dumps"]
    if not dumps:
        pytest.skip("no datasets loaded")
    dump_id = dumps[0]["_dump_id"]

    full = requests.get(f"{api_base}/api/dashboard", params={"dumps": dump_id}, timeout=30).json()
    assert full["total"] > 0
    sector = full["sectors"][0]["sector"]

    filtered = requests.get(f"{api_base}/api/dashboard",
                            params={"dumps": dump_id, "sector": sector}, timeout=30).json()
    assert 0 < filtered["total"] < full["total"]


@pytest.mark.llm
@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS") != "1",
                    reason="costs a real LLM call — set RUN_LLM_TESTS=1 to enable")
def test_chat_sql_count_matches_dashboard(api_base):
    """Full-pipeline consistency: the chat SQL layer must compute the same
    count the dashboard shows for an identical dump+sector scope."""
    dumps = requests.get(f"{api_base}/api/datasets", timeout=15).json()["dumps"]
    dump_id = dumps[0]["_dump_id"]
    dash = requests.get(f"{api_base}/api/dashboard", params={"dumps": dump_id}, timeout=30).json()
    sector = dash["sectors"][0]["sector"]
    expected = requests.get(f"{api_base}/api/dashboard",
                            params={"dumps": dump_id, "sector": sector}, timeout=30).json()["total"]

    sid = requests.post(f"{api_base}/api/session", timeout=10).json()["session_id"]
    r = requests.post(f"{api_base}/api/chat",
                      json={"question": "How many job postings are there?",
                            "session_id": sid, "dump_ids": [dump_id],
                            "filters": {"sector": sector}},
                      timeout=120, stream=True)
    body = b"".join(r.iter_content(65536)).decode("utf-8", errors="replace")
    assert str(expected) in body.replace(",", "")
