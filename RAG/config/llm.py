"""
config/llm.py
--------------
Model/client configuration and system-prompt construction. Kept separate from
settings.py so LLM provider changes (new model, new provider) never touch
path/CORS/environment config and vice versa.

TODO(sprint5+): build_system_prompt() and its prompt text are logically
"prompt engineering" content — if a prompts/ module is introduced later
(see ARCHITECTURE.md's structure notes), move this function there and keep
only make_client()/model constants here.
"""

import os

from dotenv import load_dotenv

load_dotenv()

_LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))


def make_client(model: str):
    """
    Return (OpenAI client, bare model name) for any model string.
    Fanar models prefixed 'fanar/' → Fanar base URL + Fanar key.
    Everything else → OpenAI.
    Import this in any file that calls the LLM.
    """
    from openai import OpenAI   # local import — avoids circular deps
    if model.startswith("fanar/"):
        bare = model[len("fanar/"):]
        key  = os.getenv("FANAR_API_KEY", "")
        return OpenAI(api_key=key, base_url=FANAR_BASE_URL, timeout=_LLM_TIMEOUT), bare
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""), timeout=_LLM_TIMEOUT), model


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FANAR_API_KEY  = os.getenv("FANAR_API_KEY",  "")
FANAR_BASE_URL = "https://api.fanar.qa/v1"

# Default model — overridden per-session from the UI model selector
CHAT_MODEL = "fanar/Fanar-C-2-27B"

# Internal model used for SQL generation and query decomposition.
INTERNAL_MODEL = "fanar/Fanar-C-2-27B"
# Multilingual model (EN + AR) so Arabic postings embed meaningfully.
# Same 384-dim output as all-MiniLM-L6-v2, so Qdrant vector size is unchanged.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Models shown in the UI selector — Fanar first, OpenAI as fallback
# Prefix "fanar/" = use Fanar client; no prefix = use OpenAI client
AVAILABLE_MODELS: dict[str, str] = {
    # ── Fanar (Qatar-based, Arabic-aware) — default ──────────────────────────
    "Fanar-C-2-27B  (Fanar · most capable)": "fanar/Fanar-C-2-27B",
    "Fanar-C-1-8.7B  (Fanar · balanced)":    "fanar/Fanar-C-1-8.7B",
    "Fanar-S-1-7B  (Fanar · lightweight)":   "fanar/Fanar-S-1-7B",
    "Fanar  (Fanar · multilingual)":          "fanar/Fanar",
    # ── OpenAI — fallback ────────────────────────────────────────────────────
    "GPT-4o  (OpenAI · best quality)":        "gpt-4o",
    "GPT-4o Mini  (OpenAI · faster)":         "gpt-4o-mini",
    "GPT-3.5 Turbo  (OpenAI · fastest)":      "gpt-3.5-turbo",
}


def build_system_prompt(
    countries: list[str],
    timelines: list[str],
    total_postings: int,
    df=None,
) -> str:
    """
    Build the LLM system prompt dynamically from the actual data in the database.
    Called at query time — never hardcodes months, years, countries, or company names.

    If `df` is provided, "Key employers" per country are derived from real
    posting volume (top companies by count) instead of hardcoded lists — this
    stops the LLM from citing names it only saw in its own system prompt as if
    they were grounded facts from the retrieved context (the Aramco/STC bug).
    """
    country_str  = ", ".join(countries) if countries else "GCC region"
    timeline_str = ", ".join(timelines) if timelines else "multiple periods"
    first_tl     = timelines[0]  if timelines else "earliest period"
    last_tl      = timelines[-1] if timelines else "latest period"

    def _top_employers(country: str, n: int = 5) -> str:
        if df is None or "company" not in df.columns or "_country" not in df.columns:
            return ""
        sub = df[df["_country"] == country]
        names = sub["company"].dropna().value_counts().head(n).index.tolist()
        return ", ".join(names)

    # General public-knowledge policy notes per country — informational only,
    # never used as a substitute for data-grounded numbers. Countries without
    # an entry here simply get no policy note (still get real employer data below).
    _POLICY_NOTES: dict[str, list[str]] = {
        "Qatar": [
            "- Qatar: large expat workforce, most postings open to non-Qataris",
            "- Qatarization = policy to increase Qatari nationals in workforce",
            "- Qatar Vision 2030 focuses on Human, Social, Economic & Environmental development",
        ],
        "UAE": [
            "- UAE: regional hub, very diverse workforce from 200+ nationalities",
            "- Emiratization = UAE policy for national workforce inclusion",
        ],
        "Saudi Arabia": [
            "- Saudi Arabia: Vision 2030 driving massive economic diversification",
            "- Saudization / Nitaqat = mandatory quotas for Saudi nationals",
        ],
    }

    # Build a context block for every country actually present in the data.
    # "Employers actively posting" is always derived live from the real postings —
    # never hardcoded — so the LLM can never cite a company name that isn't
    # grounded in the dataset (this is what previously caused fabricated company stats).
    gcc_context = []
    for country in countries:
        gcc_context += _POLICY_NOTES.get(country, [])
        emp = _top_employers(country)
        if emp:
            gcc_context.append(f"- {country} — employers actively posting in this dataset: {emp}")
    gcc_context += [
        "- Most postings don't specify salary — very common on Bayt.com across GCC",
        "- GCC experience is often preferred or required by employers",
        "- Key sectors across GCC: Oil & Gas, Construction, Healthcare, Finance, Technology, Hospitality, Education",
    ]

    return f"""\
You are an intelligent GCC Labor Market Intelligence Assistant powered by real Bayt.com job postings \
covering {country_str}, periods: {timeline_str}.

The DATA CONTEXT injected with every question contains the authoritative numbers for that query's \
exact scope (country, sector, timeline). Always use those numbers — never the total database size.

ANSWER FORMAT RULES:
1. Answer ONLY what the user asked. No padding, no follow-up questions, no "Key Insights" sections,
   no unsolicited summaries or recommendations. If the user asks for job titles, list job titles.
   If the user asks for salary, give salary. Nothing extra.
2. Give real numbers from the context. Bad: "many companies". Good: "47 companies in {last_tl}".
3. SALARY — mention salary ONLY if the user asked about salary or compensation.
   Do not invent role-specific salary amounts when only aggregate salary data is available.
   If exact role-level salary data is missing, say so clearly and provide the aggregate range/median for the scope.
   Do not assign salaries to specific job titles or roles unless the retrieved context contains those exact role-level figures.
   Never mention salary coverage percentages for career-advice or company-recommendation questions.
4. TRENDS — compare periods: "In {first_tl}: X → {last_tl}: Y (+Z%)"
5. CV / CAREER ADVICE — focus on: matching roles → required skills → companies actively hiring.
   Do NOT pad with irrelevant salary or coverage stats.
6. COUNTRY SCOPE — answer strictly for the queried country. Never mix countries unless asked to compare.
   If context contains postings from other countries, IGNORE them for counts and recommendations.
7. LOCATION ACCURACY — never fabricate "City, Country" combos. Use the Country field in each posting.
   WRONG: "role in Riyadh, Qatar". RIGHT: "role in Riyadh (Saudi Arabia)".
8. INSUFFICIENT DATA — say "Only [X] postings found — limited data." rather than guessing.
9. NEVER invent statistics, company names, or percentages not present in the context.
   If a number is not in SQL ANALYTICS or PANDAS context, you cannot state it.
10. TECH/DOMAIN CAREER QUESTIONS:
    Bayt.com has no "AI" sector — AI/ML roles appear under IT/Software or Engineering.
    Evidence to use: skill frequency counts → example job titles → sector volumes → salary (if asked).
    Be direct: "X postings mention Python/ML in Qatar — demand is [strong/moderate/weak]."

GCC CONTEXT:
{chr(10).join(gcc_context)}
"""


# Static fallback used before data is loaded (e.g. sql_engine init)
# Replaced at runtime by build_system_prompt() in rag_engine.py
SYSTEM_PROMPT = build_system_prompt(
    countries=["Qatar", "UAE", "Saudi Arabia", "Bahrain", "Kuwait", "Oman"],
    timelines=["(loaded dynamically from data files)"],
    total_postings=0,
)
