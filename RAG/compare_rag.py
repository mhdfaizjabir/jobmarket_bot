"""
compare_rag.py — HyST vs Simple RAG ablation study
----------------------------------------------------
Runs every test case through two pipelines:

  Simple RAG  — embed question → Qdrant top-10 → LLM directly
  HyST        — decompose → SQL + pandas analytics + Qdrant → LLM

Compares on:
  • Factual accuracy   — does the correct number appear in the answer?
  • Keyword coverage   — fraction of expected keywords hit
  • Hallucination rate — numbers in answer NOT present in retrieved context
  • Avg semantic score — quality of vector search hits

Run:
    python compare_rag.py
    python compare_rag.py --model gpt-4o-mini
    python compare_rag.py --out comparison.json
    python compare_rag.py --skip-answer     # SQL checks only, no LLM (fast)
"""

import argparse
import json
import re
import sys
import time
from typing import Any

import pandas as pd

# UTF-8 output for Arabic
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from analytics import AnalyticsEngine
from config import DATA_DIR, CHAT_MODEL, make_client, INTERNAL_MODEL
from data_loader import load_all
from evaluate import TEST_CASES, check_sql_correctness, check_relevancy
from rag_engine import RAGEngine
from vector_store import VectorStore


# ---------------------------------------------------------------------------
# Simple RAG — baseline (semantic search only, no SQL / pandas)
# ---------------------------------------------------------------------------

SIMPLE_SYSTEM = """\
You are a GCC job market assistant. Answer the user's question using ONLY the
job posting excerpts provided below. Be specific and cite details from the data.
If the data is insufficient, say "Not enough data to answer precisely."
Never invent numbers not present in the provided excerpts.
End with: "You might also want to ask: [follow-up question]"
"""

def simple_rag_answer(
    question: str,
    vs: VectorStore,
    model: str,
    n_results: int = 10,
) -> tuple[str, list[dict]]:
    """
    Pure semantic RAG: embed → search → LLM.
    Returns (answer_text, hits_list).
    """
    hits = vs.search(question, n_results=n_results)

    if not hits:
        docs_block = "No relevant job postings found."
    else:
        docs_block = "\n\n".join(
            f"[Posting {i+1}]\n{h['document']}"
            for i, h in enumerate(hits)
        )

    user_msg = (
        f"JOB POSTING DATA:\n{docs_block}\n\n"
        f"---\nQUESTION: {question}"
    )

    client, bare_model = make_client(model)
    if model.startswith("fanar/"):
        user_msg = user_msg[:2500]          # Fanar context limit

    resp = client.chat.completions.create(
        model=bare_model,
        messages=[
            {"role": "system", "content": SIMPLE_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.2,
        stream=False,
    )
    answer = resp.choices[0].message.content.strip()
    return answer, hits


# ---------------------------------------------------------------------------
# Hallucination detector
# ---------------------------------------------------------------------------

def _extract_numbers(text: str) -> set[int]:
    """Extract integers > 10 from text (skip years, small counts)."""
    raw = re.findall(r"\b(\d{1,3}(?:,\d{3})+|\d{3,})\b", text)
    out: set[int] = set()
    for n in raw:
        try:
            v = int(n.replace(",", ""))
            if v > 10:
                out.add(v)
        except ValueError:
            pass
    return out


def hallucination_rate(answer: str, context_docs: list[dict]) -> dict:
    """
    Numbers in the answer that do NOT appear in ANY retrieved document.
    High rate → model is making up statistics.
    """
    ctx_text = " ".join(d.get("document", "") for d in context_docs)
    ctx_nums = _extract_numbers(ctx_text)
    ans_nums = _extract_numbers(answer)

    if not ans_nums:
        return {"rate": 0.0, "hallucinated": [], "total_claimed": 0}

    hallucinated = sorted(ans_nums - ctx_nums)
    rate = len(hallucinated) / len(ans_nums)
    return {
        "rate":           round(rate, 2),
        "hallucinated":   hallucinated,
        "total_claimed":  len(ans_nums),
    }


def factual_hit(answer: str, ground_truth_expr: str, df: pd.DataFrame) -> bool | None:
    """
    For numerical questions: is the correct value present in the answer?
    Returns None if no ground truth available.
    """
    if not ground_truth_expr:
        return None
    try:
        expected = eval(ground_truth_expr, {"df": df, "pd": pd, "len": len,
                                            "round": round, "max": max})
    except Exception:
        return None

    if isinstance(expected, (int, float)):
        # Check if any number within 5% of expected appears in the answer
        ans_nums = _extract_numbers(answer)
        for n in ans_nums:
            if abs(n - float(expected)) <= max(5, abs(float(expected)) * 0.05):
                return True
        return False
    elif isinstance(expected, str):
        return expected.lower() in answer.lower()
    elif isinstance(expected, list) and expected:
        return str(expected[0]).lower() in answer.lower()
    return None


def avg_score(hits: list[dict]) -> float:
    if not hits:
        return 0.0
    scores = [1 - h.get("distance", 1.0) for h in hits]
    return round(sum(scores) / len(scores), 3)


# ---------------------------------------------------------------------------
# Comparison runner
# ---------------------------------------------------------------------------

def run_comparison(
    df: pd.DataFrame,
    engine: RAGEngine,
    vs: VectorStore,
    model: str,
    skip_answer: bool = False,
) -> list[dict]:

    results: list[dict] = []

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"  [{i:2}/{len(TEST_CASES)}] {tc.category:<10}  {tc.question[:60]}")

        entry: dict[str, Any] = {
            "question":   tc.question,
            "category":   tc.category,
            "is_numerical": tc.is_numerical,
            "notes":      tc.notes,
            "ground_truth": None,
            "simple_rag": {},
            "hyst":       {},
        }

        # Ground truth value
        if tc.ground_truth_sql:
            try:
                entry["ground_truth"] = eval(
                    tc.ground_truth_sql,
                    {"df": df, "pd": pd, "len": len, "round": round, "max": max}
                )
            except Exception:
                pass

        # ── SQL correctness (HyST only — Simple RAG has no SQL layer) ────────
        sql_check = check_sql_correctness(engine.sql, tc.question, df, tc.ground_truth_sql)

        if skip_answer:
            entry["hyst"]["sql_check"] = sql_check
            results.append(entry)
            continue

        # ── Simple RAG ────────────────────────────────────────────────────────
        try:
            t0 = time.time()
            s_answer, s_hits = simple_rag_answer(tc.question, vs, model)
            s_elapsed = round(time.time() - t0, 1)

            entry["simple_rag"] = {
                "answer":       s_answer,
                "elapsed_s":    s_elapsed,
                "factual_hit":  factual_hit(s_answer, tc.ground_truth_sql, df),
                "relevancy":    check_relevancy(s_answer, tc.expected_keywords),
                "hallucination": hallucination_rate(s_answer, s_hits),
                "avg_hit_score": avg_score(s_hits),
                "n_hits":       len(s_hits),
            }
            print(f"          Simple RAG  {s_elapsed:.1f}s  "
                  f"hallu={entry['simple_rag']['hallucination']['rate']:.0%}  "
                  f"rel={entry['simple_rag']['relevancy']['score']}")
        except Exception as e:
            entry["simple_rag"] = {"answer": f"ERROR: {e}"}
            print(f"          Simple RAG  ERROR: {e}")

        # ── HyST ──────────────────────────────────────────────────────────────
        try:
            t0 = time.time()
            eval_result = engine.answer_eval(tc.question, model=model)
            h_answer    = eval_result["answer"]
            h_elapsed   = round(time.time() - t0, 1)

            # Retrieval hits for hallucination check (best effort — use context text)
            ctx_docs = [{"document": eval_result.get("context", "")}]

            entry["hyst"] = {
                "answer":        h_answer,
                "elapsed_s":     h_elapsed,
                "factual_hit":   factual_hit(h_answer, tc.ground_truth_sql, df),
                "relevancy":     check_relevancy(h_answer, tc.expected_keywords),
                "hallucination": hallucination_rate(h_answer, ctx_docs),
                "sql_check":     sql_check,
                "verification":  eval_result.get("verification", {}),
            }
            print(f"          HyST        {h_elapsed:.1f}s  "
                  f"hallu={entry['hyst']['hallucination']['rate']:.0%}  "
                  f"rel={entry['hyst']['relevancy']['score']}")
        except Exception as e:
            entry["hyst"] = {"answer": f"ERROR: {e}", "sql_check": sql_check}
            print(f"          HyST        ERROR: {e}")

        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(results: list[dict], elapsed: float):

    def pct(v):  return f"{v:.0%}" if v is not None else "—"
    def flt(v):  return f"{v:.3f}" if v is not None else "—"

    # ── Aggregate metrics ────────────────────────────────────────────────────
    def aggregate(key: str) -> dict:
        factual, relevancy, hallu = [], [], []
        for r in results:
            d = r.get(key, {})
            fh = d.get("factual_hit")
            if fh is not None:
                factual.append(float(fh))
            rel = (d.get("relevancy") or {}).get("score")
            if rel is not None:
                relevancy.append(rel)
            hr = (d.get("hallucination") or {}).get("rate")
            if hr is not None:
                hallu.append(hr)
        return {
            "factual":   sum(factual)   / len(factual)   if factual   else None,
            "relevancy": sum(relevancy) / len(relevancy) if relevancy else None,
            "hallu":     sum(hallu)     / len(hallu)     if hallu     else None,
        }

    s_agg = aggregate("simple_rag")
    h_agg = aggregate("hyst")

    sql_graded = [r for r in results if (r.get("hyst") or {}).get("sql_check", {}).get("correct") is not None]
    sql_pass   = sum(1 for r in sql_graded if r["hyst"]["sql_check"]["correct"])

    # ── Header ────────────────────────────────────────────────────────────────
    W = 100
    print("\n" + "═" * W)
    print("  GCC JOB MARKET — HyST vs SIMPLE RAG ABLATION STUDY")
    print("═" * W)

    # ── Per-question table ────────────────────────────────────────────────────
    header = (f"{'#':<3}  {'Cat':<9}  "
              f"{'Simple:Fact':<12} {'Simple:Rel':<11} {'Simple:Hallu':<13}  "
              f"{'HyST:Fact':<10} {'HyST:Rel':<10} {'HyST:Hallu':<11}  "
              f"Question")
    print(f"\n{header}")
    print("─" * W)

    for i, r in enumerate(results, 1):
        s  = r.get("simple_rag", {})
        h  = r.get("hyst", {})

        def _sym(v):
            if v is True:   return "✅"
            if v is False:  return "❌"
            return " —"

        sf = _sym(s.get("factual_hit"))
        hf = _sym(h.get("factual_hit"))
        sr = pct((s.get("relevancy") or {}).get("score"))
        hr = pct((h.get("relevancy") or {}).get("score"))
        sh = pct((s.get("hallucination") or {}).get("rate"))
        hh = pct((h.get("hallucination") or {}).get("rate"))

        q = r["question"][:42] + ("…" if len(r["question"]) > 42 else "")
        print(f"{i:<3}  {r['category']:<9}  "
              f"{sf:<12} {sr:<11} {sh:<13}  "
              f"{hf:<10} {hr:<10} {hh:<11}  {q}")

    print("─" * W)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'METRIC':<38}  {'SIMPLE RAG':<16}  {'HyST (YOURS)':<16}  DELTA")
    print("─" * 85)

    rows = [
        ("Factual accuracy  (numerical Qs)",     s_agg["factual"],   h_agg["factual"],   True),
        ("Answer relevancy  (keyword hit rate)",  s_agg["relevancy"], h_agg["relevancy"], True),
        ("Hallucination rate (lower = better)",   s_agg["hallu"],     h_agg["hallu"],     False),
    ]

    for label, sv, hv, higher_is_better in rows:
        ss = pct(sv) if sv is not None else "n/a"
        hs = pct(hv) if hv is not None else "n/a"
        if sv is not None and hv is not None:
            delta = hv - sv
            sign  = "+" if delta >= 0 else ""
            arrow = "▲" if (delta > 0) == higher_is_better else ("▼" if delta != 0 else "=")
            ds    = f"{arrow} {sign}{delta:.0%}"
        else:
            ds = "n/a"
        print(f"  {label:<36}  {ss:<16}  {hs:<16}  {ds}")

    print(f"  {'SQL correctness (HyST only)':<36}  {'—':<16}  "
          f"{sql_pass}/{len(sql_graded)} ({sql_pass/len(sql_graded)*100:.0f}%)   " if sql_graded else "  n/a")

    print(f"\n  Questions evaluated: {len(results)}  |  Total elapsed: {elapsed:.1f}s")
    print("═" * W + "\n")

    # ── Head-to-head per question for numerical Qs ────────────────────────────
    numerical = [r for r in results if r["is_numerical"] and r.get("simple_rag") and r.get("hyst")]
    if numerical:
        print("HEAD-TO-HEAD  (numerical questions only)")
        print("─" * W)
        for r in numerical:
            gt  = r.get("ground_truth", "?")
            sf  = r.get("simple_rag", {}).get("factual_hit")
            hf  = r.get("hyst", {}).get("factual_hit")
            winner = ""
            if sf is True  and hf is False: winner = "  ← Simple RAG wins"
            if sf is False and hf is True:  winner = "  ← HyST wins ✓"
            if sf is True  and hf is True:  winner = "  ← Both correct"
            if sf is False and hf is False: winner = "  ← Both wrong"
            print(f"  {r['question'][:60]}")
            print(f"    Ground truth: {gt}  |  Simple: {'✅' if sf else '❌'}  "
                  f"HyST: {'✅' if hf else '❌'}{winner}")
        print()

    # ── Worst hallucinations in Simple RAG ───────────────────────────────────
    bad_hallu = sorted(
        [r for r in results if (r.get("simple_rag") or {}).get("hallucination", {}).get("rate", 0) > 0.3],
        key=lambda r: r["simple_rag"]["hallucination"]["rate"],
        reverse=True,
    )
    if bad_hallu:
        print("HIGH-HALLUCINATION questions in Simple RAG (rate > 30%)")
        print("─" * W)
        for r in bad_hallu[:5]:
            h = r["simple_rag"]["hallucination"]
            print(f"  {r['question'][:70]}")
            print(f"    Hallucination rate: {h['rate']:.0%}  |  "
                  f"Invented numbers: {h['hallucinated'][:6]}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",       default=CHAT_MODEL)
    parser.add_argument("--out",         default="comparison.json")
    parser.add_argument("--skip-answer", action="store_true",
                        help="SQL check only — no LLM calls (fast)")
    args = parser.parse_args()

    print("\nLoading data…")
    df, timelines = load_all(DATA_DIR)
    print(f"  {len(df):,} rows | timelines: {timelines}")

    print("Connecting to Qdrant…")
    vs = VectorStore()
    print(f"  {vs.count():,} vectors indexed")

    analytics = AnalyticsEngine(df)
    engine    = RAGEngine(analytics, vs)

    print(f"\nRunning {len(TEST_CASES)} questions through both pipelines")
    print(f"Model: {args.model}\n")

    t0 = time.time()
    results = run_comparison(df, engine, vs, args.model, skip_answer=args.skip_answer)
    elapsed = time.time() - t0

    print_report(results, elapsed)

    if args.out:
        # Make sets JSON-serialisable
        def _clean(obj):
            if isinstance(obj, set): return sorted(obj)
            return obj

        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=_clean)
        print(f"Full comparison saved → {args.out}\n")


if __name__ == "__main__":
    main()
