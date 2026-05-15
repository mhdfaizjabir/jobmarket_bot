"""
data_loader.py
--------------
Scans the data/ directory for .xlsx and .csv files, parses the timeline
(month + year) from each filename, normalises column names to canonical
names defined in config.COLUMN_ALIASES, and returns a merged DataFrame.

Adding a new dataset:  drop the file in data/ — no code changes needed.
Renaming columns:      update COLUMN_ALIASES in config.py — no code changes here.
"""

import re
import pandas as pd
from pathlib import Path
from config import DATA_DIR, COLUMN_ALIASES

# ---------------------------------------------------------------------------
# Month name → short label  (covers full names AND common abbreviations)
# ---------------------------------------------------------------------------
_MONTH_MAP: dict[str, str] = {
    "january": "Jan",  "jan": "Jan",
    "february": "Feb", "feb": "Feb",
    "march": "Mar",    "mar": "Mar",
    "april": "Apr",    "apr": "Apr",
    "may": "May",
    "june": "Jun",     "jun": "Jun",
    "july": "Jul",     "jul": "Jul",
    "august": "Aug",   "aug": "Aug",
    "september": "Sep","sep": "Sep",
    "october": "Oct",  "oct": "Oct",
    "november": "Nov", "nov": "Nov",
    "december": "Dec", "dec": "Dec",
}


def parse_timeline(filepath: str | Path) -> str:
    """
    Extract a 'Mon YYYY' label from a filename.

    Examples
    --------
    bayt_jobs_22_Feb_2026.xlsx  →  "Feb 2026"
    jobs_november_2025.csv      →  "Nov 2025"
    data_2026_03.xlsx           →  filename stem (fallback)
    """
    stem = Path(filepath).stem.lower()

    # Find 4-digit year (20xx) — avoid \b since _ is a word char
    year_m = re.search(r"(?<!\d)(20\d{2})(?!\d)", stem)
    year = year_m.group(1) if year_m else None

    # Try to find a month token surrounded by separators or at boundary
    for key, abbr in _MONTH_MAP.items():
        pattern = r"(?:(?<=[_\-\s])|(?<=\d)|^)" + re.escape(key) + r"(?=[_\-\s\d]|$)"
        if re.search(pattern, stem):
            return f"{abbr} {year}" if year else abbr

    # Fallback: return the stem so at least something meaningful is stored
    return stem


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_rename_map(actual_columns: list[str]) -> dict[str, str]:
    """
    Return {actual_col: canonical_name} for every matched column.
    Matching is case-insensitive; first alias that matches wins.
    """
    lower_to_actual = {c.lower(): c for c in actual_columns}
    rename: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower_to_actual:
                original = lower_to_actual[alias.lower()]
                rename[original] = canonical
                break  # first match wins
    return rename


def _load_file(path: Path) -> pd.DataFrame:
    """Load a single Excel or CSV file into a DataFrame."""
    if path.suffix.lower() == ".xlsx":
        return pd.read_excel(path)
    elif path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def _normalise(df: pd.DataFrame, timeline: str, source_file: str) -> pd.DataFrame:
    """Rename columns to canonical names and inject metadata columns."""
    rename_map = _build_rename_map(list(df.columns))
    df = df.rename(columns=rename_map)
    df["_timeline"] = timeline
    df["_source_file"] = Path(source_file).name
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, list[str]]:
    """
    Scan *data_dir* for .xlsx/.csv files, load and normalise each one,
    and return (merged_df, sorted_timelines).

    The merged DataFrame always contains:
      • canonical column names (whatever matched in COLUMN_ALIASES)
      • _timeline  — e.g. "Feb 2026"
      • _source_file — e.g. "bayt_jobs_22_Feb_2026.xlsx"

    Raises FileNotFoundError if the directory contains no supported files.
    """
    files = sorted(
        list(data_dir.glob("*.xlsx")) + list(data_dir.glob("*.csv"))
    )
    if not files:
        raise FileNotFoundError(f"No .xlsx or .csv files found in {data_dir}")

    frames: list[pd.DataFrame] = []
    for f in files:
        timeline = parse_timeline(f)
        raw = _load_file(f)
        normalised = _normalise(raw, timeline, str(f))
        frames.append(normalised)

    merged = pd.concat(frames, ignore_index=True)

    # Sorted timelines: chronological by parsing year+month back out
    timelines = _sort_timelines(
        list({t for df in frames for t in df["_timeline"].unique()})
    )
    return merged, timelines


def _sort_timelines(timelines: list[str]) -> list[str]:
    """Sort timeline labels chronologically (best-effort)."""
    _MONTH_ORDER = {v: i for i, v in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )}

    def _key(tl: str):
        parts = tl.split()
        try:
            month = _MONTH_ORDER.get(parts[0], 99)
            year = int(parts[1]) if len(parts) > 1 else 0
            return (year, month)
        except Exception:
            return (9999, 99)

    return sorted(timelines, key=_key) 
