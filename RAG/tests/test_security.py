"""Unit tests for the security policy module — headers, env validation,
and the identifier pattern used at the API boundary."""

import re

import security as security_module
from security import IDENTIFIER_PATTERN, SECURITY_HEADERS, validate_environment


def test_required_headers_present():
    for header in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Content-Security-Policy",
        "Referrer-Policy",
        "Strict-Transport-Security",
    ):
        assert header in SECURITY_HEADERS
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in SECURITY_HEADERS["Content-Security-Policy"]


def test_identifier_pattern():
    pat = re.compile(IDENTIFIER_PATTERN)
    assert pat.match("qatar_may_2026")
    assert pat.match("abc-DEF_123")
    assert not pat.match("bad id")
    assert not pat.match("x'; DROP TABLE jobs;--")
    assert not pat.match("<script>")
    assert not pat.match("")


def test_validate_environment_reports_missing_keys(monkeypatch):
    for var in ("QDRANT_URL", "QDRANT_API_KEY", "FANAR_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    problems = validate_environment()
    joined = " ".join(problems)
    assert "QDRANT_URL" in joined
    assert "QDRANT_API_KEY" in joined
    assert "LLM key" in joined or "FANAR_API_KEY" in joined


def test_validate_environment_clean(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.cloud.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "k")
    monkeypatch.setenv("FANAR_API_KEY", "k")
    monkeypatch.setattr(security_module, "IS_PRODUCTION", False)
    assert validate_environment() == []


def test_production_rejects_localhost_origins(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.cloud.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "k")
    monkeypatch.setenv("FANAR_API_KEY", "k")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setattr(security_module, "IS_PRODUCTION", True)
    problems = validate_environment()
    assert any("localhost" in p for p in problems)
