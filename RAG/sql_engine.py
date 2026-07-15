"""
sql_engine.py
-------------
Text-to-SQL layer: generates a SQLite query for a user question,
runs it against an in-memory copy of the jobs DataFrame, and returns
a formatted result string to include in the LLM context.

The schema sent to the LLM is built dynamically from the actual DataFrame —
countries, timelines, sectors, and row counts are never hardcoded.
"""

import re
import sqlite3
import time

import pandas as pd
from dotenv import load_dotenv

from config import INTERNAL_MODEL, get_logger, make_client
from observability import record_metric

load_dotenv()

logger = get_logger(__name__)

# Keywords that can legally follow "FROM jobs" with no alias — _scope_query's
# alias-capture must not mistake these for a table alias (e.g. "FROM jobs
# WHERE ..." must not read "WHERE" as an alias).
_SQL_RESERVED_AFTER_FROM = {
    "WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "JOIN", "INNER", "LEFT",
    "RIGHT", "OUTER", "CROSS", "UNION", "INTERSECT", "EXCEPT",
}

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
        self._columns      = set(df.columns)
        # Always use INTERNAL_MODEL for SQL generation regardless of user selection
        self._client, self._model = make_client(INTERNAL_MODEL)
        # Build schema once from the actual data — fully dynamic
        self._system = _build_system(df)

    def get_context(
        self,
        question: str,
        dump_ids: list[str] | None = None,
        explicit_filters: dict[str, str] | None = None,
    ) -> str:
        """Generate and run SQL; return formatted result string for LLM context."""
        t0 = time.perf_counter()
        sql = self._to_sql(question)
        record_metric("sql_generation_duration_ms", (time.perf_counter() - t0) * 1000)
        if not sql:
            return ""
        # Rewrite FROM jobs → filtered subquery so SQL scope matches the UI selection.
        # Bound before the try so the except below always has it for logging,
        # even if _scope_query itself is what raises.
        effective_sql = sql
        try:
            effective_sql = self._scope_query(sql, dump_ids, explicit_filters)
            t1 = time.perf_counter()
            result = pd.read_sql_query(effective_sql, self.conn)
            record_metric("sql_execution_duration_ms", (time.perf_counter() - t1) * 1000)
            if result.empty or result.isna().all().all():
                return ""
            return self._format(result)
        except Exception:
            # Was a fully silent no-op before — the SQL layer would drop the
            # answer with zero trace. Now at least visible in logs (never to
            # the client — this is a fallback path, not an error response).
            logger.warning("SQL execution failed, falling back to no SQL context. sql=%r", effective_sql, exc_info=True)
            return ""

    def _scope_query(
        self,
        sql: str,
        dump_ids: list[str] | None,
        explicit_filters: dict[str, str] | None = None,
    ) -> str:
        """
        Replace FROM jobs with a filtered subquery for active UI selections —
        dump_ids plus any registered explicit filter (column -> value), already
        resolved to real internal column names by the caller. Column names are
        checked against this table's own columns, not hardcoded per filter, so
        a new registry entry needs no change here.
        """
        def _q(value) -> str:
            # Single-quote-escape any value interpolated into SQL. The API layer
            # already constrains these to an identifier charset, but eval/offline
            # callers bypass that — so escape here too rather than trust callers.
            return "'" + str(value).replace("'", "''") + "'"

        conditions: list[str] = []
        if dump_ids and self._has_dump_col:
            ids_str = ", ".join(_q(d) for d in dump_ids)
            conditions.append(f"_dump_id IN ({ids_str})")
        for column, value in (explicit_filters or {}).items():
            if not value or column not in self._columns:
                continue
            conditions.append(f"{column} = {_q(value)}")
        if not conditions:
            return sql
        subquery = f"(SELECT * FROM jobs WHERE {' AND '.join(conditions)})"

        # If the LLM aliased the table (e.g. "FROM jobs j"), blindly inserting
        # "AS jobs" produces invalid SQL ("...AS jobs j") that silently fails
        # get_context's try/except and drops the SQL-backed answer entirely.
        # Reuse whatever alias was given instead of assuming there is none.
        def _replace(m: re.Match) -> str:
            token = m.group(1)
            if token and token.upper() not in _SQL_RESERVED_AFTER_FROM:
                return f'FROM {subquery} AS {token}'
            # No real alias — `token`, if present, is actually the next SQL
            # keyword (WHERE/GROUP/...) the pattern greedily captured; it must
            # be re-emitted, not consumed.
            tail = f' {token}' if token else ''
            return f'FROM {subquery} AS jobs{tail}'

        return re.sub(
            r'\bFROM\s+jobs\b(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?',
            _replace, sql, count=1, flags=re.IGNORECASE,
        )

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

        # Defense in depth: keep only the first statement. Even though this SQL
        # runs read-only against an ephemeral in-memory copy, dropping anything
        # after the first ';' prevents stacked-statement injection outright.
        raw = raw.split(";")[0].strip()
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
