"""
evaluate.py
-----------
Offline evaluation script for the GCC Job Market RAG system.

Runs three evaluation layers:
  1. _verify()          — did the LLM repeat SQL numbers correctly?      (numerical accuracy)
  2. SQL correctness    — does generated SQL return the right result?     (vs pandas ground truth)
  3. Answer relevancy   — simple keyword presence check, no API needed   (lightweight proxy)

Run:
    python evaluate.py
    python evaluate.py --model gpt-4o-mini   # override model
    python evaluate.py --out results.json    # save JSON report
"""

import argparse
import json
import re
import sqlite3
import sys

# Windows cmd/PowerShell default to cp1252 — force UTF-8 so Arabic prints correctly
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd

from analytics import AnalyticsEngine
from data_loader import load_all
from rag_engine import RAGEngine
from sql_engine import SQLEngine
from vector_store import VectorStore
from config import CHAT_MODEL


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    question: str
    category: str                         # counting | ranking | skill | semantic | arabic
    expected_keywords: list[str] = field(default_factory=list)   # words that MUST appear in answer
    ground_truth_sql: str = ""            # pandas expression for expected scalar result
    is_numerical: bool = False            # should _verify() run?
    notes: str = ""


TEST_CASES: list[TestCase] = [
    # ── Counting ────────────────────────────────────────────────────────────
    TestCase(
        question="How many total job postings are in the database?",
        category="counting",
        is_numerical=True,
        ground_truth_sql="len(df)",
        expected_keywords=[],
        notes="Total row count — deterministic",
    ),
    TestCase(
        question="How many full-time jobs are there in Qatar?",
        category="counting",
        is_numerical=True,
        ground_truth_sql="len(df[(df['_country']=='Qatar') & (df['_employment_norm']=='Full-Time')])",
        expected_keywords=["qatar", "full"],
        notes="Country + employment type filter",
    ),
    TestCase(
        question="How many job postings are from Saudi Arabia?",
        category="counting",
        is_numerical=True,
        ground_truth_sql="len(df[df['_country']=='Saudi Arabia'])",
        expected_keywords=["saudi"],
        notes="Single-country count",
    ),
    TestCase(
        question="How many jobs require a Bachelor's degree in UAE?",
        category="counting",
        is_numerical=True,
        ground_truth_sql="len(df[(df['_country']=='UAE') & (df['education'].str.contains('Bachelor', case=False, na=False))])",
        expected_keywords=["uae", "bachelor"],
        notes="Country + education filter",
    ),
    TestCase(
        question="How many senior-level positions are available?",
        category="counting",
        is_numerical=True,
        ground_truth_sql="len(df[df['_career_norm']=='Senior'])",
        expected_keywords=["senior"],
        notes="Career level filter",
    ),

    # ── Ranking ─────────────────────────────────────────────────────────────
    TestCase(
        question="What are the top 3 sectors by job count in Qatar?",
        category="ranking",
        is_numerical=False,
        ground_truth_sql=(
            "df[df['_country']=='Qatar']['_sector_norm'].value_counts().head(3).index.tolist()"
        ),
        expected_keywords=["qatar"],
        notes="Sector ranking — check top sector appears in answer",
    ),
    TestCase(
        question="Which employment type is most common across the GCC?",
        category="ranking",
        is_numerical=False,
        ground_truth_sql="df[df['_employment_norm'].notna()]['_employment_norm'].value_counts().idxmax()",
        expected_keywords=["full"],
        notes="Most common employment type — should be Full-Time",
    ),
    TestCase(
        question="What are the top 5 companies hiring in Saudi Arabia?",
        category="ranking",
        is_numerical=False,
        ground_truth_sql=(
            "df[df['_country']=='Saudi Arabia']['company'].value_counts().head(5).index.tolist()"
        ),
        expected_keywords=["saudi"],
        notes="Company ranking by country",
    ),
    TestCase(
        question="Which career level has the most job postings in Qatar?",
        category="ranking",
        is_numerical=False,
        ground_truth_sql=(
            "df[df['_country']=='Qatar']['_career_norm'].value_counts().idxmax()"
        ),
        expected_keywords=["qatar"],
        notes="Career level distribution",
    ),

    # ── Skill / Salary (pandas layer) ───────────────────────────────────────
    TestCase(
        question="What are the most demanded skills for data science jobs in Qatar?",
        category="skill",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=["python", "data", "qatar"],
        notes="Semantic + skill stats — check common DS skills appear",
    ),
    TestCase(
        question="What is the average salary range for engineers in UAE?",
        category="skill",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=["uae", "salary", "engineer"],
        notes="Salary query — pandas layer; verify coverage flag appears",
    ),
    TestCase(
        question="What skills are most required in the healthcare sector?",
        category="skill",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=["health", "nursing", "patient"],
        notes="Sector-specific skill frequency",
    ),

    # ── Semantic search ──────────────────────────────────────────────────────
    TestCase(
        question="What jobs are available related to cloud computing and DevOps?",
        category="semantic",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=["cloud", "devops", "aws"],
        notes="Pure semantic — ChromaDB layer",
    ),
    TestCase(
        question="Find jobs for fresh graduates in the technology sector",
        category="semantic",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=["entry", "graduate", "technology"],
        notes="Career level + sector semantic query",
    ),

    # ── Arabic ──────────────────────────────────────────────────────────────
    TestCase(
        question="كم عدد الوظائف في قطر؟",
        category="arabic",
        is_numerical=True,
        ground_truth_sql="len(df[df['_country']=='Qatar'])",
        expected_keywords=["قطر"],
        notes="Arabic count query — tests Arabic routing",
    ),
    TestCase(
        question="ما هي أكثر المهارات طلباً في المملكة العربية السعودية؟",
        category="arabic",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=["السعودية", "مهار"],
        notes="Arabic skill query — semantic + pandas layers",
    ),

    # ── Trend / Comparison ───────────────────────────────────────────────────
    TestCase(
        question="How have job postings in Qatar changed between the two time periods?",
        category="trend",
        is_numerical=True,
        ground_truth_sql=(
            "df[df['_country']=='Qatar'].groupby('_timeline').size().to_dict()"
        ),
        expected_keywords=["qatar", "increase", "decrease", "change", "grew"],
        notes="Trend comparison — tests multi-timeline SQL",
    ),
    TestCase(
        question="Which sector grew the most between the two snapshots?",
        category="trend",
        is_numerical=False,
        ground_truth_sql="",
        expected_keywords=[],
        notes="Trend ranking — non-numerical, SQL correctness only",
    ),

    # ── Edge cases ───────────────────────────────────────────────────────────
    TestCase(
        question="How many jobs are available in Riyadh?",
        category="counting",
        is_numerical=True,
        ground_truth_sql="len(df[df['location'].str.contains('Riyadh', case=False, na=False)])",
        expected_keywords=["riyadh"],
        notes="City-level filter — should not say 'Riyadh, Qatar'",
    ),
    TestCase(
        question="What percentage of jobs in Qatar are full-time?",
        category="counting",
        is_numerical=True,
        ground_truth_sql=(
            "round(100 * len(df[(df['_country']=='Qatar') & (df['_employment_norm']=='Full-Time')]) "
            "/ max(len(df[df['_country']=='Qatar']), 1), 1)"
        ),
        expected_keywords=["qatar", "full", "%"],
        notes="Percentage calculation — verifies number accuracy",
    ),
]


# ---------------------------------------------------------------------------
# SQL correctness checker
# ---------------------------------------------------------------------------

def check_sql_correctness(sql_engine: SQLEngine, question: str, df: pd.DataFrame,
                           ground_truth_expr: str) -> dict:
    """
    Compare what the SQL engine returns vs the pandas ground truth.
    Returns: {correct, generated_result, expected_result, generated_sql}
    """
    if not ground_truth_expr:
        return {"correct": None, "generated_result": None,
                "expected_result": None, "generated_sql": ""}

    try:
        expected = eval(ground_truth_expr, {"df": df, "pd": pd, "len": len,
                                            "round": round, "max": max})
    except Exception as e:
        return {"correct": None, "generated_result": None,
                "expected_result": f"eval error: {e}", "generated_sql": ""}

    generated_sql = sql_engine._to_sql(question)
    if not generated_sql:
        return {"correct": False, "generated_result": "(no SQL generated)",
                "expected_result": expected, "generated_sql": ""}

    try:
        result_df = pd.read_sql_query(generated_sql, sql_engine.conn)
        if result_df.empty:
            generated_result = 0
        elif result_df.shape == (1, 1):
            val = result_df.iloc[0, 0]
            # numpy scalars don't pass isinstance(x, (int, float)) — convert to Python native
            generated_result = val.item() if hasattr(val, "item") else val
        else:
            generated_result = result_df.iloc[:, 0].tolist()
    except Exception as e:
        return {"correct": False, "generated_result": f"SQL error: {e}",
                "expected_result": expected, "generated_sql": generated_sql}

    # Normalise string results that look like "23.8%" → 23.8 float
    if isinstance(generated_result, str):
        num_match = re.search(r"[\d.]+", generated_result)
        if num_match:
            try:
                generated_result = float(num_match.group())
            except ValueError:
                pass

    # Scalar comparison with tolerance
    correct = False
    if isinstance(expected, (int, float)) and isinstance(generated_result, (int, float)):
        correct = abs(float(expected) - float(generated_result)) < 1
    elif isinstance(expected, str):
        if isinstance(generated_result, str):
            correct = expected.strip().lower() == generated_result.strip().lower()
        elif isinstance(generated_result, list):
            # e.g. expected='Senior', got=['Senior'] from a multi-column SELECT
            first = next((x for x in generated_result if x is not None), None)
            correct = (first is not None and
                       str(first).strip().lower() == expected.strip().lower())
    elif isinstance(expected, list) and isinstance(generated_result, list):
        # Top item should match
        correct = (len(expected) > 0 and len(generated_result) > 0
                   and str(expected[0]).lower() == str(generated_result[0]).lower())
    elif isinstance(expected, dict):
        correct = None  # dict comparison — skip auto-grade

    return {
        "correct":           correct,
        "generated_result":  generated_result,
        "expected_result":   expected,
        "generated_sql":     generated_sql,
    }


# ---------------------------------------------------------------------------
# Answer relevancy (keyword check)
# ---------------------------------------------------------------------------

def check_relevancy(answer_text: str, expected_keywords: list[str]) -> dict:
    """
    Lightweight relevancy check: fraction of expected keywords present in answer.
    Returns: {score, hits, misses}
    """
    if not expected_keywords:
        return {"score": None, "hits": [], "misses": []}

    answer_lower = answer_text.lower()
    hits   = [kw for kw in expected_keywords if kw.lower() in answer_lower]
    misses = [kw for kw in expected_keywords if kw.lower() not in answer_lower]
    score  = len(hits) / len(expected_keywords)
    return {"score": round(score, 2), "hits": hits, "misses": misses}


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _col(text: str, width: int) -> str:
    return str(text)[:width].ljust(width)


def print_report(results: list[dict], elapsed: float):
    # Aggregate
    numerical    = [r for r in results if r["is_numerical"]]
    verify_pass  = sum(1 for r in numerical if r["verification"]["passed"])
    verify_total = len(numerical)

    sql_graded   = [r for r in results if r["sql_check"]["correct"] is not None]
    sql_pass     = sum(1 for r in sql_graded if r["sql_check"]["correct"])

    rel_graded   = [r for r in results if r["relevancy"]["score"] is not None]
    rel_scores   = [r["relevancy"]["score"] for r in rel_graded]
    avg_rel      = sum(rel_scores) / len(rel_scores) if rel_scores else 0.0

    print("\n" + "═" * 90)
    print("  GCC JOB MARKET RAG — EVALUATION REPORT")
    print("═" * 90)

    # Per-question table
    hdr = (f"{'#':<3}  {'Category':<10}  {'Verify':<8}  {'SQL':<8}  "
           f"{'Relevancy':<10}  Question")
    print(f"\n{hdr}")
    print("─" * 90)

    for i, r in enumerate(results, 1):
        v_str  = "✅ pass" if r["verification"]["passed"] else (
                 "❌ fail" if r["is_numerical"] else "  —    ")
        sq_str = ("✅ pass" if r["sql_check"]["correct"] is True  else
                  "❌ fail" if r["sql_check"]["correct"] is False else "  —    ")
        rel    = r["relevancy"]["score"]
        rl_str = f"{rel:.0%}" if rel is not None else "  —  "
        q_short = r["question"][:48] + ("…" if len(r["question"]) > 48 else "")
        print(f"{i:<3}  {_col(r['category'],10)}  {v_str:<8}  {sq_str:<8}  {rl_str:<10}  {q_short}")

    print("─" * 90)

    # Summary table
    print(f"\n{'METRIC':<40}  {'SCORE':<15}  {'TARGET'}")
    print("─" * 72)
    vp = f"{verify_pass}/{verify_total}  ({verify_pass/verify_total*100:.0f}%)" if verify_total else "n/a"
    sp = f"{sql_pass}/{len(sql_graded)}  ({sql_pass/len(sql_graded)*100:.0f}%)" if sql_graded else "n/a"
    rp = f"{avg_rel:.0%}" if rel_scores else "n/a"

    rows = [
        ("Numerical accuracy  (_verify pass rate)", vp, "> 90%"),
        ("SQL correctness     (auto-graded)",       sp, "> 90%"),
        ("Answer relevancy    (keyword coverage)",  rp, "> 70%"),
    ]
    for label, score, target in rows:
        print(f"  {label:<38}  {score:<15}  {target}")

    print(f"\n  Total questions: {len(results)}  |  Elapsed: {elapsed:.1f}s")
    print("═" * 90 + "\n")

    # Failures detail
    failures = [r for r in results
                if (r["is_numerical"] and not r["verification"]["passed"])
                or (r["sql_check"]["correct"] is False)]
    if failures:
        print("FAILURES DETAIL")
        print("─" * 90)
        for r in failures:
            print(f"\nQ: {r['question']}")
            v = r["verification"]
            if r["is_numerical"] and not v["passed"]:
                print(f"  _verify:  claimed={v['claimed']}  mismatches={v['mismatches']}")
            sq = r["sql_check"]
            if sq["correct"] is False:
                print(f"  SQL:      expected={sq['expected_result']}  got={sq['generated_result']}")
                print(f"  SQL gen:  {sq['generated_sql'][:120]}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=CHAT_MODEL,
                        help="LLM model to use (default: CHAT_MODEL from config)")
    parser.add_argument("--out",   default="",
                        help="Save JSON report to this path")
    parser.add_argument("--skip-answer", action="store_true",
                        help="Skip LLM answer generation (SQL + verify only — faster)")
    args = parser.parse_args()

    print("\nLoading data…")
    df, timelines = load_all()
    print(f"  Loaded {len(df):,} rows | timelines: {timelines}")

    analytics = AnalyticsEngine(df)

    print("Initialising vector store…")
    vs = VectorStore()

    engine = RAGEngine(analytics, vs)

    t0 = time.time()
    results: list[dict] = []

    print(f"\nRunning {len(TEST_CASES)} test cases with model: {args.model}\n")

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"  [{i:2}/{len(TEST_CASES)}] {tc.category:<10}  {tc.question[:60]}")

        result: dict[str, Any] = {
            "question":    tc.question,
            "category":    tc.category,
            "is_numerical": tc.is_numerical,
            "notes":       tc.notes,
            "answer":      "",
            "verification": {"passed": True, "claimed": set(), "expected": set(), "mismatches": set()},
            "sql_check":   {"correct": None, "generated_result": None,
                            "expected_result": None, "generated_sql": ""},
            "relevancy":   {"score": None, "hits": [], "misses": []},
        }

        # SQL correctness — always run (no LLM answer needed for this)
        result["sql_check"] = check_sql_correctness(
            engine.sql, tc.question, df, tc.ground_truth_sql
        )

        if not args.skip_answer:
            try:
                eval_result      = engine.answer_eval(tc.question, model=args.model)
                result["answer"] = eval_result["answer"]

                if tc.is_numerical:
                    # Use full context (includes SQL ANALYTICS section) for verification
                    result["verification"] = eval_result["verification"]

                result["relevancy"] = check_relevancy(eval_result["answer"], tc.expected_keywords)
            except Exception as e:
                result["answer"] = f"ERROR: {e}"
                print(f"         ⚠ LLM error: {e}")

        results.append(result)

    elapsed = time.time() - t0

    # Convert sets to lists for JSON serialisation
    for r in results:
        v = r["verification"]
        v["claimed"]    = sorted(v["claimed"])
        v["expected"]   = sorted(v["expected"])
        v["mismatches"] = sorted(v["mismatches"])

    print_report(results, elapsed)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"JSON report saved → {args.out}\n")


if __name__ == "__main__":
    main()
