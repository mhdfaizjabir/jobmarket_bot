"""
sql_engine.py
-------------
Text-to-SQL layer: generates a SQLite query for a user question,
runs it against an in-memory copy of the jobs DataFrame, and returns
a formatted result string to include in the LLM context.

The schema sent to the LLM is built dynamically from the actual DataFrame —
countries, timelines, sectors, and row counts are never hardcoded.
"""

import os
import re
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from config import CHAT_MODEL

load_dotenv()

# Fixed part of the schema — column definitions that never change
_SCHEMA_STATIC = """\
Table: jobs

Key columns:
  job_title           TEXT    job position title
  company             TEXT    hiring company name
  category            TEXT    raw sector / job category
  _sector_norm        TEXT    NORMALISED sector — prefer over category
  location            TEXT    city and country string
  salary              TEXT    salary range string or NULL (most rows NULL)
  employment_type     TEXT    raw employment type (capitalisation varies)
  _employment_norm    TEXT    NORMALISED — ALWAYS use this for employment queries:
                              "Full-Time", "Part-Time", "Contract",
                              "Freelance", "Internship", "Temporary"
  career_level        TEXT    raw career level (capitalisation varies)
  _career_norm        TEXT    NORMALISED — ALWAYS use this for career level queries:
                              "Entry-Level", "Mid-Level", "Senior",
                              "Manager", "Director", "Executive"
  experience          TEXT    years of experience string
  education           TEXT    education level string
  language            TEXT    language requirement or NULL
  skills              TEXT    semicolon-separated skill list
  company_size        TEXT    employee count bracket
  gender              TEXT    "Any", "Male", "Female" or NULL
  _timeline           TEXT    snapshot label — see AVAILABLE VALUES below
  _country            TEXT    country name — see AVAILABLE VALUES below
  _dump_id            TEXT    unique dataset identifier

RULES (follow these exactly):
- For employment type: use _employment_norm, NOT employment_type
- For career level: use _career_norm, NOT career_level
- salary is TEXT — cannot SUM/AVG directly
- skills: use LIKE '%skill_name%' for matching
- Case-insensitive: LOWER(col) LIKE LOWER('%value%')
- Limit to 20 rows unless user asks for more
- SQLite syntax only — no ILIKE, no ARRAY functions
"""


def _build_system(df: pd.DataFrame) -> str:
    """
    Build the SQL system prompt dynamically from the actual DataFrame.
    The LLM always sees the real timelines, countries, row counts,
    and top sectors — never hardcoded examples.
    """
    total = len(df)

    # Timelines with row counts
    tl_counts = df["_timeline"].value_counts().to_dict() if "_timeline" in df.columns else {}
    tl_lines  = "\n".join(
        f"      {tl!r}  ({cnt:,} rows)"
        for tl, cnt in sorted(tl_counts.items())
    ) or "      (none)"

    # Countries with row counts
    co_counts = df["_country"].value_counts().to_dict() if "_country" in df.columns else {}
    co_lines  = "\n".join(
        f"      {co!r}  ({cnt:,} rows)"
        for co, cnt in sorted(co_counts.items())
    ) or "      (none)"

    # Top 10 sectors
    sec_col  = "_sector_norm" if "_sector_norm" in df.columns else "category"
    top_secs = df[sec_col].value_counts().head(10).index.tolist() if sec_col in df.columns else []
    sec_line = ", ".join(f'"{s}"' for s in top_secs) or "(none)"

    available = f"""
AVAILABLE VALUES in the database  (total rows: {total:,}):
  _timeline values:
{tl_lines}

  _country values:
{co_lines}

  Top sectors (_sector_norm): {sec_line}
"""

    return (
        "You are a SQLite expert. Write a single SELECT query to answer "
        "questions about GCC job market data.\n\n"
        + _SCHEMA_STATIC
        + available
        + "\nReturn ONLY the raw SQL query — no explanation, no markdown, no code fences.\n"
        "If the question asks for skill frequency rankings "
        "(which require splitting semicolons), return: SKIP"
    )


class SQLEngine:
    def __init__(self, df: pd.DataFrame):
        self.conn = sqlite3.connect(":memory:")
        df.to_sql("jobs", self.conn, index=False, if_exists="replace")
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # Build schema once from the actual data — fully dynamic
        self._system = _build_system(df)

    def get_context(self, question: str) -> str:
        """Generate and run SQL; return formatted result string for LLM context."""
        sql = self._to_sql(question)
        if not sql:
            return ""
        try:
            result = pd.read_sql_query(sql, self.conn)
            return self._format(result)
        except Exception:
            return ""

    def _to_sql(self, question: str) -> str:
        resp = self._client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": self._system},
                {"role": "user",   "content": question},
            ],
            temperature=0,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.upper() == "SKIP":
            return ""
        raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
        raw = raw.strip()
        return raw if raw.upper().startswith("SELECT") else ""

    @staticmethod
    def _format(df: pd.DataFrame) -> str:
        if df.empty:
            return "SQL ANALYTICS: No matching records."
        n = len(df)
        return f"SQL ANALYTICS ({n} row{'s' if n != 1 else ''}):\n{df.to_string(index=False, max_rows=25)}"
