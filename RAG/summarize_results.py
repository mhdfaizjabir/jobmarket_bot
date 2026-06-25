"""
summarize_results.py
--------------------
Turn an evaluate_mcq.py JSON report into shareable outputs:
  - mcq_summary.txt   : a copy-paste scorecard (for WhatsApp / email)
  - mcq_results.xlsx   : per-question detail + a Summary sheet (for Drive)

Run:
    python summarize_results.py                 # reads mcq_results.json
    python summarize_results.py my_results.json
"""

import json
import sys
from collections import defaultdict

import pandas as pd


def acc(rows):
    n = len(rows)
    c = sum(r["is_correct"] for r in rows)
    return c, n, (c / n if n else 0.0)


def scorecard(results) -> str:
    lines = []
    c, n, a = acc(results)
    lines.append("RAG MULTIPLE-CHOICE BENCHMARK — RESULTS")
    lines.append("=" * 42)
    lines.append(f"Overall accuracy: {c}/{n} = {a:.1%}")
    lines.append("")

    def block(field, title):
        lines.append(f"{title}:")
        groups = defaultdict(list)
        for r in results:
            groups[r[field]].append(r)
        for k in sorted(groups):
            c, n, a = acc(groups[k])
            lines.append(f"   {str(k):<16} {c:>4}/{n:<4} = {a:.1%}")
        lines.append("")

    block("language", "By language (English vs Arabic)")
    block("file", "By benchmark file")
    block("country", "By country")
    return "\n".join(lines)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "mcq_results.json"
    with open(path, encoding="utf-8") as f:
        results = json.load(f)

    text = scorecard(results)
    print(text)

    with open("mcq_summary.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")

    # Per-question detail + a tidy Summary sheet, in one Excel file.
    detail = pd.DataFrame(results)[
        ["file", "language", "country", "category", "question",
         "chosen", "correct", "is_correct"]
    ]

    rows = []
    def add(label, sub):
        c, n, a = acc(sub)
        rows.append({"Group": label, "Correct": c, "Total": n,
                     "Accuracy": round(a * 100, 1)})
    add("OVERALL", results)
    for lang in sorted({r["language"] for r in results}):
        add(f"Language: {lang}", [r for r in results if r["language"] == lang])
    for ctry in sorted({r["country"] for r in results}):
        add(f"Country: {ctry}", [r for r in results if r["country"] == ctry])
    summary = pd.DataFrame(rows)

    with pd.ExcelWriter("mcq_results.xlsx") as xl:
        summary.to_excel(xl, sheet_name="Summary", index=False)
        detail.to_excel(xl, sheet_name="Per-Question", index=False)

    print("\nSaved:")
    print("  mcq_summary.txt   — copy-paste scorecard")
    print("  mcq_results.xlsx  — Summary + Per-Question sheets (send this to mentor)")


if __name__ == "__main__":
    main()
