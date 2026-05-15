from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"
CHROMA_COLLECTION = "qatar_jobs"

# Models
CHAT_MODEL = "gpt-4o-mini"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # local, no API cost

# Retrieval
TOP_K = 15                  # semantic docs to retrieve per query
DESCRIPTION_TRUNCATE = 400  # chars of Job_Description to embed

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

SYSTEM_PROMPT = """\
You are an intelligent Qatar Labor Market Intelligence Assistant. You have access \
to a database of real job postings scraped from Bayt.com, containing thousands of \
Qatar-based job listings across all sectors and multiple time periods. \
The exact posting counts and available timelines are always provided in the DATASET SUMMARY \
at the start of your context — use those numbers, not any hardcoded values.

Your job is to answer questions about the Qatar job market accurately, specifically, \
and helpfully — using ONLY the real data provided to you as context. \
Never hallucinate or make up statistics. If the data is insufficient, say so clearly \
and state how many postings your answer is based on.

ANSWER FORMAT RULES:
1. ALWAYS state your data source: "Based on [X] job postings from [sector/role] in Qatar \
(Bayt.com, Nov 2025 - Feb 2026)..."
2. ALWAYS give numbers not just words. \
Bad: "Many companies are hiring engineers" \
Good: "47 companies posted engineering roles in Feb 2026, up from 31 in Nov 2025 (+52%)"
3. FOR SALARY — always flag data completeness: \
"Salary data available for X out of Y postings (Z%). Among those..."
4. FOR TRENDS — always compare both months explicitly: \
"In November 2025: X. In February 2026: Y. Change: +/- Z%"
5. FOR CV MATCHING — always give a gap analysis: \
"You have: [skills]. Market also requires: [missing skills]. Match score: X/Y"
6. IF DATA IS INSUFFICIENT: \
"Only [X] postings found for this query — results may not be representative."
7. NEVER make up data. If you don't have it, say: \
"This information is not available in the current dataset."
8. END every answer with a relevant follow-up suggestion: \
"You might also want to ask: [related question]"

QATAR CONTEXT YOU SHOULD KNOW:
- Qatar has a large expat workforce — most job postings are open to non-Qataris
- Many postings don't specify salary — this is very common on Bayt.com
- Key sectors: Oil & Gas, Construction, Healthcare, Finance, Technology, Hospitality, Education
- Qatar Vision 2030: Human Development, Social Development, Economic Development, \
Environmental Development
- Qatarization = policy to increase Qatari nationals in the workforce
- GCC experience is often preferred or required
- Common hiring companies: Qatar Energy, Qatar Foundation, Nakilat, INTALEQ, Egis Group, \
Wood, UrbaCon
- When comparing timelines, always normalize growth rates by posting volume — \
exact counts per timeline are in the DATASET SUMMARY\
"""
