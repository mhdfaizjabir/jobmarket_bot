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

from config import INTERNAL_MODEL, make_client

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

CRITICAL SQL RULES (these prevent runtime errors):
- education: always use LIKE, NEVER exact match — education values vary.
  WRONG: WHERE education = 'Bachelor''s Degree'
  RIGHT: WHERE LOWER(education) LIKE '%bachelor%'
- location: always use LIKE for city names — location stores "City, Country" strings.
  WRONG: WHERE location = 'Riyadh'
  RIGHT: WHERE location LIKE '%Riyadh%'
- rankings/most-common: NEVER use SELECT DISTINCT with ORDER BY COUNT(*).
  WRONG: SELECT DISTINCT company ... ORDER BY COUNT(*) DESC
  RIGHT: SELECT company, COUNT(*) AS cnt FROM jobs GROUP BY company ORDER BY cnt DESC
- NULL filtering: when finding the most common value of a categorical column,
  always add WHERE col IS NOT NULL to exclude missing data.
  WRONG: GROUP BY _employment_norm ORDER BY COUNT(*) DESC LIMIT 1
  RIGHT: WHERE _employment_norm IS NOT NULL GROUP BY _employment_norm ORDER BY COUNT(*) DESC LIMIT 1
- String literals: never use backslash escapes inside SQL strings.
  Use two single-quotes to escape an apostrophe: O''Brien, Bachelor''s
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
        # check_same_thread=False is safe here: all queries are read-only SELECT statements,
        # and SQLite allows concurrent reads from multiple threads without data corruption.
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        df.to_sql("jobs", self.conn, index=False, if_exists="replace")
        self._has_dump_col = "_dump_id" in df.columns
        # Always use INTERNAL_MODEL for SQL generation regardless of user selection
        self._client, self._model = make_client(INTERNAL_MODEL)
        # Build schema once from the actual data — fully dynamic
        self._system = _build_system(df)

    def get_context(self, question: str, dump_ids: list[str] | None = None) -> str:
        """Generate and run SQL; return formatted result string for LLM context."""
        sql = self._to_sql(question)
        if not sql:
            return ""
        try:
            # Rewrite FROM jobs → filtered subquery so SQL scope matches the UI selection
            effective_sql = self._scope_to_dumps(sql, dump_ids)
            result = pd.read_sql_query(effective_sql, self.conn)
            if result.empty or result.isna().all().all():
                return ""
            return self._format(result)
        except Exception:
            return ""

    def _scope_to_dumps(self, sql: str, dump_ids: list[str] | None) -> str:
        """Replace FROM jobs with a dump-filtered subquery when dump_ids are provided."""
        if not dump_ids or not self._has_dump_col:
            return sql
        ids_str = ", ".join(f"'{d}'" for d in dump_ids)
        subquery = f"(SELECT * FROM jobs WHERE _dump_id IN ({ids_str}))"
        return re.sub(r'\bFROM\s+jobs\b', f'FROM {subquery} AS jobs', sql, flags=re.IGNORECASE)

    def _to_sql(self, question: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
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
        if not raw.upper().startswith("SELECT"):
            return ""

        # Post-process: location exact match → LIKE (location stores "City, Country" strings)
        raw = re.sub(
            r"\blocation\s*=\s*'([^']+)'",
            lambda m: f"location LIKE '%{m.group(1)}%'",
            raw,
            flags=re.IGNORECASE,
        )

        # Post-process: remove || '%' string concatenation — return numbers as numbers
        raw = re.sub(r"\s*\|\|\s*'%'", "", raw)

        # Hard cap: if the LLM forgot to add LIMIT, inject one so we never
        # dump thousands of rows into the LLM context.
        if "LIMIT" not in raw.upper():
            raw = raw.rstrip(";") + " LIMIT 200"
        return raw

    @staticmethod
    def _format(df: pd.DataFrame) -> str:
        if df.empty:
            return "SQL ANALYTICS: No matching records."
        n = len(df)
        return f"SQL ANALYTICS ({n} row{'s' if n != 1 else ''}):\n{df.to_string(index=False, max_rows=25)}"
