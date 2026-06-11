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

  5. LLM synthesises a streaming answer from all three layers.
"""

import difflib
import json
import re
from typing import Generator

import pandas as pd
from dotenv import load_dotenv

from analytics import AnalyticsEngine
from sql_engine import SQLEngine
from vector_store import VectorStore, _build_doc_text, _build_metadata
from config import CHAT_MODEL, INTERNAL_MODEL, build_system_prompt, make_client

load_dotenv()

_MAX_SEMANTIC_DOCS = 12
_MAX_HISTORY_TURNS = 6


# make_client is imported from config — routes fanar/ prefix to Fanar API

# Fields where ChromaDB supports exact-match metadata filtering.
# Use only the core scope filters from the dataset for exact retrieval context.
_CHROMA_EXACT_FIELDS = {"career_level", "_timeline", "_country"}

# Country aliases recognised in natural language → canonical _country value in the data.
# The actual set of supported countries is built from the loaded dataset so new GCC
# countries can be added by updating the data only.
_BASE_COUNTRY_ALIASES: dict[str, str] = {
    "qatar": "Qatar",
    "uae": "UAE",
    "united arab emirates": "UAE",
    "dubai": "UAE",
    "abu dhabi": "UAE",
    "ksa": "Saudi Arabia",
    "saudi": "Saudi Arabia",
    "saudi arabia": "Saudi Arabia",
    "kingdom of saudi arabia": "Saudi Arabia",
    "bahrain": "Bahrain",
    "kuwait": "Kuwait",
    "oman": "Oman",
}

def _build_country_alias_map(countries: list[str]) -> dict[str, str]:
    """Build a lookup map from country aliases to canonical dataset values."""
    alias_map: dict[str, str] = {}
    for country in countries:
        if not country or not isinstance(country, str):
            continue
        alias_map[country.strip().lower()] = country

    for alias, canonical in _BASE_COUNTRY_ALIASES.items():
        if canonical in countries:
            alias_map[alias] = canonical

    return alias_map


def _normalize_country(country: str, countries: list[str]) -> str | None:
    if not isinstance(country, str) or not country.strip():
        return None
    alias_map = _build_country_alias_map(countries)
    return alias_map.get(country.strip().lower())


# Phrasing that signals the question is explicitly about the whole GCC/Gulf
# region rather than one country — e.g. "across the GCC", "in the Gulf region".
_REGION_WIDE_RE = re.compile(
    r"\b(gcc|gulf countries|gulf region|gulf states|across the (gcc|gulf|region)|"
    r"whole (gcc|gulf)|entire (gcc|gulf)|all (of )?(the )?(gcc|gulf)|"
    r"region[\s-]wide|across the region)\b",
    re.IGNORECASE,
)


def _drop_hallucinated_country(filters: dict, question: str, countries: list[str]) -> dict:
    """
    Remove a single-country filter the decomposer invented for a question that's
    explicitly region-wide (mentions "GCC"/"Gulf region"/etc.) and never actually
    names that country anywhere in the text — e.g. "top in-demand skills across
    the GCC" getting silently scoped to just "UAE".

    Leaves the filter alone for normal single-country questions (including ones
    that reference a city rather than the country name) — only fires when the
    region-wide phrasing AND the absence of any mention of the chosen country
    both hold, so it can't misfire on legitimate single-country scoping.
    """
    country = filters.get("_country")
    if not country or not _REGION_WIDE_RE.search(question):
        return filters
    alias_map = _build_country_alias_map(countries)
    q_lower = question.lower()
    mentioned = any(
        alias in q_lower for alias, canonical in alias_map.items() if canonical == country
    )
    if not mentioned:
        filters = dict(filters)
        filters.pop("_country", None)
    return filters


def _build_decompose_system(df: pd.DataFrame, timelines: list[str], countries: list[str]) -> str:
    """
    Build the decompose system prompt entirely from the actual loaded DataFrame —
    timelines, countries, career levels, employment types, education values,
    top companies, and top cities are all derived at call time, so adding new
    data dumps requires zero code changes.
    """
    tl_str = " | ".join(f'"{t}"' for t in timelines)
    co_str = " | ".join(f'"{c}"' for c in countries)

    # Career levels — prefer the normalised column so values are consistent
    _career_col = "_career_norm" if "_career_norm" in df.columns else "career_level"
    _career_vals = sorted(df[_career_col].dropna().unique().tolist())
    cl_str = " | ".join(f'"{v}"' for v in _career_vals) if _career_vals \
        else '"Entry-Level" | "Mid-Level" | "Senior" | "Manager" | "Director" | "Executive"'

    # Employment types — prefer normalised column
    _emp_col = "_employment_norm" if "_employment_norm" in df.columns else "employment_type"
    _emp_vals = sorted(df[_emp_col].dropna().unique().tolist())
    et_str = " | ".join(f'"{v}"' for v in _emp_vals) if _emp_vals \
        else '"Full-Time" | "Part-Time" | "Contract" | "Freelance" | "Internship" | "Temporary"'

    # Education — top 8 most common values (avoids huge enum for messy data)
    _edu_vals: list[str] = []
    if "education" in df.columns:
        _edu_vals = df["education"].dropna().value_counts().head(8).index.tolist()
    edu_str = " | ".join(f'"{v}"' for v in _edu_vals) if _edu_vals \
        else '"Bachelor" | "Master" | "MBA" | "Diploma" | "PhD"'

    # Top cities extracted from "City, Country" location strings
    _top_cities: list[str] = []
    if "location" in df.columns:
        _cities = df["location"].dropna().str.split(",").str[0].str.strip()
        _top_cities = _cities[_cities.str.len() > 1].value_counts().head(6).index.tolist()
    loc_ex = ", ".join(_top_cities) if _top_cities else "Doha, Riyadh, Dubai, Abu Dhabi"

    # Top companies by posting volume (real examples, not hardcoded names)
    _top_cos: list[str] = []
    if "company" in df.columns:
        _top_cos = df["company"].dropna().value_counts().head(5).index.tolist()
    company_ex = ", ".join(f'"{c}"' for c in _top_cos) if _top_cos \
        else '"Qatar Energy", "Qatar Foundation"'

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
  career_level    — one of: {cl_str}
                    Use for career experience levels like "Entry-Level".
  job_title       — specific role the user is asking about (free text, CONTAINS match).
                    Use when the question is about a particular job title or role.
                    Examples: "software developer" → job_title: "software developer"
                              "data analyst salary" → job_title: "data analyst"
                              "civil engineer jobs" → job_title: "civil engineer"
                              "nurse" → job_title: "nurse"

Only these structured fields should be used for precise retrieval context.
Other details should remain in semantic_query or resolved_question.

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
                      ALSO true for vague career/field questions like:
                      "is X a good field", "should I go into X", "is X in demand",
                      "what about X jobs", "future of X", "opportunities in X".
                      These need sector + skill data to answer properly.
  analysis_types    — subset of: ["skills","salary","companies","sectors","trends",
                      "education","experience","language","career_level"]
                      For career/field questions always include ["skills","sectors","salary"].
                      For "should I learn X" or "is X in demand" always include ["skills","sectors"].
                      For "what skills", "top N skills", "skills needed", "requirements for", "qualifications
                      for" type questions → ALWAYS include "skills" in analysis_types.
                      For "which companies", "companies hiring", "where to apply" → include "companies".
  resolved_question — MANDATORY: always output a non-empty complete sentence.
                      Rewrite fully self-contained, replacing ALL pronouns (those roles, those companies,
                      that sector, them, they, it, same) by reading the conversation history.
                      Look at the ASSISTANT's previous responses — they list the actual role names,
                      company names, and sectors referenced by pronouns in the current question.
                      CRITICAL: a short follow-up like "just in Qatar" or "what about salary?" or
                      "only for that sector" does NOT start a new topic — it refines the prior question.
                      Always carry forward: the job type, domain (AI, nursing, engineering, etc.),
                      career context (fresh grad, experienced, etc.), and any prior filters.
                      WRONG: user asks about AI jobs → follow-up "what skills needed for those roles?"
                             → resolved: "skills needed for the roles"   ← empty / pronoun left in
                      RIGHT: → resolved: "Top technical and non-technical skills needed for Data
                               Scientist, Machine Learning Engineer, Business Analyst roles in Qatar"
                      WRONG: user asks about AI jobs in Qatar → follow-up "what about in Saudi?"
                             → resolved: "jobs in Saudi"
                      RIGHT: → resolved: "Data Scientist and AI/ML roles available in Saudi Arabia"

TECHNOLOGY/DOMAIN MAPPING — when user asks about a tech field, map it to real data:
  "AI" / "artificial intelligence" → skills: machine learning, deep learning, NLP, python, data science
                                     sectors: IT/Software, Engineering, R&D
  "data science" / "data"          → skills: python, sql, machine learning, analytics, tableau
  "cybersecurity" / "security"     → skills: cybersecurity, network security, ethical hacking
  "cloud"                          → skills: AWS, Azure, cloud computing, DevOps
  "software" / "programming"       → skills: python, javascript, java, software development
  "finance" / "banking"            → sector: Banking/Finance, Accounting
  "healthcare" / "medical"         → sector: Healthcare/Medical/Nursing
  IMPORTANT: Bayt.com does NOT have an "AI" sector — AI jobs appear under IT/Software/Engineering.
  When asked about a technology domain, set needs_aggregation=true and analysis_types=["skills","sectors"].
"""


# ---------------------------------------------------------------------------
# Module-level helpers (no class state needed)
# ---------------------------------------------------------------------------

def _job_title_roles(value: str) -> list[list[str]]:
    """
    Split a (possibly multi-role) job_title filter value into per-role word
    lists, e.g. "Data Scientist, ML Engineer" -> [["data","scientist"], ["engineer"]].
    Words of length <= 2 are dropped as too generic to be useful for matching.
    """
    roles = [r.strip() for r in re.split(r",|\band\b|\bor\b", str(value), flags=re.IGNORECASE) if r.strip()]
    if not roles:
        roles = [str(value)]
    out: list[list[str]] = []
    for role in roles:
        words = [w for w in re.findall(r"[a-z0-9]+", role.lower()) if len(w) > 2]
        if words:
            out.append(words)
    return out


def _job_title_mask(col: pd.Series, value: str) -> pd.Series:
    """
    Boolean mask for job_title matching against `value` (one role, or several
    comma/and/or-separated roles).

    Within a single role, ALL significant words must be present (any order) —
    otherwise a multi-word title like "software engineer" would match every
    posting containing just "engineer" (mechanical engineer, sales engineer,
    civil engineer, etc.), drowning out the role the user actually asked about.
    Across multiple roles (e.g. "Data Scientist, ML Engineer, Business Analyst"
    from `_extract_roles_from_assistant`), a posting matches if ANY role matches.
    """
    mask = pd.Series(False, index=col.index)
    for words in _job_title_roles(value):
        pattern = "".join(f"(?=.*{re.escape(w)})" for w in words)
        mask = mask | col.str.contains(pattern, case=False, na=False, regex=True)
    return mask


def _job_title_matches_text(title: str, value: str) -> bool:
    """Scalar version of `_job_title_mask` for checking a single metadata value."""
    title_l = str(title).lower()
    return any(all(w in title_l for w in words) for words in _job_title_roles(value))


def _apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """
    Narrow the DataFrame using only the core structured filters.

    We only use exact retrieval context from:
      _country, _timeline, career_level
    job_title is also used as a soft role filter because it helps match
    user role queries to the actual postings in the data.

    Other fields in the dataset are not used as strict filter context.
    """
    result = df
    for field, value in filters.items():
        if field == "job_title":
            if "job_title" not in result.columns:
                continue
            mask = _job_title_mask(result["job_title"], value)
            if not mask.any():
                continue
            narrowed = result[mask]
            result = narrowed if len(narrowed) >= 3 else result
        elif field == "career_level":
            match_col = "_career_norm" if "_career_norm" in result.columns else "career_level"
            if match_col not in result.columns:
                continue
            col = result[match_col].astype(str)
            narrowed = result[col.str.lower() == str(value).lower()]
            result = narrowed if len(narrowed) > 0 else result
        elif field in {"_country", "_timeline"}:
            if field not in result.columns:
                continue
            col = result[field].astype(str)
            narrowed = result[col.str.lower() == str(value).lower()]
            result = narrowed if len(narrowed) > 0 else result
        else:
            # Ignore all other structured filters in the retrieval context.
            continue

    return result if len(result) > 0 else df


def _find_similar_titles(df: pd.DataFrame, query: str, n: int = 6) -> list[str]:
    """
    Find job titles ACTUALLY present in the data that are closest to `query`,
    using word-overlap + fuzzy string similarity (no hardcoded title lists).

    Used when a user asks about a role that doesn't exist verbatim in the
    dataset (e.g. "blockchain developer" when only "Software Developer" /
    "Backend Developer" exist) — lets the LLM say "closest roles available are
    X, Y" (grounded in real postings) instead of either inventing a match or
    flatly claiming nothing similar exists.
    """
    if "job_title" not in df.columns or not query:
        return []
    titles = df["job_title"].dropna().unique().tolist()
    if not titles:
        return []
    q_words = {w for w in re.split(r"\W+", query.lower()) if len(w) > 2}
    scored: list[tuple[float, str]] = []
    for t in titles:
        t_words = {w for w in re.split(r"\W+", t.lower()) if len(w) > 2}
        overlap = len(q_words & t_words)
        ratio   = difflib.SequenceMatcher(None, query.lower(), t.lower()).ratio()
        if overlap > 0 or ratio > 0.5:
            scored.append((overlap + ratio, t))
    scored.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    out: list[str] = []
    for _, t in scored:
        key = t.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= n:
            break
    return out


def _to_chroma_where(filters: dict) -> dict | None:
    """Convert filters to a ChromaDB-compatible where clause (exact-match fields only)."""
    exact = {k: {"$eq": v} for k, v in filters.items() if k in _CHROMA_EXACT_FIELDS}
    if not exact:
        return None
    if len(exact) == 1:
        k, v = next(iter(exact.items()))
        return {k: v}
    return {"$and": [{k: v} for k, v in exact.items()]}


_CHITCHAT_RE = re.compile(
    r"^(?:hi|hello|hey|hiya|yo|sup|howdy|good morning|good afternoon|good evening|good night)\b"
    r"|^(?:bye|goodbye|see ya|take care)\b"
    r"|\b(?:thanks|thank you|thx|ty|cheers|appreciate it)\b"
    r"|\bhow'?s?\s+(?:is\s+|are\s+)?(?:\w+\s+)*(?:going|life|things|everything|you|u)\b"
    r"|\bwhat'?s up\b"
    r"|\bw(?:h?a)?(?:s+|z+|dd)up\b"
    r"|\bwhat\s+(?:all\s+)?(?:can|could)\s+(?:you|u)\s+do\b"
    r"|^who\s+are\s+you\b"
    r"|^what\s+are\s+you\b"
    r"|\btell me about yourself\b"
    r"|^(?:ok|okay|cool|nice|great|awesome|perfect|got it|alright|sounds good|no worries|sure|np)[\s!.,]*$",
    re.IGNORECASE,
)

# Data-related keywords — if present, the message is NOT pure chitchat even if
# it also matches _CHITCHAT_RE (e.g. "thanks, what about salaries?").
_CHITCHAT_DATA_RE = re.compile(
    r"\b(job|jobs|salary|salaries|pay|compensation|skill|skills|company|companies|"
    r"sector|industry|country|qatar|uae|saudi|career|posting|postings|"
    r"trend|market|hiring|vacanc|role|roles|position|positions)\b",
    re.IGNORECASE,
)


def _is_chitchat(question: str) -> bool:
    """
    Detect greetings, thanks, farewells, and meta questions ("what can you do",
    "how are you") that need no data retrieval at all — running SQL/Pandas and
    vector search for these wastes time and surfaces irrelevant postings.
    """
    text = str(question or "").strip()
    if not text or len(text) > 60:
        return False
    if not _CHITCHAT_RE.search(text):
        return False
    return not _CHITCHAT_DATA_RE.search(text)


def _is_short_followup(question: str) -> bool:
    """Detect a likely follow-up question that depends on prior context."""
    if not question:
        return False
    text = str(question).strip()
    if len(text) > 120:
        return False
    return bool(re.match(
        r"^(?:just|only|also|and|so|but|then|what about|how about|same|those|that|these|more|now|also show|tell me|what else|what now|how much|how many|what is|what are|what do|which are|which do)\b",
        text,
        flags=re.IGNORECASE,
    ))


def _is_followup_question(question: str) -> bool:
    """Detect follow-up questions that refer to prior entities or topics."""
    if not question:
        return False
    text = str(question).strip().lower()
    if len(text) > 200:
        return False
    return bool(re.search(
        r"\b(these roles|those roles|that role|that company|those companies|that sector|the roles|the companies|my role|my profile|my background|salary|pay|compensation|what about|how about|more about|also|same|then|now)\b",
        text,
        flags=re.IGNORECASE,
    ))


def _merge_followup(question: str, chat_history: list[dict] | None = None) -> str:
    """
    Build a self-contained fallback resolved question when the decomposer fails to
    produce one. Uses the FIRST assistant response as context because that is where
    the topic is typically established (role list, sector, entities) — later assistant
    responses often drift to sub-topics (salary, specific companies) and would cause
    pronouns like 'those roles' to resolve to the wrong thing.
    """
    if not chat_history:
        return question
    prev_user = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), None)
    if not prev_user:
        return question
    # First assistant response = where the topic/entity list was defined
    first_asst = next((msg["content"] for msg in chat_history if msg["role"] == "assistant"), None)
    base = prev_user[:250]
    if first_asst:
        snippet = first_asst[:500].rsplit(" ", 1)[0]
        return f"{base} [topic context: {snippet}] — follow-up: {question}"
    return f"{base} — follow-up: {question}"


def _extract_roles_from_assistant(chat_history: list[dict] | None = None) -> list[str]:
    if not chat_history:
        return []
    for msg in reversed(chat_history):
        if msg.get("role") != "assistant":
            continue
        text = str(msg.get("content", ""))
        match = re.search(
            r"(?:job titles|relevant roles|relevant jobs|roles|positions|job positions)[:\-]\s*(.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        payload = match.group(1).strip()
        payload = re.split(r"\.|\n|$", payload, maxsplit=1)[0]
        parts = re.split(r",\s*|\band\b|\bor\b", payload)
        roles: list[str] = []
        for part in parts:
            role = part.strip(" \t\n\r,.")
            words = [w for w in role.split() if len(w) > 2]
            if len(words) >= 2 and len(words) <= 8:
                roles.append(role)
        if roles:
            return list(dict.fromkeys(roles))
    return []


# Pull a specific job title out of a salary-style question via regex, e.g.
# "what about salary for a software engineer" -> "software engineer".
# Used as a safety net when the LLM decomposer fails to populate
# filters["job_title"] — for some chat histories the small internal model
# answers the question directly in plain English instead of returning JSON,
# which loses the role entirely and falls back to a country-wide average.
_JOB_TITLE_TAIL_RE = re.compile(
    r"(?:salary|pay|compensation|wage|wages|earnings|income)\s+(?:for|of|as)\s+"
    r"(?:an?\s+)?([a-z][a-z0-9/&+\-\s]{2,40}?)"
    r"(?:\s+(?:role|roles|position|positions|job|jobs))?"
    r"\s*[\?\.!]*$",
    re.IGNORECASE,
)
_JOB_TITLE_HEAD_RE = re.compile(
    r"^(?:what about\s+|how about\s+)?(?:an?\s+)?([a-z][a-z0-9/&+\-\s]{2,40}?)"
    r"\s+(?:salary|pay|compensation|wage|wages)\b",
    re.IGNORECASE,
)
_JOB_TITLE_AS_RE = re.compile(
    r"\bas\s+(?:an?\s+)?([a-z][a-z0-9/&+\-\s]{2,40}?)"
    r"(?:[,.]|\s+(?:what|how|i|can|do|does)\b|\s*[\?\.!]*$)",
    re.IGNORECASE,
)

_JOB_TITLE_STOPWORDS = {
    "i", "we", "you", "they", "it", "this", "that", "those", "these",
    "the", "a", "an", "me", "my", "our", "expect", "can",
}


def _extract_job_title_from_question(question: str) -> str | None:
    """Pull a specific job title out of a salary-style question via regex."""
    text = question.strip()
    for pattern in (_JOB_TITLE_TAIL_RE, _JOB_TITLE_HEAD_RE, _JOB_TITLE_AS_RE):
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group(1).strip(" ?.!,")
        words = [w for w in candidate.split() if w]
        if not (1 <= len(words) <= 4):
            continue
        if all(w.lower() in _JOB_TITLE_STOPWORDS for w in words):
            continue
        return candidate
    return None


def _matches_filter_metadata(metadata: dict, filters: dict) -> bool:
    if not filters:
        return True

    for field in ("_country", "_timeline"):
        if field not in filters:
            continue
        expected = str(filters[field]).strip().lower()
        if not expected:
            continue
        actual = str(metadata.get(field, "")).strip().lower()
        if actual != expected:
            return False

    if "career_level" in filters:
        expected = str(filters["career_level"]).strip().lower()
        if expected:
            actual = str(metadata.get("career_level") or metadata.get("_career_norm", "")).strip().lower()
            if actual and actual != expected:
                return False

    return True


def _inherit_country(
    decomposed: dict,
    question: str,
    chat_history: list[dict] | None,
    countries: list[str],
) -> dict:
    """
    Post-process the decomposed result to inherit _country from recent history
    when the current question has no country keyword but a prior user turn did.
    Called OUTSIDE the try/except in _decompose so it cannot be silently swallowed.
    Returns (possibly updated) decomposed dict.
    """
    filters = decomposed.get("filters", {})
    if "_country" in filters or not chat_history:
        return decomposed

    alias_map = _build_country_alias_map(countries)
    q_lower = question.lower()
    # Don't inherit if the current question already names a country
    if any(alias in q_lower for alias in alias_map):
        return decomposed

    for msg in reversed(chat_history[-8:]):
        if msg["role"] != "user":
            continue
        m_lower = str(msg.get("content", "")).lower()
        inherited = next(
            (canonical for alias, canonical in alias_map.items() if alias in m_lower),
            None,
        )
        if inherited:
            decomposed = dict(decomposed)
            decomposed["filters"] = dict(filters)
            decomposed["filters"]["_country"] = inherited
            break

    return decomposed



def _post_filter_semantic_results(results: list[dict], filters: dict) -> list[dict]:
    if not results or not filters:
        return results

    filtered = [r for r in results if _matches_filter_metadata(r.get("metadata", {}), filters)]
    return filtered if filtered else results


# ---------------------------------------------------------------------------
# RAGEngine
# ---------------------------------------------------------------------------

class RAGEngine:
    def __init__(self, analytics: AnalyticsEngine, vector_store: VectorStore):
        self.analytics = analytics
        self.vs = vector_store
        # Internal client for decomposition — always INTERNAL_MODEL regardless of user model choice
        self._internal_client, self._internal_model = make_client(INTERNAL_MODEL)
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
        system = _build_decompose_system(df, timelines, countries)

        messages = [{"role": "system", "content": system}]
        if chat_history:
            for msg in chat_history[-6:]:
                # Keep more of assistant messages so entity lists (companies, roles)
                # are not truncated before the decomposer can resolve pronouns like
                # "those companies" or "the roles you mentioned".
                limit = 1800 if msg["role"] == "assistant" else 900
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"][:limit],
                })
        messages.append({"role": "user", "content": question})

        try:
            resp = self._internal_client.chat.completions.create(
                model=self._internal_model,
                messages=messages,
                temperature=0,
                max_tokens=400,
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)
            result = json.loads(raw)

            # Safety net: resolve country aliases in case LLM used informal names.
            filters = result.get("filters", {})
            if "_country" in filters:
                canonical = _normalize_country(filters["_country"], countries)
                if canonical:
                    filters["_country"] = canonical
            filters = _drop_hallucinated_country(filters, question, countries)
            result["filters"] = filters

            if _is_short_followup(question):
                if not result.get("semantic_query"):
                    result["semantic_query"] = question

            if _is_followup_question(question) and chat_history:
                resolved = result.get("resolved_question") or ""
                if not resolved or re.search(r"\b(those|these|that|they|them|same|it)\b", resolved, flags=re.IGNORECASE):
                    result["resolved_question"] = _merge_followup(question, chat_history)

            # Always ensure resolved_question is non-empty — use _merge_followup
            # as a fallback whenever the LLM failed to produce one. This prevents
            # raw unresolved pronouns ("those roles", "those companies") from being
            # used as-is for vector search.
            if not result.get("resolved_question") and chat_history:
                result["resolved_question"] = _merge_followup(question, chat_history)

            return result
        except Exception:
            # Fallback: try to extract country from question text ourselves
            filters: dict = {}
            q_lower = question.lower()
            alias_map = _build_country_alias_map(countries)
            for alias, canonical in alias_map.items():
                if alias in q_lower:
                    filters["_country"] = canonical
                    break
            resolved = question
            if _is_followup_question(question) and chat_history:
                resolved = _merge_followup(question, chat_history)
            return {
                "filters":          filters,
                "semantic_query":   question,
                "needs_aggregation":True,
                "analysis_types":   [],
                "resolved_question":resolved,
            }

    def _normalize_decomposed(
        self,
        question: str,
        chat_history: list[dict] | None = None,
    ) -> dict:
        # Greetings, thanks, farewells, "what can you do" etc. need no retrieval —
        # skip the decomposer LLM call entirely and short-circuit SQL/Pandas/vector
        # search downstream.
        if _is_chitchat(question):
            return {
                "filters": {},
                "semantic_query": "",
                "needs_aggregation": False,
                "analysis_types": [],
                "resolved_question": question,
                "_chitchat": True,
            }

        decomposed = self._decompose(question, chat_history)
        countries = sorted(self.analytics.df["_country"].dropna().unique().tolist()) \
                    if "_country" in self.analytics.df.columns else []
        decomposed = _inherit_country(decomposed, question, chat_history, countries)

        if _is_followup_question(question) and chat_history:
            resolved = decomposed.get("resolved_question") or ""
            if not resolved or re.search(
                r"\b(those|these|that|they|them|same|it)\b",
                resolved,
                flags=re.IGNORECASE,
            ):
                decomposed["resolved_question"] = _merge_followup(question, chat_history)

            if "job_title" not in decomposed.get("filters", {}) and re.search(
                r"\b(those roles|these roles|that role|those positions|these positions)\b",
                question,
                flags=re.IGNORECASE,
            ):
                roles = _extract_roles_from_assistant(chat_history)
                if roles:
                    decomposed = dict(decomposed)
                    filters = dict(decomposed.get("filters", {}))
                    filters["job_title"] = ", ".join(roles)
                    decomposed["filters"] = filters

        # Safety net: a salary question that explicitly names a role
        # (e.g. "what about salary for a software engineer") should always
        # be scoped to that role, even if the decomposer dropped it.
        if "job_title" not in decomposed.get("filters", {}) and self._SALARY_FORCE.search(question):
            extracted_title = _extract_job_title_from_question(question)
            if extracted_title:
                decomposed = dict(decomposed)
                filters = dict(decomposed.get("filters", {}))
                filters["job_title"] = extracted_title
                decomposed["filters"] = filters

                # The raw question already names the role explicitly, so it
                # makes a cleaner self-contained resolved_question than the
                # generic _merge_followup fallback, which centers on the
                # PREVIOUS question and can bury the role in a long snippet.
                clean = question.strip().rstrip("?.! ")
                country = filters.get("_country")
                if country and country.lower() not in clean.lower():
                    clean = f"{clean} in {country}"
                decomposed["resolved_question"] = clean

        if not decomposed.get("resolved_question") and chat_history:
            decomposed["resolved_question"] = _merge_followup(question, chat_history)

        return decomposed

    def _apply_analysis_forces(
        self,
        question: str,
        resolved_q: str,
        analysis_types: list[str],
        needs_agg: bool,
    ) -> tuple[bool, list[str]]:
        _check_texts = [question, resolved_q]

        if not needs_agg and any(self._AGG_FORCE.search(t) for t in _check_texts):
            needs_agg = True

        if any(self._CAREER_FORCE.search(t) for t in _check_texts):
            needs_agg = True
            for t in ["skills", "sectors", "salary"]:
                if t not in analysis_types:
                    analysis_types.append(t)

        if any(self._CV_FORCE.search(t) for t in _check_texts):
            needs_agg = True
            for t in ["skills", "salary"]:
                if t not in analysis_types:
                    analysis_types.append(t)

        if any(self._SKILL_FORCE.search(t) for t in _check_texts):
            needs_agg = True
            if "skills" not in analysis_types:
                analysis_types.append("skills")

        if any(self._SALARY_FORCE.search(t) for t in _check_texts):
            needs_agg = True
            if "salary" not in analysis_types:
                analysis_types.append("salary")

        if "companies" in analysis_types or any(self._COMPANY_FORCE.search(t) for t in _check_texts):
            needs_agg = True
            if "companies" not in analysis_types:
                analysis_types.append("companies")

        return needs_agg, analysis_types

    # Patterns that always need SQL even if decomposer missed needs_aggregation
    _AGG_FORCE = re.compile(
        r"\b(how many|how much|count|total|number of|average|avg|mean|"
        r"salary|salaries|compensation|pay|remuneration|wage|wages|salary for|compare|top \d+|top companies|top roles|top jobs|"
        r"which sector|what sector|trending|most common|most popular|"
        r"percent|percentage|ratio|distribution|breakdown|ranking|rank|"
        r"highest|lowest|fastest.growing|most.hired|"
        r"كم|عدد)\b",
        re.IGNORECASE,
    )

    # Vague career/field questions — always pull skills + sectors + salary
    _CAREER_FORCE = re.compile(
        r"\b(good field|good career|in[\s-]demand|is .{1,30} good|should i (go into|study|learn|do)|"
        r"future of|opportunities in|worth (it|learning)|career in|job market for|"
        r"jobs? (in|for) .{1,20}|scope of|prospects|what (field|sector|industry|role))\b",
        re.IGNORECASE,
    )

    # Company recommendation questions — always run SQL for grounded Qatar/country company names
    _COMPANY_FORCE = re.compile(
        r"\b(good companies|best companies|which companies|top companies|"
        r"companies (to apply|hiring|that hire|looking for)|"
        r"where (can|should) i apply|who (is|are) hiring|recommend.{0,20}compan)\b",
        re.IGNORECASE,
    )

    # Personal CV / profile questions — always pull skills analytics + vector search
    _CV_FORCE = re.compile(
        r"\b(i (studied|study|have|am a|graduated|majored|speciali[sz]e|work(ed)? (in|as)|know)|"
        r"my (background|degree|experience|skills?|major|profile|resume|cv)|"
        r"(what|which) jobs? (fit|suit|match|for) me|"
        r"relevant (jobs?|roles?|positions?)|"
        r"i (have|got) \d+ years?|with \d+ years? (of )?experience|"
        r"as a (developer|engineer|nurse|doctor|analyst|manager|designer|teacher))\b",
        re.IGNORECASE,
    )

    # Skill / requirement questions — force skills analytics regardless of domain
    _SKILL_FORCE = re.compile(
        r"\b(skill|skills|requirement|qualif|certif|tool|"
        r"programming language|framework|technolog|expertise|competenc|"
        r"what.{0,20}need|need.{0,20}know|what.{0,20}learn|know.{0,20}for)\b",
        re.IGNORECASE,
    )

    _SALARY_FORCE = re.compile(
        r"\b(salary|pay|compensation|wage|earnings|income|expect.*salary|salary.*expect|how much.*salary|what.*salary)\b",
        re.IGNORECASE,
    )

    def _build_full_context(
        self,
        question: str,
        chat_history: list[dict] | None = None,
        dump_ids: list[str] | None = None,
    ) -> str:
        df       = self.analytics.df
        countries = sorted(df["_country"].dropna().unique().tolist()) \
                    if "_country" in df.columns else []

        decomposed     = self._normalize_decomposed(question, chat_history)

        if decomposed.get("_chitchat"):
            return (
                "CONVERSATIONAL MESSAGE — no data retrieval needed. Respond briefly and "
                "naturally, like a normal assistant. If asked what you can do, briefly "
                "mention you can answer questions about the GCC job market: posting "
                "counts, salaries, in-demand skills, top companies/sectors, and trends "
                "across Qatar, UAE, and Saudi Arabia."
            )

        filters        = decomposed.get("filters", {})
        needs_agg      = decomposed.get("needs_aggregation", False)
        analysis_types = decomposed.get("analysis_types", [])
        resolved_q     = decomposed.get("resolved_question") or question
        needs_agg, analysis_types = self._apply_analysis_forces(
            question,
            resolved_q,
            analysis_types,
            needs_agg,
        )
        # Always use resolved_q for vector search — it is self-contained and
        # carries full conversation context (roles, domain, country) so
        # follow-ups like "what about in Saudi?" don't lose the DS/AI topic.
        semantic_q     = resolved_q

        # Restrict the analytics base to the dumps the user has selected in the UI,
        # ensuring chatbot numbers always match the dashboard for the same selection.
        base_df = self.analytics.df
        if dump_ids and "_dump_id" in base_df.columns:
            base_df = base_df[base_df["_dump_id"].isin(dump_ids)]

        # Scope the DATASET SUMMARY to the question's country/timeline so the LLM
        # sees the correct count (e.g. 12,231 Qatar) instead of the global total (25,959).
        summary_df = base_df
        if "_country" in filters and "_country" in summary_df.columns:
            summary_df = summary_df[summary_df["_country"] == filters["_country"]]
        if "_timeline" in filters and "_timeline" in summary_df.columns:
            summary_df = summary_df[summary_df["_timeline"] == filters["_timeline"]]

        summary_engine = AnalyticsEngine(summary_df)
        ov = summary_engine.overview()
        scope_label = filters.get("_country") or "all selected countries"
        parts = [
            f"DATASET SUMMARY: {ov['total_postings']:,} postings in scope ({scope_label}) | "
            f"timelines: {', '.join(str(t) for t in ov['timelines'])}"
        ]
        if filters.get("_country"):
            parts.append(
                f"SCOPE NOTE: Answer only for {filters['_country']}. "
                "Do not include jobs from other countries unless the user explicitly asks."
            )
        if filters.get("_timeline"):
            parts.append(
                f"TIME SCOPE: Only use postings from {filters['_timeline']} in this answer."
            )
        if filters.get("career_level"):
            parts.append(
                f"LEVEL NOTE: Focus on {filters['career_level']} roles only."
            )

        # Job-title grounding check — if the user asked about a specific role and
        # the data has few/no postings with that exact title, surface the closest
        # roles ACTUALLY posted (derived live, never hardcoded). This stops the LLM
        # from either inventing a match or flatly saying "no such role exists" when
        # genuinely-similar roles are sitting right there in the dataset.
        if "job_title" in filters and "job_title" in summary_df.columns:
            jt = str(filters["job_title"])
            if any(len(w) > 2 for w in re.findall(r"[a-z0-9]+", jt.lower())):
                exact_mask = _job_title_mask(summary_df["job_title"], jt)
                n_match = int(exact_mask.sum())
                if n_match < 3:
                    similar = _find_similar_titles(summary_df, jt, n=6)
                    if similar:
                        parts.append(
                            f"JOB TITLE NOTE: Only {n_match} posting(s) closely match \"{jt}\" in this scope. "
                            f"Closest roles ACTUALLY posted in the data: "
                            + ", ".join(f'"{s}"' for s in similar)
                            + ". Present these as the closest available roles — do not claim an exact "
                              f"\"{jt}\" market exists if it doesn't."
                        )
                    else:
                        parts.append(
                            f"JOB TITLE NOTE: No postings matching \"{jt}\" (or similar roles) found in this "
                            "scope. State this plainly rather than inventing roles or statistics."
                        )

        # Step 2 — SQL: aggregation, rankings, trend comparisons
        sql_ran = False
        sql_ctx = ""
        if needs_agg:
            # Build a precise SQL question so the LLM generates the right aggregation.
            # For company questions, explicitly ask for company ranking so SQL engine
            # generates GROUP BY company ORDER BY COUNT(*) instead of SELECT *.
            sql_question = resolved_q
            if "salary" in analysis_types and "job_title" in filters:
                job_titles = filters["job_title"]
                country = filters.get("_country")
                scope = f" in {country}" if country else ""
                sql_question = (
                    f"Return only job_title and salary columns for the following job titles{scope}: {job_titles}. "
                    "Do not aggregate by career level or career grade. "
                    "Do not include full job descriptions or other unrelated columns. "
                    "If no exact job_title salary rows exist, return no matching records."
                )
            elif "companies" in analysis_types and "top companies" not in sql_question.lower():
                sql_question = f"Top companies by number of job postings — {resolved_q}"
            # Append country to the SQL question if not already present —
            # ensures the SQL engine always scopes to the right country
            if "_country" in filters and "salary" not in analysis_types:
                country = filters["_country"]
                if country.lower() not in sql_question.lower():
                    sql_question = f"{sql_question} (country: {country})"
            # Pass dump_ids so SQL operates on the same dump scope as the UI
            sql_ctx = self.sql.get_context(sql_question, dump_ids=dump_ids)
            if sql_ctx and "No matching records" not in sql_ctx:
                if "salary" in analysis_types and "job_title" in filters:
                    numeric_values = re.findall(r"\$?\d{3,}(?:,\d{3})*", sql_ctx)
                    if not numeric_values:
                        sql_ctx = ""
                # If the SQL result is only career-level averages for a job_title salary query,
                # hide it to avoid misleading role-level salary claims.
                if sql_ctx and (
                    "salary" in analysis_types
                    and "job_title" in filters
                    and "_career_norm" in sql_ctx
                    and "job_title" not in sql_ctx
                ):
                    sql_ctx = ""
                if sql_ctx:
                    sql_ran = True

        # Step 3 — Pandas: skills & salary on the FILTERED subset
        # When SQL already ran, skip analytics that SQL handles better
        # (sectors, companies, career_level, trends, education, experience).
        # Only keep skills/salary/language — these need text parsing SQL can't do.
        _SQL_HANDLES = {"companies", "sectors", "trends", "education", "experience", "career_level"}
        effective_types = set(analysis_types)
        if sql_ran:
            effective_types -= _SQL_HANDLES

        if effective_types:
            filtered_df = _apply_filters(base_df, filters)
            sub = AnalyticsEngine(filtered_df)

            if "salary" in effective_types:
                parts.append(
                    "SALARY NOTE: Salary information below is aggregate for the filtered scope. "
                    "Do not invent or assign salaries to individual job titles, career levels, or roles "
                    "unless the dataset explicitly contains those exact role-level salary values. "
                    "If exact role-level salary data is missing, state that only aggregate range/median "
                    "is available for this scope."
                )

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
                if atype in effective_types:
                    parts.append(fn())

        if sql_ctx:
            parts.append("SQL ANALYTICS — AUTHORITATIVE SOURCE (use these numbers for counts/rankings):\n" + sql_ctx)

        # Step 4 — ChromaDB: semantic search within structurally-filtered candidates
        # When SQL already answered a count/ranking, use fewer docs (qualitative context only)
        n_semantic = 4 if sql_ran else _MAX_SEMANTIC_DOCS
        # job_title is a free-text CONTAINS filter that Qdrant can't apply at query
        # time, so pull a larger candidate pool and re-rank locally — otherwise a
        # query like "software engineer salary" can return generic "engineer"
        # postings (mechanical, electrical, sales) that just rank higher by embedding
        # similarity, pushing the actual Software Engineer postings out of the top N.
        fetch_n = max(n_semantic, 25) if "job_title" in filters else n_semantic
        _semantic_companies: set[str] = set()
        if self.vs.has_vectors():
            chroma_where = _to_chroma_where(filters)
            try:
                results = self.vs.search(
                    semantic_q,
                    n_results=fetch_n,
                    where=chroma_where,
                )
            except Exception as _vec_err:
                print(f"[RAG] Vector search with filter failed ({_vec_err}) — retrying without filter")
                # Qdrant filters may fail if the payload field is not indexed.
                # Fall back to an unfiltered semantic search and enforce scope locally.
                results = self.vs.search(semantic_q, n_results=fetch_n)

            if "job_title" in filters:
                other_filters = {k: v for k, v in filters.items() if k != "job_title"}
                title_matches = [
                    r for r in results
                    if _job_title_matches_text(r["metadata"].get("job_title", ""), filters["job_title"])
                ]
                rest = _post_filter_semantic_results(
                    [r for r in results if r not in title_matches], other_filters
                )

                # Vector search may not surface the exact role even from a larger
                # candidate pool (embeddings can rank generic "engineer" postings
                # higher than the actual role asked about). If pandas filtering
                # finds genuine matches for this job_title, splice a few of those
                # rows in directly so the LLM sees real postings for that role.
                want = min(3, n_semantic)
                if len(title_matches) < want and "job_title" in base_df.columns:
                    job_rows = base_df[_job_title_mask(base_df["job_title"], filters["job_title"])]
                    if "_country" in filters and "_country" in job_rows.columns:
                        job_rows = job_rows[
                            job_rows["_country"].astype(str).str.lower() == str(filters["_country"]).lower()
                        ]
                    seen_keys = {
                        (r["metadata"].get("job_title", "").lower().strip(),
                         r["metadata"].get("company", "").lower().strip())
                        for r in title_matches
                    }
                    for _, row in job_rows.iterrows():
                        key = (str(row.get("job_title", "")).lower().strip(),
                               str(row.get("company", "")).lower().strip())
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        title_matches.append({
                            "document": _build_doc_text(row),
                            "metadata": _build_metadata(row),
                            "distance": 0.0,
                        })
                        if len(title_matches) >= want:
                            break

                results = (title_matches + rest)[:n_semantic]
            else:
                results = _post_filter_semantic_results(results, filters)

            if results:
                # Deduplicate: same job posted across multiple timelines → keep highest score only
                seen_jobs: set[tuple] = set()
                deduped: list[dict] = []
                for r in results:
                    key = (
                        r["metadata"].get("job_title", "").lower().strip(),
                        r["metadata"].get("company",   "").lower().strip(),
                    )
                    if key not in seen_jobs:
                        seen_jobs.add(key)
                        deduped.append(r)
                results = deduped

                lines = [f"RELEVANT JOB POSTINGS (top {len(results)} unique roles by semantic similarity):\n"]
                for i, r in enumerate(results, 1):
                    lines.append(f"[Posting {i}]")
                    lines.append(r["document"])
                    lines.append("")
                    company = r["metadata"].get("company", "").strip()
                    if company:
                        _semantic_companies.add(company)
                parts.append("\n".join(lines))

        # Grounding guard for company-recommendation questions — list every employer
        # name that actually appears in the retrieved SQL/semantic results so the LLM
        # cannot cite a company it never saw (previously caused fabricated names like
        # "OilExec International" that don't exist anywhere in the dataset).
        if "companies" in analysis_types:
            grounded = set(_semantic_companies)
            if "company" in summary_df.columns:
                grounded.update(
                    summary_df["company"].dropna().astype(str).str.strip()
                    .value_counts().head(30).index.tolist()
                )
            grounded.discard("")
            if grounded:
                parts.append(
                    "GROUNDED COMPANY NAMES — these are the ONLY employer names that actually "
                    "appear in the retrieved data for this query. When naming specific companies "
                    "in your answer, choose ONLY from this list — never state a company name from "
                    "general knowledge or memory, even if it sounds plausible for this market:\n"
                    + ", ".join(sorted(grounded))
                )

        # If retrieval returned nothing beyond the dataset summary (Qdrant down or
        # very niche query with no matches), tell the LLM explicitly so it doesn't
        # fabricate numbers — it should acknowledge the data gap instead.
        if len(parts) == 1:
            parts.append(
                "DATA NOTE: No specific postings or analytics were retrieved for this query. "
                "Answer qualitatively based on general GCC job market knowledge where appropriate, "
                "but clearly state that exact figures are not available in the dataset."
            )

        return "\n\n".join(filter(None, parts))

    # ── Public API ───────────────────────────────────────────────────────────

    def answer(
        self,
        question: str,
        chat_history: list[dict] | None = None,
        model: str | None = None,
        dump_ids: list[str] | None = None,
    ) -> Generator[str, None, None]:
        """
        Stream the answer token-by-token.
        Compatible with Streamlit's st.write_stream().

        Parameters
        ----------
        model    : override the default CHAT_MODEL for this call (from UI selector)
        dump_ids : restrict to the dumps selected in the sidebar — ensures chatbot
                   numbers match the dashboard for the same selection
        """
        context = self._build_full_context(question, chat_history, dump_ids=dump_ids)

        # Build system prompt from the dump-scoped df so total_postings matches the UI
        df = self.analytics.df
        if dump_ids and "_dump_id" in df.columns:
            df = df[df["_dump_id"].isin(dump_ids)]
        countries = sorted(df["_country"].dropna().unique().tolist()) if "_country" in df.columns else []
        timelines = AnalyticsEngine(df).timelines
        system   = build_system_prompt(
            countries       = countries,
            timelines       = timelines,
            total_postings  = len(df),
            df              = df,
        )

        # Fanar models have a 4,096 token context limit.
        # Arabic is ~2 chars/token vs ~4 for English, so use 2,500 chars as a
        # safe budget (leaves room for system prompt + history + question).
        use_model = model or CHAT_MODEL
        if use_model.startswith("fanar/"):
            truncated = context[:2500]
            context = truncated[:truncated.rfind('\n')] if '\n' in truncated else truncated

        messages: list[dict] = [{"role": "system", "content": system}]

        if chat_history:
            messages.extend(chat_history[-(_MAX_HISTORY_TURNS * 2):])

        decomposed = self._normalize_decomposed(question, chat_history)
        resolved_q = decomposed.get("resolved_question") or question

        messages.append({
            "role": "user",
            "content": (
                f"DATA CONTEXT (use this data to answer accurately):\n"
                f"{context}\n\n"
                "IMPORTANT: Only use salary figures explicitly shown in the data context. "
                "If salary data is aggregate for the filtered scope, do not assign salaries to "
                "individual job titles or roles. Use only the overall range/median and note any "
                "role-level salary limitations.\n\n"
                f"---\n"
                f"USER QUESTION: {question}\n"
                f"RESOLVED QUESTION: {resolved_q}"
            ),
        })

        client, bare_model = make_client(use_model)
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

    # ── Evaluation helpers ───────────────────────────────────────────────────

    def _verify(self, answer_text: str, context: str) -> dict:
        """
        Compare numbers in LLM answer against numbers from SQL/analytics context.
        Only whole integers > 100 — skips decimals (derived %) and small counts.
        Returns: {passed, claimed, expected, mismatches}
        """
        def _extract(text: str) -> set[str]:
            # Whole integers only — decimals are almost always derived percentages/averages
            raw = re.findall(r"\b(\d{1,3}(?:,\d{3})+|\d{3,})\b", text)
            out: set[str] = set()
            for n in raw:
                cleaned = n.replace(",", "")
                try:
                    if int(cleaned) > 100:
                        out.add(cleaned)
                except ValueError:
                    pass
            return out

        ctx_nums    = _extract(context)
        # Strip "You might also want to ask" tail — numbers there are hypothetical, not claims
        answer_body = re.split(r"you might also want to ask", answer_text, flags=re.IGNORECASE)[0]
        answer_nums = _extract(answer_body)

        if not answer_nums or not ctx_nums:
            return {"passed": True, "claimed": answer_nums,
                    "expected": ctx_nums, "mismatches": set()}

        mismatches = answer_nums - ctx_nums
        return {
            "passed":     len(mismatches) == 0,
            "claimed":    answer_nums,
            "expected":   ctx_nums,
            "mismatches": mismatches,
        }

    def answer_eval(
        self,
        question: str,
        chat_history: list[dict] | None = None,
        model: str | None = None,
    ) -> dict:
        """
        Non-streaming evaluation call. Returns answer text + context + verification.
        Builds context once, runs answer(), then calls _verify().
        Used only by evaluate.py and temporary evaluation scripts.
        """
        context     = self._build_full_context(question, chat_history)
        answer_text = "".join(
            chunk for chunk in self.answer(question, chat_history=chat_history, model=model)
        )
        verification = self._verify(answer_text, context)
        return {
            "question":     question,
            "answer":       answer_text,
            "context":      context,
            "sql_context":  "\n".join(
                line for line in context.splitlines()
                if "SQL ANALYTICS" in line or line.strip().startswith("|")
            ),
            "verification": verification,
        }

    def get_retrieval_info(
        self,
        question: str,
        chat_history: list[dict] | None = None,
        dump_ids: list[str] | None = None,
    ) -> dict:
        """
        Return retrieval metadata for the transparency panel (no streaming).
        Shows: decomposition, which layers ran, semantic search scores.
        """
        df       = self.analytics.df
        countries = sorted(df["_country"].dropna().unique().tolist()) \
                    if "_country" in df.columns else []

        decomposed     = self._normalize_decomposed(question, chat_history)

        if decomposed.get("_chitchat"):
            return {
                "decomposed":     decomposed,
                "filters":        {},
                "analysis_types": [],
                "needs_agg":      False,
                "layers_used":    [],
                "sql_snippet":    "",
                "semantic_hits":  [],
            }

        filters        = decomposed.get("filters", {})
        needs_agg      = decomposed.get("needs_aggregation", False)
        analysis_types = decomposed.get("analysis_types", [])
        resolved_q     = decomposed.get("resolved_question") or question
        needs_agg, analysis_types = self._apply_analysis_forces(
            question,
            resolved_q,
            analysis_types,
            needs_agg,
        )
        semantic_q     = resolved_q

        layers_used: list[str] = []

        sql_result = ""
        if needs_agg:
            layers_used.append("SQL / Pandas")
            sql_result = self.sql.get_context(
                decomposed.get("resolved_question") or question,
                dump_ids=dump_ids,
            )

        semantic_hits: list[dict] = []
        if self.vs.has_vectors():
            layers_used.append("Vector Search (semantic)")
            chroma_where = _to_chroma_where(filters)
            try:
                results = self.vs.search(semantic_q, n_results=12, where=chroma_where)
            except Exception:
                # Qdrant filters may fail if the payload field is not indexed.
                # Use the unfiltered search and rely on post-filtering for scope.
                results = self.vs.search(semantic_q, n_results=12)

            results = _post_filter_semantic_results(results, filters)

            # Deduplicate by (title, company) for the UI panel
            seen_jobs: set[tuple] = set()
            for r in results:
                key = (
                    r["metadata"].get("job_title", "").lower().strip(),
                    r["metadata"].get("company",   "").lower().strip(),
                )
                if key in seen_jobs:
                    continue
                seen_jobs.add(key)
                semantic_hits.append({
                    "title":    r["metadata"].get("job_title", "—"),
                    "company":  r["metadata"].get("company", "—"),
                    "sector":   r["metadata"].get("category", "—"),
                    "timeline": r["metadata"].get("_timeline", "—"),
                    "country":  r["metadata"].get("_country", "—"),
                    "score":    round(1 - r["distance"], 3),
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
