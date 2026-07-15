"""Unit tests for the SQL layer — scope-subquery rewriting, value escaping,
stacked-statement stripping, and end-to-end execution against a tiny
in-memory table (LLM generation is monkeypatched; no network involved)."""

from types import SimpleNamespace

import pandas as pd
import pytest

from sql_engine import SQLEngine


@pytest.fixture()
def engine():
    df = pd.DataFrame({
        "job_title":    ["Engineer", "Nurse", "Developer", "Analyst"],
        "company":      ["A Corp", "B Ltd", "A Corp", "C Inc"],
        "_dump_id":     ["qatar_may", "qatar_may", "uae_may", "uae_may"],
        "_sector_norm": ["Technology", "Healthcare", "Technology", "Finance"],
        "_country":     ["Qatar", "Qatar", "UAE", "UAE"],
        "_timeline":    ["May 2026"] * 4,
    })
    return SQLEngine(df)


def _fake_llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_scope_query_unchanged_without_filters(engine):
    sql = "SELECT COUNT(*) FROM jobs"
    assert engine._scope_query(sql, None, None) == sql


def test_scope_query_dump_ids(engine):
    out = engine._scope_query("SELECT COUNT(*) FROM jobs", ["qatar_may"], None)
    assert "_dump_id IN ('qatar_may')" in out
    assert "AS jobs" in out


def test_scope_query_explicit_filter_and_escaping(engine):
    out = engine._scope_query("SELECT COUNT(*) FROM jobs", None, {"_sector_norm": "O'Brien"})
    assert "_sector_norm = 'O''Brien'" in out   # quote doubled — injection-safe


def test_scope_query_ignores_unknown_columns(engine):
    out = engine._scope_query("SELECT COUNT(*) FROM jobs", None, {"not_a_column": "x"})
    assert out == "SELECT COUNT(*) FROM jobs"


def test_stacked_statements_stripped(engine, monkeypatch):
    monkeypatch.setattr(
        engine._client.chat.completions, "create",
        lambda **kw: _fake_llm_response("SELECT COUNT(*) FROM jobs; DROP TABLE jobs"),
    )
    sql = engine._to_sql("how many jobs?")
    assert "DROP" not in sql.upper()
    assert sql.upper().startswith("SELECT")


def test_non_select_rejected(engine, monkeypatch):
    monkeypatch.setattr(
        engine._client.chat.completions, "create",
        lambda **kw: _fake_llm_response("DELETE FROM jobs"),
    )
    assert engine._to_sql("delete everything") == ""


def test_limit_injected(engine, monkeypatch):
    monkeypatch.setattr(
        engine._client.chat.completions, "create",
        lambda **kw: _fake_llm_response("SELECT job_title FROM jobs"),
    )
    assert "LIMIT" in engine._to_sql("list jobs").upper()


def test_get_context_end_to_end_with_scoping(engine, monkeypatch):
    monkeypatch.setattr(engine, "_to_sql", lambda q: "SELECT COUNT(*) AS cnt FROM jobs")
    # Unscoped: all 4 rows; scoped to qatar_may + Technology: exactly 1.
    assert "4" in engine.get_context("count all")
    scoped = engine.get_context("count", dump_ids=["qatar_may"],
                                explicit_filters={"_sector_norm": "Technology"})
    assert "1" in scoped


# ---------------------------------------------------------------------------
# Table-alias regression (LLM-generated "FROM jobs j" used to silently break
# scoping — the rewrite produced invalid SQL "...AS jobs j", which get_context's
# try/except swallowed with zero trace, dropping the SQL-backed answer entirely)
# ---------------------------------------------------------------------------

def test_scope_query_preserves_bare_alias(engine):
    out = engine._scope_query("SELECT j.company FROM jobs j WHERE j.company = 'A Corp'",
                               ["qatar_may"], None)
    assert "AS j " in out or out.endswith("AS j")
    assert "AS jobs j" not in out       # the exact invalid form this bug produced
    assert "WHERE j.company" in out     # rest of the query must survive untouched


def test_scope_query_preserves_as_alias(engine):
    out = engine._scope_query("SELECT j.company FROM jobs AS j GROUP BY j.company",
                               None, {"_sector_norm": "Technology"})
    assert "AS j " in out
    assert "AS jobs j" not in out
    assert "GROUP BY j.company" in out


def test_scope_query_no_alias_keyword_not_mistaken_for_one(engine):
    # "WHERE" must not be captured as a fake alias when there's no real one.
    out = engine._scope_query("SELECT COUNT(*) FROM jobs WHERE company = 'A Corp'",
                               ["qatar_may"], None)
    assert "AS jobs WHERE company = 'A Corp'" in out


def test_get_context_survives_aliased_sql_from_llm(engine, monkeypatch):
    # Reproduces the real bug end-to-end: before the fix, this raised a SQLite
    # syntax error (silently swallowed) and get_context returned "" — the
    # dashboard-vs-chat numbers would then disagree with no signal why.
    monkeypatch.setattr(
        engine, "_to_sql",
        lambda q: "SELECT j.company, COUNT(*) AS cnt FROM jobs j GROUP BY j.company",
    )
    result = engine.get_context("companies", dump_ids=["qatar_may"])
    assert result != ""
    assert "A Corp" in result


def test_get_context_logs_on_genuine_sql_failure(engine, monkeypatch, caplog):
    # A query that's still broken for some other reason must warn, not vanish
    # silently — this is the B2 fix (previously a bare `except: return ""`).
    monkeypatch.setattr(engine, "_to_sql", lambda q: "SELECT nonexistent_column FROM jobs")
    with caplog.at_level("WARNING"):
        result = engine.get_context("bogus")
    assert result == ""
    assert any("SQL execution failed" in r.message for r in caplog.records)
