"""
data_loader.py
--------------
Scans data/ for EN and AR Excel/CSV files, parses country + timeline from
the filename, normalises column names, applies substring-based normalization
for career level and employment type (catches ALL variants), merges Arabic
signals where an AR counterpart exists, and returns a combined DataFrame.

Filename convention (professor's format):
  EN:  bayt_jobs_{Country}_{Day}_{Month}_{Year}.xlsx
  AR:  bayt_jobs_{Country}_AR_{Day}_{Month}_{Year}.xlsx

Examples:
  bayt_jobs_Qatar_22_Nov_2025.xlsx       → country=Qatar, timeline=Nov 2025
  bayt_jobs_Saudi_Arabia_AR_12_May_2026.xlsx → country=Saudi Arabia, AR signals
"""

import re
import pandas as pd
from pathlib import Path
from config import DATA_DIR, COLUMN_ALIASES

# ---------------------------------------------------------------------------
# Month helpers
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

_MONTH_ORDER = {v: i for i, v in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)}


# ---------------------------------------------------------------------------
# Substring-based normalization  (catches ALL variants — fixes wrong answers)
# ---------------------------------------------------------------------------

def norm_employment(val) -> str | None:
    """
    Map any employment-type string to a canonical label using substring match.
    Handles: Full-Time / full time / fulltime / Full Time / FULL-TIME / etc.
    """
    if pd.isna(val) or not str(val).strip():
        return None
    s = str(val).strip().lower().replace("-", " ").replace("_", " ")
    if "full" in s and "time" in s:        return "Full-Time"
    if "part" in s and "time" in s:        return "Part-Time"
    if "contract" in s:                    return "Contract"
    if "freelance" in s or "free lance" in s: return "Freelance"
    if "intern" in s:                      return "Internship"
    if "temp" in s:                        return "Temporary"
    return str(val).strip()                # keep original if unrecognised


def norm_career(val) -> str | None:
    """
    Map any career-level string to a canonical label using substring match.
    Uses the same logic as the professor's norm_career() to ensure our numbers
    match his dashboard exactly.
    """
    if pd.isna(val) or not str(val).strip():
        return None
    s = str(val).strip().lower()

    # Order matters: most specific first
    if any(x in s for x in ["executive", "c-level", "chief", "إدارة عليا تنفيذية"]):
        return "Executive"
    if "director" in s:
        return "Director"
    # Senior management → Executive (more senior than regular Manager)
    if "senior management" in s or "senior mgmt" in s or "senior managerial" in s:
        return "Executive"
    # Management / manager / supervisory → Manager
    if any(x in s for x in ["manager", "managerial", "management", "إدارة"]):
        return "Manager"
    if "senior" in s or "sr." in s:
        return "Senior"
    if any(x in s for x in ["supervisor", "supervisory"]):
        return "Manager"
    # Mid-level — catches consultant, متوسط الخبرة, intermediate, professional, etc.
    if any(x in s for x in ["mid", "intermediate", "consultant", "professional",
                              "experienced hire", "متوسط", "associate"]):
        return "Mid-Level"
    # Entry level
    if any(x in s for x in ["entry", "junior", "graduate", "مبتدئ",
                              "intern", "trainee", "student", "undergraduate",
                              "fresh", "early career"]):
        return "Entry-Level"
    return str(val).strip()   # keep original if unrecognised


def norm_sector(val) -> str | None:
    """Consolidate duplicate sector names (e.g. Oil and Gas / Oil & Gas)."""
    if pd.isna(val) or not str(val).strip():
        return None
    s = str(val).strip().lower()
    _ALIASES = {
        "oil and gas": "Oil & Gas",
        "oil & gas": "Oil & Gas",
        "information technology": "Technology",
        "it": "Technology",
        "tech": "Technology",
        "commercial support services": "Commercial Support",
        "business support services": "Business Support",
        "services and support": "Services",
        "services & support": "Services",
    }
    return _ALIASES.get(s, str(val).strip())


# ---------------------------------------------------------------------------
# Arabic-portal signal extractors
# ---------------------------------------------------------------------------

def _lang_signal(text) -> str:
    if pd.isna(text) or not str(text).strip():
        return "unspecified"
    t = str(text).lower()
    ar_req = any(x in t for x in [
        "arabic mandatory", "fluent in arabic", "arabic required",
        "arabic fluency", "إجادة اللغة العربية", "العربية إلزامي",
        "اللغة العربية شرط",
    ])
    en_req = any(x in t for x in [
        "english mandatory", "fluent in english", "english required",
        "english fluency", "إجادة الإنجليزية", "الإنجليزية إلزامي",
    ])
    if ar_req and en_req:  return "both"
    if ar_req:             return "arabic"
    if en_req:             return "english"
    return "unspecified"


_NATIONAL_KW: dict[str, list[str]] = {
    "Qatar":        ["مواطن قطري", "قطري الجنسية", "للقطريين", "qatarization", "qatari national"],
    "UAE":          ["مواطن إماراتي", "إماراتي الجنسية", "للإماراتيين", "emiratization", "emirati national"],
    "Saudi Arabia": ["سعودي الجنسية", "للسعوديين", "مواطن سعودي", "saudization", "saudi national", "nitaqat"],
}


def _national_signal(text, country: str) -> bool:
    if pd.isna(text) or not str(text).strip():
        return False
    t = str(text).lower()
    return any(k.lower() in t for k in _NATIONAL_KW.get(country, []))


def _remote_signal(text) -> bool:
    if pd.isna(text) or not str(text).strip():
        return False
    t = str(text).lower()
    return any(x in t for x in ["remote", "work from home", "hybrid", "wfh",
                                  "عن بعد", "من المنزل", "عمل عن بعد"])


# ---------------------------------------------------------------------------
# Filename parser
# ---------------------------------------------------------------------------

def parse_file_info(filepath: str | Path) -> dict:
    """
    Parse a Bayt.com filename into metadata.

    Accepted formats
    ----------------
    bayt_jobs_{Country}_{Day}_{Month}_{Year}.xlsx       ← EN posting data
    bayt_jobs_{Country}_AR_{Day}_{Month}_{Year}.xlsx    ← Arabic portal data
    anything_else.xlsx                                  ← fallback (unknown country)

    Returns
    -------
    dict with keys: country, timeline, dump_id, dump_label, is_ar
    """
    stem = Path(filepath).stem

    if not stem.lower().startswith("bayt_jobs_"):
        # Legacy / unknown format — derive timeline from filename heuristically
        tl = _parse_timeline_fallback(stem)
        return {
            "country":    "Unknown",
            "timeline":   tl,
            "dump_id":    re.sub(r"[^a-z0-9]", "_", stem.lower()),
            "dump_label": stem,
            "is_ar":      False,
        }

    rest = stem[len("bayt_jobs_"):]

    # Detect and strip AR flag
    is_ar = bool(re.search(r"_AR_", rest, re.IGNORECASE))
    if is_ar:
        rest = re.sub(r"_AR_", "_", rest, count=1, flags=re.IGNORECASE)

    # Pattern: {Country_Words}_{1-2 digit day}_{3+ alpha month}_{4 digit year}
    m = re.match(r"^(.+?)_(\d{1,2})_([A-Za-z]{3,9})_(\d{4})$", rest)
    if not m:
        tl = _parse_timeline_fallback(stem)
        return {
            "country":    "Unknown",
            "timeline":   tl,
            "dump_id":    re.sub(r"[^a-z0-9]", "_", stem.lower()),
            "dump_label": stem,
            "is_ar":      is_ar,
        }

    country_raw = m.group(1)                                        # e.g. "Saudi_Arabia"
    month_key   = m.group(3).lower()                               # e.g. "nov"
    month_abbr  = _MONTH_MAP.get(month_key, m.group(3).capitalize())  # e.g. "Nov"
    year        = m.group(4)                                        # e.g. "2025"

    country    = country_raw.replace("_", " ")                     # "Saudi Arabia"
    timeline   = f"{month_abbr} {year}"                            # "Nov 2025"
    dump_id    = f"{country_raw.lower()}_{month_abbr.lower()}_{year}"  # "qatar_nov_2025"
    dump_label = f"{country} {timeline}"                           # "Qatar Nov 2025"

    return {
        "country":    country,
        "timeline":   timeline,
        "dump_id":    dump_id,
        "dump_label": dump_label,
        "is_ar":      is_ar,
    }


def _parse_timeline_fallback(stem: str) -> str:
    """Heuristic timeline extraction from arbitrary filenames."""
    s = stem.lower()
    year_m = re.search(r"(?<!\d)(20\d{2})(?!\d)", s)
    year = year_m.group(1) if year_m else None
    # Split on separators and check each token — avoids variable-width lookbehind
    tokens = set(re.split(r"[_\-\s\d]+", s))
    for key, abbr in _MONTH_MAP.items():
        if key in tokens:
            return f"{abbr} {year}" if year else abbr
    return stem


# ---------------------------------------------------------------------------
# Column alias resolver
# ---------------------------------------------------------------------------

def _build_rename_map(actual_columns: list[str]) -> dict[str, str]:
    lower_to_actual = {c.lower(): c for c in actual_columns}
    rename: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower_to_actual:
                rename[lower_to_actual[alias.lower()]] = canonical
                break
    return rename


def _load_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".xlsx":
        return pd.read_excel(path)
    elif path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


# ---------------------------------------------------------------------------
# Timeline sort helper
# ---------------------------------------------------------------------------

def _sort_timelines(timelines: list[str]) -> list[str]:
    return sort_timelines(timelines)


def sort_timelines(timelines: list[str]) -> list[str]:
    """
    Sort timeline labels chronologically (earliest first).
    Uses (year, month_index) key — never alphabetical.
    Public version — import this wherever timeline lists need ordering.

    Examples
    --------
    ['May 2026', 'Nov 2025', 'Feb 2026']  →  ['Nov 2025', 'Feb 2026', 'May 2026']
    """
    def _key(tl: str):
        parts = tl.split()
        try:
            return (int(parts[1]) if len(parts) > 1 else 0,
                    _MONTH_ORDER.get(parts[0], 99))
        except Exception:
            return (9999, 99)
    return sorted(timelines, key=_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, list[str]]:
    """
    Scan data_dir for all Excel/CSV files.

    - EN files  → primary posting data, normalised + enriched
    - AR files  → bilingual signal extraction only (language, nationalization, remote)
                  merged into EN rows by job_id where available

    Returns (merged_df, sorted_timelines_list).
    The DataFrame contains all canonical columns plus:
      _timeline, _country, _dump_id, _dump_label, _source_file
      _employment_norm, _career_norm, _sector_norm
      _lang_signal, _national_signal, _remote_signal  (from AR portal)
    """
    all_files = sorted(
        f for f in list(data_dir.glob("*.xlsx")) + list(data_dir.glob("*.csv"))
        if not f.name.startswith("~$")   # skip Excel lock files
    )
    if not all_files:
        raise FileNotFoundError(f"No data files found in {data_dir}")

    # Separate EN and AR files
    en_entries: list[tuple[Path, dict]] = []
    ar_lookup:  dict[str, Path] = {}   # dump_id → AR file path

    for f in all_files:
        info = parse_file_info(f)
        if info["is_ar"]:
            ar_lookup[info["dump_id"]] = f
        else:
            en_entries.append((f, info))

    if not en_entries:
        raise FileNotFoundError("No EN (non-AR) data files found.")

    frames: list[pd.DataFrame] = []

    for f, info in en_entries:
        raw = _load_file(f)
        rename_map = _build_rename_map(list(raw.columns))
        df = raw.rename(columns=rename_map)

        # Inject file-level metadata
        df["_timeline"]   = info["timeline"]
        df["_country"]    = info["country"]
        df["_dump_id"]    = info["dump_id"]
        df["_dump_label"] = info["dump_label"]
        df["_source_file"] = f.name

        # Substring-normalised columns (fix for wrong-answer bug)
        if "employment_type" in df.columns:
            df["_employment_norm"] = df["employment_type"].apply(norm_employment)
        else:
            df["_employment_norm"] = None

        if "career_level" in df.columns:
            df["_career_norm"] = df["career_level"].apply(norm_career)
        else:
            df["_career_norm"] = None

        if "category" in df.columns:
            df["_sector_norm"] = df["category"].apply(norm_sector)
        else:
            df["_sector_norm"] = None

        # Try to merge AR bilingual signals
        ar_path = ar_lookup.get(info["dump_id"])
        if ar_path:
            try:
                ar_raw    = _load_file(ar_path)
                ar_rename = _build_rename_map(list(ar_raw.columns))
                ar_df     = ar_raw.rename(columns=ar_rename)

                # Identify the Arabic content column
                ar_col = next(
                    (c for c in ar_df.columns
                     if any(k in c.lower() for k in ["original", "ar_content", "page_content"])),
                    None,
                )

                if ar_col and "job_id" in ar_df.columns and "job_id" in df.columns:
                    ar_sub = (ar_df[["job_id", ar_col]]
                              .rename(columns={ar_col: "_ar_content"})
                              .drop_duplicates("job_id"))
                    df = df.merge(ar_sub, on="job_id", how="left")
                    df["_lang_signal"]     = df["_ar_content"].apply(_lang_signal)
                    df["_national_signal"] = df.apply(
                        lambda r: _national_signal(r.get("_ar_content"), info["country"]),
                        axis=1,
                    )
                    df["_remote_signal"]   = df["_ar_content"].apply(_remote_signal)
                else:
                    _add_empty_ar_cols(df)
            except Exception:
                _add_empty_ar_cols(df)
        else:
            _add_empty_ar_cols(df)

        frames.append(df)

    merged = pd.concat(frames, ignore_index=True)
    timelines = _sort_timelines(
        list({t for df in frames for t in df["_timeline"].dropna().unique()})
    )
    return merged, timelines


def _add_empty_ar_cols(df: pd.DataFrame):
    df["_ar_content"]      = None
    df["_lang_signal"]     = "unspecified"
    df["_national_signal"] = False
    df["_remote_signal"]   = False
