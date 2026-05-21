"""
analytics.py
------------
Pure-pandas statistics engine for the Qatar job market dataset.
All methods work off whatever canonical columns are present in the DataFrame —
missing columns degrade gracefully rather than raising exceptions.

Usage
-----
    from analytics import AnalyticsEngine
    engine = AnalyticsEngine(df)
    print(engine.sector_stats())
    print(engine.build_context("What skills are trending in Tech?"))
"""

import re
from collections import Counter

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pct(count: int | float, total: int | float) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns


def _parse_skills(val) -> list[str]:
    """Split a semicolon/comma/pipe/newline-delimited skills string."""
    if not val or (isinstance(val, float) and np.isnan(val)):
        return []
    tokens = re.split(r"[;,|\n/]+", str(val))
    return [t.strip() for t in tokens if t.strip() and len(t.strip()) > 2]


def _parse_salary_monthly(val) -> tuple[float, float] | None:
    """
    Parse salary strings like:
      '2745-4118 USD/month'
      '102000-138000 USD/year'
    Returns (min_monthly_usd, max_monthly_usd) or None.
    """
    if not val or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val)
    nums = re.findall(r"[\d,]+", s)
    if len(nums) < 2:
        return None
    try:
        lo = float(nums[0].replace(",", ""))
        hi = float(nums[1].replace(",", ""))
    except ValueError:
        return None
    if "year" in s.lower():
        lo, hi = lo / 12, hi / 12
    return (lo, hi)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

_MONTH_ORDER = {
    m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}


def _sort_timelines_chrono(timelines: list[str]) -> list[str]:
    def _key(tl: str):
        parts = tl.split()
        try:
            month = _MONTH_ORDER.get(parts[0], 99)
            year = int(parts[1]) if len(parts) > 1 else 0
            return (year, month)
        except Exception:
            return (9999, 99)
    return sorted(timelines, key=_key)


class AnalyticsEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        raw_timelines = (
            df["_timeline"].dropna().unique().tolist()
            if "_timeline" in df.columns else []
        )
        self.timelines: list[str] = _sort_timelines_chrono(raw_timelines)
        self._sal_df: pd.DataFrame | None = None  # lazy

    # ── private utilities ────────────────────────────────────────────────────

    def _sub(self, timeline: str | None = None) -> pd.DataFrame:
        if timeline and "_timeline" in self.df.columns:
            return self.df[self.df["_timeline"] == timeline]
        return self.df

    def _salary_frame(self) -> pd.DataFrame:
        """Build a salary-augmented DataFrame (cached)."""
        if self._sal_df is not None:
            return self._sal_df
        if not _has(self.df, "salary"):
            self._sal_df = pd.DataFrame()
            return self._sal_df
        rows = []
        for _, row in self.df.iterrows():
            parsed = _parse_salary_monthly(row.get("salary"))
            if parsed:
                d = row.to_dict()
                d["_sal_min"], d["_sal_max"] = parsed
                d["_sal_mid"] = (parsed[0] + parsed[1]) / 2
                rows.append(d)
        self._sal_df = pd.DataFrame(rows) if rows else pd.DataFrame()
        return self._sal_df

    def _skill_counter(self, sub: pd.DataFrame) -> Counter:
        c: Counter = Counter()
        if _has(sub, "skills"):
            for v in sub["skills"].dropna():
                c.update(_parse_skills(v))
        return c

    # ── public stats methods ─────────────────────────────────────────────────

    def overview(self) -> dict:
        total = len(self.df)
        per_tl = (
            self.df["_timeline"].value_counts().to_dict()
            if "_timeline" in self.df.columns else {}
        )
        per_country = (
            self.df["_country"].value_counts().to_dict()
            if "_country" in self.df.columns else {}
        )
        # Use normalised sector column if available
        sec_col = "_sector_norm" if _has(self.df, "_sector_norm") else "category"
        top_sectors = (
            self.df[sec_col].value_counts().head(10).to_dict()
            if _has(self.df, sec_col) else {}
        )
        sal_df = self._salary_frame()
        return {
            "total_postings":  total,
            "per_timeline":    per_tl,
            "per_country":     per_country,
            "timelines":       self.timelines,
            "top_sectors":     top_sectors,
            "salary_n":        len(sal_df),
            "salary_coverage": f"{len(sal_df)}/{total} ({_pct(len(sal_df), total)}%)",
        }

    def sector_stats(self) -> str:
        if not _has(self.df, "category"):
            return "Sector data not available in this dataset."

        lines = [f"SECTOR ANALYSIS  ({len(self.df):,} total postings)\n"]

        by_tl: dict[str, pd.Series] = {}
        for tl in self.timelines:
            sub = self._sub(tl)
            counts = sub["category"].value_counts().head(15)
            by_tl[tl] = counts
            lines.append(f"  {tl}  ({len(sub):,} postings):")
            for sector, n in counts.items():
                lines.append(f"    {sector}: {n}  ({_pct(n, len(sub))}%)")
            lines.append("")

        if len(self.timelines) == 2:
            tl1, tl2 = self.timelines[0], self.timelines[1]
            n1, n2 = len(self._sub(tl1)), len(self._sub(tl2))
            lines.append(f"  GROWTH  ({tl1} → {tl2}, share-normalised):")
            all_sectors = set(by_tl[tl1].index) | set(by_tl[tl2].index)
            growths = []
            for s in all_sectors:
                r1 = by_tl[tl1].get(s, 0) / n1
                r2 = by_tl[tl2].get(s, 0) / n2
                if r1 > 0:
                    growths.append((s, int(by_tl[tl1].get(s, 0)),
                                    int(by_tl[tl2].get(s, 0)),
                                    round((r2 - r1) / r1 * 100, 1)))
            for s, c1, c2, g in sorted(growths, key=lambda x: -x[3])[:12]:
                arrow = "↑" if g >= 0 else "↓"
                lines.append(f"    {s}: {c1} → {c2}  ({arrow}{abs(g)}%)")

        return "\n".join(lines)

    def skill_stats(
        self,
        filter_col: str | None = None,
        filter_val: str | None = None,
        n: int = 25,
    ) -> str:
        if not _has(self.df, "skills"):
            return "Skills data not available in this dataset."

        sub = self.df
        if filter_col and filter_val and _has(sub, filter_col):
            sub = sub[sub[filter_col].str.contains(filter_val, case=False, na=False)]

        lines = [f"SKILL ANALYSIS  ({len(sub):,} postings analysed)\n"]

        for tl in self.timelines:
            tl_sub = sub[sub["_timeline"] == tl] if "_timeline" in sub.columns else sub
            counter = self._skill_counter(tl_sub)
            total = len(tl_sub)
            lines.append(f"  Top skills in {tl}  ({total:,} postings):")
            for skill, cnt in counter.most_common(n):
                lines.append(f"    {skill}: {cnt}  ({_pct(cnt, total)}%)")
            lines.append("")

        if len(self.timelines) == 2:
            tl1, tl2 = self.timelines[0], self.timelines[1]
            s1 = sub[sub["_timeline"] == tl1] if "_timeline" in sub.columns else sub
            s2 = sub[sub["_timeline"] == tl2] if "_timeline" in sub.columns else sub
            c1, c2 = self._skill_counter(s1), self._skill_counter(s2)
            n1, n2 = max(len(s1), 1), max(len(s2), 1)

            growths = []
            for sk in set(c1.keys()) | set(c2.keys()):
                r1 = c1.get(sk, 0) / n1
                r2 = c2.get(sk, 0) / n2
                if r1 >= 0.01:  # only meaningful skills (≥1% baseline)
                    growths.append((sk, round((r2 - r1) / r1 * 100, 1)))

            lines.append(f"  FASTEST GROWING skills  ({tl1} → {tl2}):")
            for sk, g in sorted(growths, key=lambda x: -x[1])[:10]:
                lines.append(f"    {sk}: {'+' if g >= 0 else ''}{g}%")

        return "\n".join(lines)

    def salary_stats(
        self,
        filter_col: str | None = None,
        filter_val: str | None = None,
    ) -> str:
        sal_df     = self._salary_frame()
        total_base = len(self.df)

        # Show which job titles are in this subset (useful when filtered by role)
        title_note = ""
        if _has(self.df, "job_title") and total_base < 500:
            titles = self.df["job_title"].dropna().value_counts().head(8).to_dict()
            if titles:
                title_note = f"\n  Job titles in this subset: {', '.join(f'{t} ({n})' for t, n in titles.items())}"

        if filter_col and filter_val:
            filtered_base = self.df
            if _has(filtered_base, filter_col):
                filtered_base = filtered_base[
                    filtered_base[filter_col].str.contains(filter_val, case=False, na=False)
                ]
            total_base = len(filtered_base)
            if not sal_df.empty and _has(sal_df, filter_col):
                sal_df = sal_df[
                    sal_df[filter_col].str.contains(filter_val, case=False, na=False)
                ]

        n = len(sal_df)
        if n == 0:
            return (
                f"No salary data available for this filter "
                f"(out of {total_base:,} matching postings).{title_note} "
                "This is common on Bayt.com where most listings omit salary."
            )

        lines = [
            f"SALARY ANALYSIS  (data available for {n}/{total_base:,} postings, "
            f"{_pct(n, total_base)}%){title_note}\n",
            f"  Min:    ${sal_df['_sal_min'].min():>10,.0f} /month",
            f"  Max:    ${sal_df['_sal_max'].max():>10,.0f} /month",
            f"  Avg:    ${sal_df['_sal_mid'].mean():>10,.0f} /month (midpoint)",
            f"  Median: ${sal_df['_sal_mid'].median():>10,.0f} /month (midpoint)",
        ]

        if self.timelines and "_timeline" in sal_df.columns:
            lines.append("\n  By timeline:")
            for tl in self.timelines:
                ts = sal_df[sal_df["_timeline"] == tl]
                if len(ts):
                    lines.append(
                        f"    {tl}: avg ${ts['_sal_mid'].mean():,.0f}/month  (n={len(ts)})"
                    )

        if _has(sal_df, "category") and len(sal_df) >= 5:
            lines.append("\n  Top-paying sectors  (avg monthly USD, min 3 postings):")
            by_sec = (
                sal_df.groupby("category")["_sal_mid"]
                .agg(["mean", "count"])
                .query("count >= 3")
                .sort_values("mean", ascending=False)
            )
            for sector, row in by_sec.head(10).iterrows():
                lines.append(
                    f"    {sector}: ${row['mean']:,.0f}/month  (n={int(row['count'])})"
                )

        return "\n".join(lines)

    def career_level_stats(self) -> str:
        # Prefer the normalised column (_career_norm) so numbers match the dashboard
        col = "_career_norm" if _has(self.df, "_career_norm") else "career_level"
        if not _has(self.df, col):
            return "Career level data not available in this dataset."

        lines = [f"CAREER LEVEL DISTRIBUTION  ({len(self.df):,} total postings)\n"]
        for tl in self.timelines:
            sub = self._sub(tl)
            counts = sub[col].dropna().value_counts()
            total_with_data = int(sub[col].notna().sum())
            lines.append(f"  {tl}  (data for {total_with_data:,} of {len(sub):,} postings):")
            for lvl, n in counts.items():
                lines.append(f"    {lvl}: {n}  ({_pct(n, total_with_data)}%)")
            lines.append("")

        # Cross-country if multiple countries present
        if _has(self.df, "_country") and self.df["_country"].nunique() > 1:
            lines.append("  BY COUNTRY:")
            for country, cdf in self.df.groupby("_country"):
                counts = cdf[col].dropna().value_counts()
                n_with = int(cdf[col].notna().sum())
                lines.append(f"    {country} ({len(cdf):,} postings):")
                for lvl, n in counts.head(6).items():
                    lines.append(f"      {lvl}: {n}  ({_pct(n, n_with)}%)")
        return "\n".join(lines)

    def employment_type_stats(self) -> str:
        # Prefer the normalised column — catches Full-Time / full time / fulltime etc.
        col = "_employment_norm" if _has(self.df, "_employment_norm") else "employment_type"
        if not _has(self.df, col):
            return "Employment type data not available in this dataset."

        lines = [f"EMPLOYMENT TYPE DISTRIBUTION  ({len(self.df):,} total postings)\n"]
        for tl in self.timelines:
            sub = self._sub(tl)
            counts = sub[col].dropna().value_counts()
            total_with_data = int(sub[col].notna().sum())
            lines.append(f"  {tl}  (data for {total_with_data:,} of {len(sub):,} postings):")
            for et, n in counts.items():
                lines.append(f"    {et}: {n}  ({_pct(n, total_with_data)}%)")
            lines.append("")

        # Cross-country if multiple countries present
        if _has(self.df, "_country") and self.df["_country"].nunique() > 1:
            lines.append("  BY COUNTRY:")
            for country, cdf in self.df.groupby("_country"):
                counts = cdf[col].dropna().value_counts().head(4)
                lines.append(f"    {country}:")
                for et, n in counts.items():
                    lines.append(f"      {et}: {n}")
        return "\n".join(lines)

    def company_stats(self, n: int = 20) -> str:
        if not _has(self.df, "company"):
            return "Company data not available in this dataset."

        lines = [f"TOP HIRING COMPANIES  ({len(self.df):,} total postings)\n"]
        overall = self.df["company"].value_counts().head(n)
        lines.append(f"  Overall top {n}:")
        for co, cnt in overall.items():
            lines.append(f"    {co}: {cnt} postings")

        if len(self.timelines) >= 2:
            for tl in self.timelines:
                sub = self._sub(tl)
                top = sub["company"].value_counts().head(8)
                lines.append(f"\n  Top in {tl}:")
                for co, cnt in top.items():
                    lines.append(f"    {co}: {cnt}")
        return "\n".join(lines)

    def experience_stats(
        self,
        filter_col: str | None = None,
        filter_val: str | None = None,
    ) -> str:
        if not _has(self.df, "experience"):
            return "Experience data not available in this dataset."

        sub = self.df
        if filter_col and filter_val and _has(sub, filter_col):
            sub = sub[sub[filter_col].str.contains(filter_val, case=False, na=False)]

        counts = sub["experience"].value_counts().head(15)
        total_with_data = int(sub["experience"].notna().sum())
        lines = [
            f"EXPERIENCE REQUIREMENTS  "
            f"({total_with_data:,} of {len(sub):,} postings specify experience)\n"
        ]
        for exp, n in counts.items():
            lines.append(f"  {exp}: {n}  ({_pct(n, total_with_data)}%)")
        return "\n".join(lines)

    def education_stats(
        self,
        filter_col: str | None = None,
        filter_val: str | None = None,
    ) -> str:
        if not _has(self.df, "education"):
            return "Education data not available in this dataset."

        sub = self.df
        if filter_col and filter_val and _has(sub, filter_col):
            sub = sub[sub[filter_col].str.contains(filter_val, case=False, na=False)]

        counts = sub["education"].value_counts()
        total_with_data = int(sub["education"].notna().sum())
        lines = [
            f"EDUCATION REQUIREMENTS  "
            f"({total_with_data:,} of {len(sub):,} postings specify education)\n"
        ]
        for edu, n in counts.items():
            lines.append(f"  {edu}: {n}  ({_pct(n, total_with_data)}%)")
        return "\n".join(lines)

    def language_stats(self) -> str:
        if not _has(self.df, "language"):
            return "Language requirement data not available in this dataset."

        sub = self.df["language"].dropna()
        total = len(self.df)
        lines = [
            f"LANGUAGE REQUIREMENTS  "
            f"({len(sub):,} of {total:,} postings specify a language)\n"
        ]
        for lang in ["English", "Arabic", "French", "Hindi", "Urdu"]:
            n = int(sub.str.contains(lang, case=False, na=False).sum())
            if n > 0:
                lines.append(f"  {lang}: {n}  ({_pct(n, total)}%)")
        return "\n".join(lines)

    def trend_comparison(self) -> str:
        if len(self.timelines) < 2:
            return "Only one timeline in the dataset — trend comparison not possible."

        tl1, tl2 = self.timelines[0], self.timelines[1]
        n1 = len(self._sub(tl1))
        n2 = len(self._sub(tl2))
        growth = round((n2 - n1) / n1 * 100, 1) if n1 else 0

        parts = [
            f"TREND COMPARISON: {tl1} vs {tl2}",
            f"  Overall: {n1:,} → {n2:,} postings  (+{growth}% raw volume)\n",
            self.sector_stats(),
            "",
            self.career_level_stats(),
            "",
            self.employment_type_stats(),
        ]
        return "\n".join(parts)

    # ── context builder (called by RAGEngine) ─────────────────────────────────

    def build_context(self, question: str) -> str:
        """
        Heuristically select and assemble the most relevant stats blocks
        for a given question.  Always includes a one-liner dataset summary.
        """
        q = question.lower()
        ov = self.overview()
        parts = [
            f"DATASET SUMMARY: {ov['total_postings']:,} total postings | "
            f"timelines: {', '.join(str(t) for t in ov['timelines'])} | "
            f"salary coverage: {ov['salary_coverage']}"
        ]

        kw = lambda *words: any(w in q for w in words)  # noqa: E731

        if kw("sector", "industry", "field", "domain", "area"):
            parts.append(self.sector_stats())

        if kw("skill", "technology", "tech", "tool", "framework", "programming",
               "python", "sql", "excel", "power bi", "java", "machine learning",
               "cloud", "aws", "azure"):
            role = next(
                (r for r in ["analyst", "engineer", "developer", "manager",
                              "designer", "nurse", "doctor", "accountant"]
                 if r in q),
                None,
            )
            parts.append(self.skill_stats("job_title" if role else None, role))

        if kw("salary", "pay", "compensation", "earn", "income", "wage", "remuneration"):
            # Try to pass a sector or role filter
            fval = next(
                (w for w in ["it", "tech", "engineer", "finance", "health",
                              "construction", "energy", "education"]
                 if w in q),
                None,
            )
            parts.append(self.salary_stats("category" if fval else None, fval))

        if kw("career level", "seniority", "senior", "junior", "entry level",
               "manager", "executive", "mid-level"):
            parts.append(self.career_level_stats())

        if kw("employment type", "full-time", "part-time", "contract",
               "freelance", "temporary", "permanent"):
            parts.append(self.employment_type_stats())

        if kw("company", "companies", "employer", "hiring company",
               "who is hiring", "top employer"):
            parts.append(self.company_stats())

        if kw("experience", "years", "how long", "fresh graduate",
               "entry level", "junior"):
            parts.append(self.experience_stats())

        if kw("education", "degree", "bachelor", "master", "mba",
               "diploma", "phd", "qualification"):
            parts.append(self.education_stats())

        if kw("language", "arabic", "english", "bilingual", "french"):
            parts.append(self.language_stats())

        if kw("trend", "grow", "change", "nov", "feb", "november", "february",
               "month", "compare", "increase", "decrease", "over time"):
            parts.append(self.trend_comparison())

        if kw("overview", "summary", "market", "overall", "general",
               "top job", "most demand", "big picture"):
            parts.append(self.sector_stats())
            parts.append(self.company_stats(10))
            parts.append(self.career_level_stats())

        # Always include sector stats if nothing else triggered
        if len(parts) == 1:
            parts.append(self.sector_stats())
            parts.append(self.skill_stats(n=15))

        return "\n\n".join(parts)
