"""
evaluate_mcq.py
---------------
Grade the RAG against the multiple-choice benchmarks the mentor created.

For each MCQ we hand the RAG the question + the four options and ask it to
reply with a single letter (A/B/C/D). We then compare to Correct_Option.
Because grading is just letter-matching, accuracy is fully objective.

Only rows whose source file(s) are present in data/ are scored, so the RAG is
never penalised for data it was never given (e.g. LinkedIn or the June scrape).

Run:
    python evaluate_mcq.py                       # quick sample (default 20 per lang per file)
    python evaluate_mcq.py --full                # every usable row
    python evaluate_mcq.py --sample 50           # 50 per language per file
    python evaluate_mcq.py --file mcq            # only the same-questions MCQ file
    python evaluate_mcq.py --file source         # only the FromSource MCQ file
    python evaluate_mcq.py --out mcq_results.json
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

# Windows terminals default to cp1252 — force UTF-8 so Arabic prints correctly.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from analytics import AnalyticsEngine
from data_loader import load_all
from rag_engine import RAGEngine
from vector_store import VectorStore
from config import CHAT_MODEL

BENCHMARK_FILES = {
    "mcq":    "RAG_Benchmark_Jobs_GCC_MCQ.xlsx",      # same questions, MCQ form
    "source": "RAG_MCQ_Jobs_GCC_FromSource.xlsx",     # generated from raw job data
}

LETTERS = ["A", "B", "C", "D"]


def _usable(filename: str, available: set[str]) -> bool:
    """True if every source file referenced by the row is present in data/."""
    if not isinstance(filename, str) or not filename.strip():
        return False
    files = [f.strip() for f in filename.split(";") if f.strip()]
    return bool(files) and all(f in available for f in files)


def _country(filename: str) -> str:
    fn = (filename or "").lower()
    if "qatar" in fn:        return "Qatar"
    if "saudi" in fn:        return "Saudi Arabia"
    if "uae" in fn:          return "UAE"
    return "Unknown"


def build_prompt(row) -> str:
    """Question + four options, instructing the model to answer with one letter."""
    opts = "\n".join(f"{L}. {row[f'Option_{L}']}" for L in LETTERS)
    return (
        "Answer the following multiple-choice question using the job-market data. "
        "Choose the single best option. Reply with ONLY the letter (A, B, C, or D) "
        "and nothing else.\n\n"
        f"Question: {row['Question']}\n\n"
        f"{opts}\n\n"
        "Answer (letter only):"
    )


def parse_letter(answer: str) -> str | None:
    """Extract the chosen A/B/C/D from a free-text answer."""
    if not answer:
        return None
    # Prefer a standalone letter at the very start, e.g. "B" or "B." or "B)"
    m = re.match(r"\s*([ABCD])\b", answer.strip(), re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Fallback: first standalone letter anywhere
    m = re.search(r"\b([ABCD])\b", answer, re.IGNORECASE)
    return m.group(1).upper() if m else None


def select_rows(df: pd.DataFrame, available: set[str], sample: int | None) -> pd.DataFrame:
    df = df[df["Filename"].apply(lambda f: _usable(f, available))].copy()
    df["_country"] = df["Filename"].apply(_country)
    if sample is None:
        return df
    # Balanced sample: `sample` rows per (language) — keeps EN/AR comparable.
    parts = []
    for lang, g in df.groupby("Language"):
        parts.append(g.sample(min(sample, len(g)), random_state=42))
    return pd.concat(parts) if parts else df


def run_file(key: str, engine: RAGEngine, available: set[str],
             sample: int | None, model: str) -> list[dict]:
    path = BENCHMARK_FILES[key]
    df = pd.read_excel(path)
    rows = select_rows(df, available, sample)
    print(f"\n=== {path} — scoring {len(rows)} rows "
          f"({'sample' if sample else 'FULL'}) ===")

    results = []
    for i, (_, row) in enumerate(rows.iterrows(), 1):
        prompt = build_prompt(row)
        try:
            out = engine.answer_eval(prompt, model=model)
            raw = out["answer"]
            chosen = parse_letter(raw)
        except Exception as e:
            raw, chosen = f"ERROR: {e}", None

        correct = str(row["Correct_Option"]).strip().upper()
        ok = (chosen == correct)
        results.append({
            "file": key,
            "language": row["Language"],
            "country": row["_country"],
            "category": row.get("Category", ""),
            "question": row["Question"],
            "chosen": chosen,
            "correct": correct,
            "is_correct": ok,
            "raw_answer": raw[:200],
        })
        mark = "✓" if ok else ("?" if chosen is None else "✗")
        if i % 10 == 0 or i == len(rows):
            done = sum(r["is_correct"] for r in results)
            print(f"  [{i:>4}/{len(rows)}] running acc: {done}/{i} = {done/i:.1%}")
    return results


def report(results: list[dict], elapsed: float):
    def acc(rows):
        n = len(rows)
        c = sum(r["is_correct"] for r in rows)
        return c, n, (c / n if n else 0.0)

    print("\n" + "=" * 60)
    print("RAG MCQ BENCHMARK RESULTS")
    print("=" * 60)
    c, n, a = acc(results)
    print(f"Overall: {c}/{n} = {a:.1%}   ({elapsed:.0f}s)")

    unparsed = sum(1 for r in results if r["chosen"] is None)
    if unparsed:
        print(f"  (couldn't parse a letter from {unparsed} answers — counted wrong)")

    def breakdown(field, title):
        print(f"\nBy {title}:")
        groups = defaultdict(list)
        for r in results:
            groups[r[field]].append(r)
        for k in sorted(groups):
            c, n, a = acc(groups[k])
            print(f"  {str(k):<16} {c:>4}/{n:<4} = {a:.1%}")

    breakdown("language", "language (English vs Arabic)")
    breakdown("file", "benchmark file")
    breakdown("country", "country")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=CHAT_MODEL)
    ap.add_argument("--sample", type=int, default=20,
                    help="rows per language per file (default 20)")
    ap.add_argument("--full", action="store_true", help="score every usable row")
    ap.add_argument("--file", choices=["mcq", "source", "both"], default="both")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    sample = None if args.full else args.sample
    available = set(os.listdir("data"))
    print("Files in data/ (RAG will index these):")
    for f in sorted(available):
        print("  ", f)

    print("\nLoading data…")
    df, timelines = load_all()
    print(f"  Loaded {len(df):,} rows | timelines: {timelines}")
    analytics = AnalyticsEngine(df)
    print("Initialising vector store…")
    vs = VectorStore()
    engine = RAGEngine(analytics, vs)

    keys = ["mcq", "source"] if args.file == "both" else [args.file]
    t0 = time.time()
    results = []
    for k in keys:
        results += run_file(k, engine, available, sample, args.model)
    elapsed = time.time() - t0

    report(results, elapsed)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nJSON report saved → {args.out}")


if __name__ == "__main__":
    main()
