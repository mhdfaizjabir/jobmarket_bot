"""
filter_registry.py
-------------------
Single source of truth for "explicit filters" — UI-driven selections (e.g. the
dashboard's sector click) that must hold as a hard scope, as opposed to the
soft filters the LLM decomposer infers from question text (_country, _timeline,
career_level, job_title), which keep their existing dedicated handling.

Every layer that touches explicit filters — the API request model, pandas,
SQL, Qdrant payload/index provisioning, and prompt scope notes — reads this
registry instead of hardcoding field names. Adding a new filter (e.g.
Employment Type) means adding one entry here; no other file changes.

Historical Qdrant data still needs a one-time payload backfill when a new
entry is added (the same migration pattern as migrate_sector_payload.py) —
that's an inherent data step, not a pipeline change.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from data_loader import norm_sector, norm_employment, norm_career


@dataclass(frozen=True)
class FilterField:
    key: str                                    # wire key from the frontend/API, e.g. "sector"
    column: str                                  # internal df / SQL / Qdrant payload column, e.g. "_sector_norm"
    label: str                                   # human-readable label for prompt scope notes, e.g. "sector"
    normalize: Optional[Callable[[object], Optional[str]]] = None  # raw-value normalizer for the semantic post-filter safety net


FILTER_REGISTRY: dict[str, FilterField] = {
    "sector":          FilterField(key="sector",          column="_sector_norm",      label="sector",         normalize=norm_sector),
    "employment_type": FilterField(key="employment_type", column="_employment_norm",  label="employment type", normalize=norm_employment),
    "career_level":    FilterField(key="career_level",    column="_career_norm",      label="career level",   normalize=norm_career),
    "company":         FilterField(key="company",         column="company",          label="company"),
    "experience":      FilterField(key="experience",      column="experience",       label="experience"),
    "salary_bucket":   FilterField(key="salary_bucket",   column="_salary_bucket_norm", label="salary range"),
}

# "skill" is deliberately NOT here: postings carry a delimited multi-value skills
# string (parsed via regex split in analytics.py/server.py), not a single scalar
# per row. This registry's exact-match semantics (SQL `col = value`, pandas
# `col.str.lower() == value.lower()`, Qdrant keyword-match payload index) only
# fit single-value columns. Supporting it would mean adding CONTAINS/array-match
# semantics across sql_engine._scope_query, rag_engine._apply_filters, and
# rag_engine._matches_filter_metadata — a real extension of the filter
# architecture, not "one registry entry." Left for a future sprint if wanted.
#
# Existing Qdrant points need a one-time payload backfill for each new column
# (see migrate_sector_payload.py — generalized to cover all registry columns).

_BY_COLUMN: dict[str, FilterField] = {f.column: f for f in FILTER_REGISTRY.values()}

EXPLICIT_FILTER_COLUMNS: frozenset[str] = frozenset(_BY_COLUMN)


def translate_explicit_filters(explicit_filters: dict | None) -> dict[str, str]:
    """Wire-format keys (e.g. {"sector": "Technology"}) -> internal columns (e.g. {"_sector_norm": "Technology"})."""
    if not explicit_filters:
        return {}
    out: dict[str, str] = {}
    for k, v in explicit_filters.items():
        if not v or not str(v).strip():
            continue
        field = FILTER_REGISTRY.get(k)
        if field is None:
            continue  # unknown key (e.g. a newer frontend build) — ignore rather than crash
        out[field.column] = v
    return out


def field_for_column(column: str) -> FilterField | None:
    return _BY_COLUMN.get(column)
