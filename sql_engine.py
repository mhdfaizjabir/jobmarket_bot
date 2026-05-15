"""
sql_engine.py
-------------
Text-to-SQL layer: generates a SQLite query for a user question,
runs it against an in-memory copy of the jobs DataFrame, and returns
a formatted result string to include in the LLM context.

Covers: counts, group-bys, filters, top-N, trend comparisons.
Defers to analytics.py for: skill frequency (semicolon splitting) and
salary statistics (regex parsing from text strings).
"""

import os
import re
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from config import CHAT_MODEL

load_dotenv()

_SCHEMA = """\
Table: jobs  (total ~5,424 rows)
  job_title       TEXT    e.g. "Data Analyst", "Civil Engineer", "Nurse"
  company         TEXT    e.g. "Qatar Energy", "Qatar Foundation", "Nakilat"
  category        TEXT    e.g. "Information Technology", "Oil and Gas", "Healthcare"
  location        TEXT    e.g. "Doha", "Al Rayyan", "Lusail"
  salary          TEXT    e.g. "2745-4118 USD/month" or NULL (most rows are NULL)
  employment_type TEXT    e.g. "Full Time", "Part Time", "Contract"
  career_level    TEXT    e.g. "Entry Level", "Mid Career", "Senior", "Management"
  experience      TEXT    e.g. "1-2 Years", "3-5 Years", "5+ Years", "Fresh Graduate"
  education       TEXT    e.g. "Bachelor", "Master", "MBA", "Diploma"
  language        TEXT    e.g. "English", "Arabic" or NULL
  skills          TEXT    semicolon-separated e.g. "Python;SQL;Power BI"
  company_size    TEXT    employee count bracket
  gender          TEXT    "Any", "Male", "Female" or NULL
  _timeline       TEXT    "Nov 2025" (1,880 rows) or "Feb 2026" (3,544 rows)

Notes:
- salary is TEXT, not numeric — cannot SUM or AVG it directly
- skills is semicolon-separated TEXT — use skills LIKE '%Python%' for matching
- For case-insensitive matching: LOWER(col) LIKE LOWER('%val%')
- For timeline comparisons: GROUP BY _timeline or WHERE _timeline = 'Feb 2026'
- Limit to 20 rows unless the question asks for more
- SQLite syntax only — no ILIKE, no ARRAY functions
"""

_SYSTEM = f"""\
You are a SQLite expert. Write a single SELECT query to answer questions about Qatar job market data.

{_SCHEMA}
Return ONLY the raw SQL query — no explanation, no markdown, no code fences.
If the question asks for skill frequency rankings (which require splitting semicolons), return: SKIP
"""


class SQLEngine:
    def __init__(self, df: pd.DataFrame):
        self.conn = sqlite3.connect(":memory:")
        df.to_sql("jobs", self.conn, index=False, if_exists="replace")
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def get_context(self, question: str) -> str:
        """Generate and run SQL for the question; return a formatted result string."""
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
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.upper() == "SKIP":
            return ""
        # Strip any accidental markdown fences
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
