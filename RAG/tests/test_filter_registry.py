"""Unit tests for the explicit-filter registry — the single source of truth
every pipeline layer (pandas, SQL, Qdrant, prompts) derives its filter
handling from. If these break, dashboard↔chat consistency breaks."""

import pytest

from filter_registry import (
    EXPLICIT_FILTER_COLUMNS,
    FILTER_REGISTRY,
    field_for_column,
    translate_explicit_filters,
)

# The set of wire keys the dashboard/chat currently ship UI controls for. If a
# field is added to or removed from the registry, this list must change too —
# so a silent, untested drift (a renamed column, a dropped field) fails here
# rather than only surfacing as a broken filter in production.
EXPECTED_FIELDS = {
    "sector":          "_sector_norm",
    "employment_type": "_employment_norm",
    "career_level":    "_career_norm",
    "company":         "company",
    "experience":      "experience",
    "salary_bucket":   "_salary_bucket_norm",
}


def test_registry_matches_expected_fields():
    # Guards against both accidental removal and undocumented addition.
    assert set(FILTER_REGISTRY) == set(EXPECTED_FIELDS)


@pytest.mark.parametrize("wire_key,column", EXPECTED_FIELDS.items())
def test_field_registered_with_expected_column(wire_key, column):
    assert wire_key in FILTER_REGISTRY
    assert FILTER_REGISTRY[wire_key].column == column
    assert column in EXPLICIT_FILTER_COLUMNS


@pytest.mark.parametrize("wire_key,column", EXPECTED_FIELDS.items())
def test_every_field_translates_and_roundtrips(wire_key, column):
    # Each registered field must map wire-key -> column and back, so a typo in
    # any single entry (not just sector) is caught.
    assert translate_explicit_filters({wire_key: "X"}) == {column: "X"}
    field = field_for_column(column)
    assert field is not None and field.key == wire_key


@pytest.mark.parametrize("field", FILTER_REGISTRY.values(), ids=lambda f: f.key)
def test_declared_normalizers_are_callable_and_stable(field):
    # Where a field declares a normalizer, it must run without error and be
    # idempotent on an already-normalized value (the semantic post-filter
    # relies on both properties).
    if field.normalize is None:
        pytest.skip(f"{field.key} has no normalizer")
    once = field.normalize("Full-Time")
    assert field.normalize(once) == once


def test_sector_is_registered():
    assert "sector" in FILTER_REGISTRY
    assert FILTER_REGISTRY["sector"].column == "_sector_norm"
    assert "_sector_norm" in EXPLICIT_FILTER_COLUMNS


def test_translate_maps_wire_key_to_column():
    assert translate_explicit_filters({"sector": "Technology"}) == {"_sector_norm": "Technology"}


def test_translate_drops_unknown_keys():
    # An unknown key (e.g. a newer frontend build) must be ignored, not crash.
    out = translate_explicit_filters({"sector": "Technology", "bogus_key": "x"})
    assert out == {"_sector_norm": "Technology"}


def test_translate_drops_empty_values():
    assert translate_explicit_filters({"sector": ""}) == {}
    assert translate_explicit_filters({"sector": "   "}) == {}
    assert translate_explicit_filters(None) == {}
    assert translate_explicit_filters({}) == {}


def test_field_for_column_roundtrip():
    field = field_for_column("_sector_norm")
    assert field is not None and field.key == "sector"
    assert field_for_column("nonexistent_column") is None


def test_sector_normalizer_attached():
    # The semantic post-filter safety net relies on this to normalize raw
    # `category` payload values before comparing.
    field = FILTER_REGISTRY["sector"]
    assert field.normalize is not None
    assert field.normalize("Oil and Gas") == field.normalize("Oil & Gas")
