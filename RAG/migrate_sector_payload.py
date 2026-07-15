"""
migrate_sector_payload.py
--------------------------
One-off backfill: adds `_sector_norm` to every existing Qdrant point's payload,
computed from the already-stored raw `category` field via norm_sector(). This
makes sector a filterable field for the RAG chatbot (Sprint 1 — filter
propagation) without re-embedding any vectors — only a payload merge.

Safe to re-run: points that already carry `_sector_norm` are skipped.

Run:  python migrate_sector_payload.py
"""

from collections import defaultdict

from data_loader import norm_sector
from vector_store import VectorStore, QDRANT_COLLECTION


def main():
    vs = VectorStore()
    client = vs._client
    total = vs.count()
    print(f"Scanning {total:,} points in '{QDRANT_COLLECTION}'...")

    updated = 0
    skipped = 0
    no_category = 0
    offset = None

    while True:
        result = client.scroll(QDRANT_COLLECTION, limit=500, offset=offset)
        points = result.get("points", [])
        if not points:
            break

        by_sector: dict[str, list[str]] = defaultdict(list)
        for p in points:
            payload = p.get("payload") or {}
            if "_sector_norm" in payload:
                skipped += 1
                continue
            sector = norm_sector(payload.get("category"))
            if not sector:
                no_category += 1
                continue
            by_sector[sector].append(p["id"])

        for sector, ids in by_sector.items():
            client.set_payload(QDRANT_COLLECTION, {"_sector_norm": sector}, ids)
            updated += len(ids)

        print(f"  batch done — updated={updated:,} skipped={skipped:,} no_category={no_category:,} "
              f"next_offset={result.get('next_page_offset')!r}")

        offset = result.get("next_page_offset")
        if offset is None:
            break

    print(f"Done — updated {updated:,} points, skipped {skipped:,} already-migrated, "
          f"{no_category:,} had no usable category.")


if __name__ == "__main__":
    main()
