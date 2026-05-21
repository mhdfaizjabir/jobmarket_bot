import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"
CHROMA_COLLECTION = "gulf_jobs"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FANAR_API_KEY  = os.getenv("FANAR_API_KEY",  "")
FANAR_BASE_URL = "https://api.fanar.qa/v1"

# Default model — overridden per-session from the UI model selector
CHAT_MODEL = "fanar/Fanar-C-2-27B"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Retrieval
TOP_K = 15
DESCRIPTION_TRUNCATE = 400

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

COUNTRY_FLAGS: dict[str, str] = {
    "Qatar":        "🇶🇦",
    "UAE":          "🇦🇪",
    "Saudi Arabia": "🇸🇦",
    "KSA":          "🇸🇦",
    "Bahrain":      "🇧🇭",
    "Kuwait":       "🇰🇼",
    "Oman":         "🇴🇲",
}

COUNTRY_COLORS: dict[str, str] = {
    "Qatar":        "#8B1538",
    "UAE":          "#00732F",
    "Saudi Arabia": "#FFB300",
    "KSA":          "#FFB300",
    "Bahrain":      "#CE1126",
    "Kuwait":       "#007A3D",
    "Oman":         "#DB161B",
}

# ---------------------------------------------------------------------------
# Column aliases — maps canonical names → possible Excel/CSV header variants.
# Add new aliases here if columns are renamed in future datasets.
# Matching is case-insensitive; first match wins.
# ---------------------------------------------------------------------------
COLUMN_ALIASES: dict[str, list[str]] = {
    "job_id":          ["Job_ID", "ID", "JobID", "job_id"],
    "job_title":       ["Job_Title", "Title", "Position", "Job Title", "job_title"],
    "company":         ["Company_Name", "Company", "Employer", "company_name"],
    "category":        ["Job_Category", "Category", "Sector", "Industry", "job_category"],
    "location":        ["Job_Location", "Location", "City", "job_location"],
    "salary":          ["Salary_Range_USD", "Salary", "Salary Range", "Compensation",
                        "salary_range_usd", "Salary_Range"],
    "employment_type": ["Employment_Type", "Job Type", "Contract Type", "employment_type"],
    "career_level":    ["Career_Level", "Level", "Seniority", "career_level"],
    "experience":      ["Years_of_Experience", "Experience", "Years Experience",
                        "years_of_experience", "Exp"],
    "company_size":    ["Company_Size", "Size", "company_size"],
    "description":     ["Job_Description", "Description", "Job Details", "job_description"],
    "skills":          ["Job_Skills", "Skills", "Required Skills", "job_skills"],
    "qualifications":  ["Required_Qualifications", "Qualifications", "Requirements",
                        "required_qualifications"],
    "gender":          ["Gender", "gender"],
    "post_date":       ["Post_Date", "Date Posted", "Posted Date", "post_date"],
    "education":       ["Education_Level", "Education", "Degree", "education_level"],
    "language":        ["Language_Requirement", "Language", "Languages", "language_requirement"],
    "url":             ["URL", "Link", "Job URL", "url"],
    "original_content": ["Original_Page_Content", "Page Content", "Raw Content"],
}

def build_system_prompt(
    countries: list[str],
    timelines: list[str],
    total_postings: int,
) -> str:
    """
    Build the LLM system prompt dynamically from the actual data in the database.
    Called at query time — never hardcodes months, years, or countries.
    """
    country_str  = ", ".join(countries) if countries else "GCC region"
    timeline_str = ", ".join(timelines) if timelines else "multiple periods"
    first_tl     = timelines[0]  if timelines else "earliest period"
    last_tl      = timelines[-1] if timelines else "latest period"

    # Build GCC-specific context block only for countries present in the data
    gcc_context = []
    if "Qatar" in countries:
        gcc_context += [
            "- Qatar: large expat workforce, most postings open to non-Qataris",
            "- Qatarization = policy to increase Qatari nationals in workforce",
            "- Qatar Vision 2030 focuses on Human, Social, Economic & Environmental development",
            "- Key employers: Qatar Energy, Qatar Foundation, Nakilat, INTALEQ, UrbaCon",
        ]
    if "UAE" in countries:
        gcc_context += [
            "- UAE: regional hub, very diverse workforce from 200+ nationalities",
            "- Emiratization = UAE policy for national workforce inclusion",
            "- Key employers: ADNOC, Emirates, DP World, ALDAR, ENOC",
        ]
    if "Saudi Arabia" in countries:
        gcc_context += [
            "- Saudi Arabia: Vision 2030 driving massive economic diversification",
            "- Saudization / Nitaqat = mandatory quotas for Saudi nationals",
            "- Key employers: Aramco, STC, SABIC, Qiddiya, NEOM, Red Sea Global",
        ]
    gcc_context += [
        "- Most postings don't specify salary — very common on Bayt.com across GCC",
        "- GCC experience is often preferred or required by employers",
        "- Key sectors across GCC: Oil & Gas, Construction, Healthcare, Finance, Technology, Hospitality, Education",
    ]

    return f"""\
You are an intelligent GCC Labor Market Intelligence Assistant. \
You have access to a database of {total_postings:,} real job postings scraped from Bayt.com, \
covering {country_str} across {len(timelines)} time period(s): {timeline_str}. \
The DATASET SUMMARY in your context always has the exact counts — use those, never guess.

Your job is to answer questions about the GCC job market accurately and helpfully \
using ONLY the real data provided. Never hallucinate statistics.

ANSWER FORMAT RULES:
1. State your data source: "Based on [X] postings from [country/sector] (Bayt.com, {timeline_str})..."
2. Always give numbers. Bad: "many companies hiring engineers". \
Good: "47 companies posted engineering roles in {last_tl}, up from 31 in {first_tl} (+52%)"
3. SALARY — always flag coverage: "Salary data: X of Y postings (Z%). Among those..."
4. TRENDS — compare periods explicitly: "In {first_tl}: X. In {last_tl}: Y. Change: +/- Z%"
5. CV MATCHING — give gap analysis: "You have: [skills]. Market also needs: [missing]. Match: X/Y"
6. COUNTRY SCOPE — when question mentions a specific country, answer for THAT country only.
   Do not mix Qatar and Saudi Arabia statistics unless explicitly asked to compare.
7. LOCATION ACCURACY — NEVER append a country name to a city unless it is explicitly in
   the job posting data. Each posting has a "Country:" field — use that.
   WRONG: "AI Engineer role in Riyadh, Qatar"  ← Riyadh is in Saudi Arabia
   RIGHT: "AI Engineer role in Riyadh (Saudi Arabia)"
   If location is unclear, write the city only, not "City, Country" unless confirmed.
8. INSUFFICIENT DATA — "Only [X] postings found — may not be representative."
9. NEVER invent data. If unavailable: "Not in the current dataset."
10. END with: "You might also want to ask: [follow-up question]"

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
