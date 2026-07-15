"""
config/settings.py
-------------------
Environment-driven settings: paths, environment name, CORS, retrieval tuning,
and static UI/data-loading constants. No LLM/model config here (see llm.py).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# One of: "development" (default), "production". Drives things like whether
# stack traces are ever allowed to leak (they never are) and log verbosity.
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION: bool = ENVIRONMENT == "production"

# Bumped manually on release; surfaced on /health. Falls back to "dev" so a
# missing env var never breaks startup.
APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0-dev")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"
CHROMA_COLLECTION = "gulf_jobs"

# ---------------------------------------------------------------------------
# CORS — comma-separated origins, e.g. "https://app.example.com,https://example.com"
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

# ---------------------------------------------------------------------------
# Retrieval tuning
# ---------------------------------------------------------------------------
TOP_K = 15
DESCRIPTION_TRUNCATE = 400

# ---------------------------------------------------------------------------
# UI-facing constants (used by the legacy Streamlit app in app.py)
# ---------------------------------------------------------------------------
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
