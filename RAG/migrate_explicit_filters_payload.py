"""
migrate_explicit_filters_payload.py
------------------------------------
One-off backfill for the explicit filters added alongside dashboard drill-down
(employment_type, career_level, salary_bucket): adds each field's normalized
`_..._norm` column to every existing Qdrant point's payload, computed from the
raw field the point already carries (same pattern as migrate_sector_payload.py,
generalized so future registry entries reuse this instead of a new one-off
script each time).

Only covers registry entries whose source raw field is already present in
every point's payload today (employment_type -> _employment_norm,
career_level -> _career_norm, salary -> _salary_bucket_norm). `company` needs
no backfill (it's already a raw stored field). `experience` is NOT covered —
the raw `experience` field was never stored in the payload at embedding time,
so there is no source data in Qdrant to derive it from; that one needs a full
re-embed via build_index.py, not a payload merge. Semantic (Qdrant) retrieval
scoped by "experience" will return few/no hits on unmigrated points until
that rebuild runs — the SQL/pandas/dashboard layers are unaffected since they
read straight from the source files, not Qdrant.

Safe to re-run: points that already carry a target field are skipped for it.

Run:  python migrate_explicit_filters_payload.py
"""

from collections import defaultdict

from data_loader import norm_employment, norm_career, norm_salary_bucket
from vector_store import VectorStore, QDRANT_COLLECTION

# (target payload field, source raw payload field, normalize fn)
_MIGRATIONS = [
    ("_employment_norm",   "employment_type", norm_employment),
    ("_career_norm",       "career_level",    norm_career),
    ("_salary_bucket_norm", "salary",         norm_salary_bucket),
]


def main():
    vs = VectorStore()
    client = vs._client
    total = vs.count()
    print(f"Scanning {total:,} points in '{QDRANT_COLLECTION}' for {len(_MIGRATIONS)} fields...")

    updated = {target: 0 for target, _, _ in _MIGRATIONS}
    skipped = {target: 0 for target, _, _ in _MIGRATIONS}
    no_source = {target: 0 for target, _, _ in _MIGRATIONS}
    offset = None

    while True:
        result = client.scroll(QDRANT_COLLECTION, limit=500, offset=offset)
        points = result.get("points", [])
        if not points:
            break

        by_value: dict[str, dict[str, list[str]]] = {target: defaultdict(list) for target, _, _ in _MIGRATIONS}
        for p in points:
            payload = p.get("payload") or {}
            for target, source, normalize in _MIGRATIONS:
                if target in payload:
                    skipped[target] += 1
                    continue
                value = normalize(payload.get(source))
                if not value:
                    no_source[target] += 1
                    continue
                by_value[target][value].append(p["id"])

        for target, _, _ in _MIGRATIONS:
            for value, ids in by_value[target].items():
                client.set_payload(QDRANT_COLLECTION, {target: value}, ids)
                updated[target] += len(ids)

        print(f"  batch done — " + ", ".join(
            f"{t}: updated={updated[t]:,} skipped={skipped[t]:,} no_source={no_source[t]:,}"
            for t, _, _ in _MIGRATIONS
        ) + f" next_offset={result.get('next_page_offset')!r}")

        offset = result.get("next_page_offset")
        if offset is None:
            break

    print("Done.")
    for target, _, _ in _MIGRATIONS:
        print(f"  {target}: updated {updated[target]:,}, skipped {skipped[target]:,} already-migrated, "
              f"{no_source[target]:,} had no usable source value.")


if __name__ == "__main__":
    main()
