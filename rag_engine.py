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
from config import (
    CHAT_MODEL, build_system_prompt, TOP_K,
    OPENAI_API_KEY, FANAR_API_KEY, FANAR_BASE_URL,
)

load_dotenv()

_MAX_SEMANTIC_DOCS = 12
_MAX_HISTORY_TURNS = 6


def _make_client(model: str) -> tuple[OpenAI, str]:
    """
    Return (OpenAI client, bare model name) for the given model string.
    Fanar models are prefixed with 'fanar/' — strip the prefix and use
    Fanar's base URL + API key.  Everything else goes to OpenAI.
    """
    if model.startswith("fanar/"):
        bare = model[len("fanar/"):]
        key  = FANAR_API_KEY or os.getenv("FANAR_API_KEY", "")
        return OpenAI(api_key=key, base_url=FANAR_BASE_URL), bare
    return OpenAI(api_key=OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")), model

# Fields where ChromaDB supports exact-match metadata filtering
# _country added so "salary in Qatar" correctly scopes to Qatar only
_CHROMA_EXACT_FIELDS = {"career_level", "employment_type", "_timeline", "education", "_country"}

# Country aliases recognised in natural language → canonical _country value in the data
_COUNTRY_ALIASES: dict[str, str] = {
    "qatar":               "Qatar",
    "uae":                 "UAE",
    "united arab emirates":"UAE",
    "dubai":               "UAE",
    "abu dhabi":           "UAE",
    "ksa":                 "Saudi Arabia",
    "saudi":               "Saudi Arabia",
    "saudi arabia":        "Saudi Arabia",
    "kingdom of saudi arabia": "Saudi Arabia",
    "bahrain":             "Bahrain",
    "kuwait":              "Kuwait",
    "oman":                "Oman",
}


def _build_decompose_system(timelines: list[str], countries: list[str]) -> str:
    """
    Build the decompose system prompt dynamically so it always knows
    which timelines and countries are actually in the database.
    This prevents the LLM from guessing or hallucinating filter values.
    """
    tl_str  = " | ".join(f'"{t}"' for t in timelines)
    co_str  = " | ".join(f'"{c}"' for c in countries)
    loc_ex  = "Doha, Riyadh, Dubai, Khobar, Abu Dhabi"

    return f"""\
You decompose questions about GCC (Gulf) job market data for a hybrid retrieval system.
You will receive recent conversation history — use it to resolve pronouns and references
(e.g. "they", "those companies", "that role", "same sector") before decomposing.

AVAILABLE DATA:
  Countries in database : {co_str}
  Timelines in database : {tl_str}

Available structured filter fields:
  _country        — MUST be one of: {co_str}
                    Use whenever user mentions a country/city.
                    "in Qatar" → "Qatar", "Saudi jobs" → "Saudi Arabia"
  _timeline       — MUST be one of: {tl_str}
                    Use only when user specifies a time period.
  job_title       — specific role the user is asking about (free text, CONTAINS match).
                    Use when user asks about a specific job title or role.
                    Examples: "software developer" → job_title: "software developer"
                              "data analyst salary" → job_title: "data analyst"
                              "civil engineer jobs" → job_title: "civil engineer"
                              "nurse" → job_title: "nurse"
                    Do NOT use for generic questions like "what jobs are available".
  category        — sector/industry name (e.g. "Engineering", "Healthcare", "Construction")
                    Use for field-level questions, not role-level questions.
  career_level    — one of: "Entry Level" | "Mid Career" | "Senior" | "Management" | "Executive"
  employment_type — one of: "Full Time" | "Part Time" | "Contract" | "Temporary"
  education       — one of: "Bachelor" | "Master" | "MBA" | "Diploma" | "PhD"
  location        — city name (e.g. {loc_ex})
  company         — employer name (e.g. "Qatar Energy", "Qatar Foundation")

Return valid JSON only — no explanation, no markdown fences:
{{
  "filters": {{}},
  "semantic_query": "",
  "needs_aggregation": false,
  "analysis_types": [],
  "resolved_question": ""
}}

Rules:
  filters           — include _country whenever a country/city is mentioned.
                      Use exact values from the lists above.
  semantic_query    — the descriptive/subjective part; omit what is in filters.
  needs_aggregation — true for: counts, averages, rankings, comparisons, trends,
                      "how many", "most", "top N", "which sector", "compare".
  analysis_types    — subset of: ["skills","salary","companies","sectors","trends",
                      "education","experience","language","career_level"]
  resolved_question — rewrite fully self-contained, replacing all pronouns.
"""


# ---------------------------------------------------------------------------
# Module-level helpers (no class state needed)
# ---------------------------------------------------------------------------

def _apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """
    Narrow the DataFrame using the decomposed structured filters.

    job_title uses OR-word CONTAINS matching so "software developer" matches
    "Software Engineer", "Senior Developer", "Full-Stack Developer", etc.
    All other structured filters use exact-match or substring-match.
    """
    result = df
    for field, value in filters.items():
        if field == "job_title":
            # Soft role filter: any row where job_title contains ANY word from value
            if "job_title" not in result.columns:
                continue
            words = [w for w in str(value).lower().split() if len(w) > 2]
            if not words:
                continue
            pattern = "|".join(re.escape(w) for w in words)
            mask    = result["job_title"].str.contains(pattern, case=False, na=False)
            narrowed = result[mask]
            # Only apply if we get at least 3 results — else keep original
            result = narrowed if len(narrowed) >= 3 else result
        elif field not in result.columns:
            continue
        elif field in _CHROMA_EXACT_FIELDS:
            col    = result[field].astype(str)
            result = result[col.str.lower() == str(value).lower()]
        else:
            col    = result[field].astype(str)
            result = result[col.str.contains(re.escape(str(value)), case=False, na=False)]

    return result if len(result) > 0 else df   # never return empty subset


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
        # Default client (OpenAI) — swapped per-call based on model choice
        self._client = OpenAI(api_key=OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", ""))
        self.sql = SQLEngine(analytics.df)

    # ── Step 1: decompose ────────────────────────────────────────────────────

    def _decompose(self, question: str, chat_history: list[dict] | None = None) -> dict:
        """
        Split the question into filters, semantic query, and analysis types.

        The system prompt is built dynamically from the actual timelines and
        countries in the database — so adding UAE or KSA data is picked up
        automatically without any code changes.
        """
        # Build dynamic system prompt with real timelines + countries
        df = self.analytics.df
        timelines = self.analytics.timelines
        countries = sorted(df["_country"].dropna().unique().tolist()) \
                    if "_country" in df.columns else []
        system = _build_decompose_system(timelines, countries)

        messages = [{"role": "system", "content": system}]
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
                max_tokens=400,
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)
            result = json.loads(raw)

            # Safety net: resolve country aliases in case LLM used informal names
            filters = result.get("filters", {})
            if "_country" in filters:
                canonical = _COUNTRY_ALIASES.get(filters["_country"].lower())
                if canonical:
                    filters["_country"] = canonical
            result["filters"] = filters
            return result

        except Exception:
            # Fallback: try to extract country from question text ourselves
            filters: dict = {}
            q_lower = question.lower()
            for alias, canonical in _COUNTRY_ALIASES.items():
                if alias in q_lower:
                    filters["_country"] = canonical
                    break
            return {
                "filters":          filters,
                "semantic_query":   question,
                "needs_aggregation":True,
                "analysis_types":   [],
                "resolved_question":question,
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
        model: str | None = None,
    ) -> Generator[str, None, None]:
        """
        Stream the answer token-by-token.
        Compatible with Streamlit's st.write_stream().

        Parameters
        ----------
        model : override the default CHAT_MODEL for this call (from UI selector)
        """
        context = self._build_full_context(question, chat_history)

        # Build system prompt dynamically — picks up any new country/timeline added
        df       = self.analytics.df
        countries = sorted(df["_country"].dropna().unique().tolist()) if "_country" in df.columns else []
        system   = build_system_prompt(
            countries       = countries,
            timelines       = self.analytics.timelines,
            total_postings  = len(df),
        )
        messages: list[dict] = [{"role": "system", "content": system}]

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

        client, bare_model = _make_client(model or CHAT_MODEL)
        stream = client.chat.completions.create(
            model=bare_model,
            messages=messages,
            temperature=0.2,
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def get_retrieval_info(
        self,
        question: str,
        chat_history: list[dict] | None = None,
    ) -> dict:
        """
        Return retrieval metadata for the transparency panel (no streaming).
        Shows: decomposition, which layers ran, semantic search scores.
        """
        decomposed     = self._decompose(question, chat_history)
        filters        = decomposed.get("filters", {})
        semantic_q     = decomposed.get("semantic_query") or question
        needs_agg      = decomposed.get("needs_aggregation", False)
        analysis_types = decomposed.get("analysis_types", [])

        layers_used: list[str] = []

        sql_result = ""
        if needs_agg:
            layers_used.append("SQL / Pandas")
            sql_result = self.sql.get_context(decomposed.get("resolved_question") or question)

        semantic_hits: list[dict] = []
        if self.vs.count() > 0:
            layers_used.append("ChromaDB (semantic search)")
            chroma_where = _to_chroma_where(filters)
            try:
                results = self.vs.search(semantic_q, n_results=8, where=chroma_where)
            except Exception:
                results = self.vs.search(semantic_q, n_results=8)
            for r in results:
                semantic_hits.append({
                    "title":    r["metadata"].get("job_title", "—"),
                    "company":  r["metadata"].get("company", "—"),
                    "sector":   r["metadata"].get("category", "—"),
                    "timeline": r["metadata"].get("_timeline", "—"),
                    "country":  r["metadata"].get("_country", "—"),
                    "score":    round(1 - r["distance"], 3),   # cosine similarity
                })

        return {
            "decomposed":     decomposed,
            "filters":        filters,
            "analysis_types": analysis_types,
            "needs_agg":      needs_agg,
            "layers_used":    layers_used,
            "sql_snippet":    sql_result[:600] if sql_result else "",
            "semantic_hits":  semantic_hits,
        }
