"""
build_index.py — Offline index builder
---------------------------------------
Run this ONCE before starting the app, and whenever new data files are added.
The Streamlit app reads the pre-built index instantly — no waiting.

Usage:
  python build_index.py           # incremental (only new/changed files)
  python build_index.py --full    # force full rebuild (needed after format changes)

Production workflow:
  1. Drop new Excel file in data/
  2. python build_index.py        ← runs in terminal (not in the app)
  3. streamlit run app.py         ← starts instantly with updated index
"""

import sys
import time
from pathlib import Path

from tqdm import tqdm

from config import DATA_DIR
from data_loader import load_all, parse_file_info
from vector_store import VectorStore


def main():
    force_full = "--full" in sys.argv

    print("=" * 55)
    print("  GCC Job Market — Index Builder")
    print("=" * 55)

    # Discover source files (EN only, no lock files)
    source_files = sorted(
        str(p) for p in (list(DATA_DIR.glob("*.xlsx")) + list(DATA_DIR.glob("*.csv")))
        if not p.name.startswith("~$") and not parse_file_info(p)["is_ar"]
    )

    if not source_files:
        print(f"No data files found in {DATA_DIR}")
        sys.exit(1)

    print(f"\nData files found ({len(source_files)}):")
    for f in source_files:
        info = parse_file_info(f)
        size = Path(f).stat().st_size / 1_000_000
        print(f"  {Path(f).name}  ({info['country']}, {info['timeline']}, {size:.1f} MB)")

    # Load data
    print("\nLoading and normalising data...")
    t0 = time.time()
    df, timelines = load_all(DATA_DIR)
    print(f"  {len(df):,} postings loaded in {time.time()-t0:.1f}s")
    print(f"  Countries: {sorted(df['_country'].unique().tolist())}")
    print(f"  Timelines: {timelines}")

    # Build index
    vs = VectorStore()
    print(f"\nExisting index: {vs.count():,} documents")

    if force_full:
        print("\nForce full rebuild requested...")
        mode = "full"
    elif vs.needs_indexing(source_files):
        new = vs.new_files(source_files)
        if new:
            print(f"\nNew/changed files detected: {[Path(f).name for f in new]}")
        mode = "incremental"
    else:
        print("\nIndex is already up to date.")
        print(f"Total indexed: {vs.count():,} documents")
        return

    # Progress bar
    bar = tqdm(total=len(df), desc="Embedding", unit="docs", ncols=70)

    def on_progress(done: int, total: int):
        bar.n = done
        bar.refresh()

    t1 = time.time()
    if mode == "full":
        vs.build_index(df, source_files, progress_callback=on_progress)
        msg = "Full rebuild"
    else:
        msg = vs.build_index_incremental(df, source_files, progress_callback=on_progress)

    bar.close()
    elapsed = time.time() - t1

    print(f"\n{msg}")
    print(f"Total indexed: {vs.count():,} documents")
    print(f"Time taken: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print("\nDone! Start the app with: streamlit run app.py")


if __name__ == "__main__":
    main()
