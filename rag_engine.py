"""
rag_engine.py
-------------
HyST-inspired hybrid pipeline (Hybrid retrieval over Semi-Structured Tabular data):

  1. Decompose — one fast LLM call splits every question into:
       • structured filters  (career level, sector, timeline, …)
       • semantic query      (descriptive / subjective part)
       • analysis types      (what pandas stats are actually needed)
       • needs_aggregation   (should SQL run?)

  2. SQL analytics    — handles counts, rankings, trends, comparisons
  3. Pandas analytics — handles skills & salary (need text parsing SQL can't do)
       runs on the FILTERED subset, not all 5,424 rows
  4. ChromaDB search  — semantic similarity within structurally-filtered candidates

  5. GPT-4o-mini synthesises a streaming answer from all three layers.
"""

import json
import os
import re
from typing import Generator

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from analytics import AnalyticsEngine
from sql_engine import SQLEngine
from vector_store import VectorStore
from config import CHAT_MODEL, SYSTEM_PROMPT, TOP_K

load_dotenv()

_MAX_SEMANTIC_DOCS = 12
_MAX_HISTORY_TURNS = 6

# Fields where ChromaDB supports exact-match metadata filtering
_CHROMA_EXACT_FIELDS = {"career_level", "employment_type", "_timeline", "education"}

_DECOMPOSE_SYSTEM = """\
You decompose questions about Qatar job market data for a hybrid retrieval system.
You will receive recent conversation history — use it to resolve pronouns and references
(e.g. "they", "those companies", "that role", "same sector") before decomposing.

Available structured filter fields and their exact allowed values:
  category        — free text sector name (e.g. "Information Technology", "Oil and Gas",
                    "Healthcare", "Finance", "Construction", "Education", "Hospitality")
  career_level    — exactly one of: "Entry Level", "Mid Career", "Senior", "Management", "Executive"
  employment_type — exactly one of: "Full Time", "Part Time", "Contract", "Temporary"
  _timeline       — exactly "Nov 2025" or "Feb 2026"
  education       — exactly one of: "Bachelor", "Master", "MBA", "Diploma", "PhD"
  location        — Qatar city (e.g. "Doha", "Al Rayyan", "Lusail")
  company         — employer name (e.g. "Qatar Energy", "Qatar Foundation")

Return valid JSON only — no explanation, no markdown fences:
{
  "filters": {},
  "semantic_query": "",
  "needs_aggregation": false,
  "analysis_types": [],
  "resolved_question": ""
}

Rules:
  filters           — only fields explicitly stated or clearly implied; use exact values for
                      career_level / employment_type / _timeline / education.
  semantic_query    — the descriptive/subjective part for vector search; remove anything
                      already captured in filters; keep it concise.
  needs_aggregation — true when the question asks for counts, rankings, averages,
                      trends, comparisons, "most", "top", "how many", "which sector".
  analysis_types    — list any subset of:
                      ["skills", "salary", "companies", "sectors", "trends",
                       "education", "experience", "language", "career_level"]
                      Include only what is relevant to the question.
  resolved_question — rewrite the user's question as a fully self-contained query with
                      all pronouns and references replaced by their explicit terms from
                      the conversation (used for SQL and semantic search).
                      Example: "how much do they pay?" with context about DS/AI jobs →
                      "what salary do data science and AI companies in Qatar offer?"
"""


# ---------------------------------------------------------------------------
# Module-level helpers (no class state needed)
# ---------------------------------------------------------------------------

def _apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Narrow the DataFrame using the decomposed structured filters."""
    result = df
    for field, value in filters.items():
        if field not in result.columns:
            continue
        col = result[field].astype(str)
        if field in _CHROMA_EXACT_FIELDS:
            result = result[col.str.lower() == str(value).lower()]
        else:
            result = result[col.str.contains(re.escape(str(value)), case=False, na=False)]
    return result if len(result) > 0 else df   # never return an empty subset


def _to_chroma_where(filters: dict) -> dict | None:
    """Convert filters to a ChromaDB-compatible where clause (exact-match fields only)."""
    exact = {k: {"$eq": v} for k, v in filters.items() if k in _CHROMA_EXACT_FIELDS}
    if not exact:
        return None
    if len(exact) == 1:
        k, v = next(iter(exact.items()))
        return {k: v}
    return {"$and": [{k: v} for k, v in exact.items()]}


# ---------------------------------------------------------------------------
# RAGEngine
# ---------------------------------------------------------------------------

class RAGEngine:
    def __init__(self, analytics: AnalyticsEngine, vector_store: VectorStore):
        self.analytics = analytics
        self.vs = vector_store
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.sql = SQLEngine(analytics.df)

    # ── Step 1: decompose ────────────────────────────────────────────────────

    def _decompose(self, question: str, chat_history: list[dict] | None = None) -> dict:
        """Split the question into filters, semantic query, and analysis types.
        Passes recent chat history so pronouns/references can be resolved."""
        messages = [{"role": "system", "content": _DECOMPOSE_SYSTEM}]

        # Last 2 turns (4 messages) give enough context for reference resolution
        # Truncate content to avoid wasting tokens on long prior answers
        if chat_history:
            for msg in chat_history[-4:]:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"][:400],
                })

        messages.append({"role": "user", "content": question})

        try:
            resp = self._client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                temperature=0,
                max_tokens=350,
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)
            return json.loads(raw)
        except Exception:
            return {
                "filters": {},
                "semantic_query": question,
                "needs_aggregation": True,
                "analysis_types": [],
                "resolved_question": question,
            }

    # ── Step 2–4: build context ──────────────────────────────────────────────

    def _build_full_context(self, question: str, chat_history: list[dict] | None = None) -> str:
        decomposed     = self._decompose(question, chat_history)
        filters        = decomposed.get("filters", {})
        semantic_q     = decomposed.get("semantic_query") or question
        needs_agg      = decomposed.get("needs_aggregation", False)
        analysis_types = decomposed.get("analysis_types", [])
        resolved_q     = decomposed.get("resolved_question") or question

        ov = self.analytics.overview()
        parts = [
            f"DATASET SUMMARY: {ov['total_postings']:,} total postings | "
            f"timelines: {', '.join(str(t) for t in ov['timelines'])} | "
            f"salary coverage: {ov['salary_coverage']}"
        ]

        # Step 2 — SQL: aggregation, rankings, trend comparisons
        if needs_agg:
            sql_ctx = self.sql.get_context(resolved_q)
            if sql_ctx:
                parts.append(sql_ctx)

        # Step 3 — Pandas: skills & salary on the FILTERED subset
        if analysis_types:
            filtered_df = _apply_filters(self.analytics.df, filters)
            sub = AnalyticsEngine(filtered_df)

            type_map = {
                "skills":       lambda: sub.skill_stats(n=15),
                "salary":       lambda: sub.salary_stats(),
                "companies":    lambda: sub.company_stats(10),
                "sectors":      lambda: sub.sector_stats(),
                "experience":   lambda: sub.experience_stats(),
                "education":    lambda: sub.education_stats(),
                "language":     lambda: sub.language_stats(),
                "career_level": lambda: sub.career_level_stats(),
                "trends":       lambda: sub.trend_comparison(),
            }
            for atype, fn in type_map.items():
                if atype in analysis_types:
                    parts.append(fn())

        # Step 4 — ChromaDB: semantic search within structurally-filtered candidates
        if self.vs.count() > 0:
            chroma_where = _to_chroma_where(filters)
            try:
                results = self.vs.search(
                    semantic_q,
                    n_results=_MAX_SEMANTIC_DOCS,
                    where=chroma_where,
                )
            except Exception:
                results = self.vs.search(semantic_q, n_results=_MAX_SEMANTIC_DOCS)

            if results:
                lines = [f"RELEVANT JOB POSTINGS (top {len(results)} by semantic similarity):\n"]
                for i, r in enumerate(results, 1):
                    lines.append(f"[Posting {i}]")
                    lines.append(r["document"])
                    lines.append("")
                parts.append("\n".join(lines))

        return "\n\n".join(filter(None, parts))

    # ── Public API ───────────────────────────────────────────────────────────

    def answer(
        self,
        question: str,
        chat_history: list[dict] | None = None,
    ) -> Generator[str, None, None]:
        """
        Stream the answer token-by-token.
        Compatible with Streamlit's st.write_stream().
        """
        context = self._build_full_context(question, chat_history)

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        if chat_history:
            messages.extend(chat_history[-(_MAX_HISTORY_TURNS * 2):])

        messages.append({
            "role": "user",
            "content": (
                f"DATA CONTEXT (use this data to answer accurately):\n"
                f"{context}\n\n"
                f"---\n"
                f"USER QUESTION: {question}"
            ),
        })

        stream = self._client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.2,
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
