"""
vector_store.py
---------------
ChromaDB wrapper for building and querying the semantic index.

PRODUCTION DESIGN:
  - Build index OFFLINE with: python build_index.py
  - App reads pre-built index instantly on startup — zero wait
  - Incremental indexing: only new/changed files are re-embedded
    (adding a new country takes minutes, not hours)
  - Manifest tracks which files are indexed by MD5 hash

MANIFEST_VERSION: bump this number ONLY when the document text
format changes (e.g. new fields added). Forces a full rebuild.
"""

import json
import hashlib
import warnings
from pathlib import Path

import chromadb
import pandas as pd
from chromadb.utils import embedding_functions
from tqdm import tqdm

from config import (
    CHROMA_DIR,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    DESCRIPTION_TRUNCATE,
    TOP_K,
)

MANIFEST_PATH    = CHROMA_DIR / "_manifest.json"
MANIFEST_VERSION = 2          # bumped: Country + Timeline now lead every document
_BATCH_SIZE      = 512        # larger batches = fewer embedding calls = faster


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(file_hashes: dict[str, str]):
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps({"version": MANIFEST_VERSION, "files": file_hashes}, indent=2),
        encoding="utf-8",
    )


def _file_hash(path: str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _fname(path: str) -> str:
    """Use filename only as manifest key — works on any OS / deploy path."""
    return Path(path).name


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

_DOC_FIELDS: list[tuple[str, str]] = [
    ("job_title",       "Job Title"),
    ("company",         "Company"),
    ("category",        "Sector"),
    ("location",        "Location"),
    ("career_level",    "Career Level"),
    ("experience",      "Years of Experience"),
    ("employment_type", "Employment Type"),
    ("education",       "Education"),
    ("salary",          "Salary"),
    ("skills",          "Skills"),
    ("qualifications",  "Qualifications"),
    ("language",        "Language"),
    ("gender",          "Gender"),
]

_META_COLS = [
    "job_title", "company", "category", "location",
    "career_level", "employment_type", "education",
    "salary", "_timeline", "_source_file", "_country",
]


def _build_doc_text(row: pd.Series) -> str:
    parts = []

    # Country and timeline FIRST — prevents the LLM from defaulting to wrong country
    if "_country" in row.index and pd.notna(row["_country"]) and str(row["_country"]).strip():
        parts.append(f"Country: {row['_country']}")
    if "_timeline" in row.index and pd.notna(row["_timeline"]) and str(row["_timeline"]).strip():
        parts.append(f"Timeline: {row['_timeline']}")

    for col, label in _DOC_FIELDS:
        if col in row.index:
            val = row[col]
            if pd.notna(val) and str(val).strip():
                parts.append(f"{label}: {val}")

    # Truncated description
    for desc_col in ("description", "original_content"):
        if desc_col in row.index and pd.notna(row[desc_col]):
            parts.append(f"Description: {str(row[desc_col])[:DESCRIPTION_TRUNCATE]}")
            break

    return "\n".join(parts)


def _build_metadata(row: pd.Series) -> dict:
    """ChromaDB metadata: str/int/float/bool only — no None/NaN."""
    meta = {}
    for col in _META_COLS:
        if col in row.index and pd.notna(row[col]):
            meta[col] = str(row[col])
    return meta


def _make_row_id(row: pd.Series, idx: int) -> str:
    """Stable unique ID: source_file + job_id (or fallback to index)."""
    src  = str(row.get("_source_file", "unknown"))
    jid  = str(row.get("job_id", idx))
    return f"{src}::{jid}"


# ---------------------------------------------------------------------------
# VectorStore class
# ---------------------------------------------------------------------------

class VectorStore:
    def __init__(self):
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=self._ef,
        )

    # ── Status helpers ───────────────────────────────────────────────────────

    def count(self) -> int:
        return self._collection.count()

    def needs_indexing(self, source_files: list[str]) -> bool:
        """True when index is empty, version changed, or any file hash changed."""
        if self._collection.count() == 0:
            return True
        manifest = _load_manifest()
        if manifest.get("version") != MANIFEST_VERSION:
            return True
        stored = manifest.get("files", {})
        # Use filename only as key — works across different machines/paths
        return any(stored.get(_fname(f)) != _file_hash(f) for f in source_files)

    def new_files(self, source_files: list[str]) -> list[str]:
        """Return list of files not yet indexed (or changed since last index)."""
        if _load_manifest().get("version") != MANIFEST_VERSION:
            return source_files
        stored = _load_manifest().get("files", {})
        return [f for f in source_files if stored.get(_fname(f)) != _file_hash(f)]

    # ── Full rebuild (used when doc format changes) ──────────────────────────

    def build_index(
        self,
        df: pd.DataFrame,
        source_files: list[str],
        progress_callback=None,
    ):
        """
        Full rebuild — deletes the collection and re-embeds everything.
        Use this when MANIFEST_VERSION changes.
        For adding new data files, use build_index_incremental() instead.
        """
        try:
            self._client.delete_collection(CHROMA_COLLECTION)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=self._ef,
        )
        self._upsert_rows(df, progress_callback)
        _save_manifest({_fname(f): _file_hash(f) for f in source_files})

    # ── Incremental (production default) ─────────────────────────────────────

    def build_index_incremental(
        self,
        df: pd.DataFrame,
        source_files: list[str],
        progress_callback=None,
    ) -> str:
        """
        PRODUCTION METHOD: only embed files that are new or changed.

        - If manifest version changed → falls back to full rebuild
        - If one new country file added → only that file's rows are embedded
        - Existing rows are untouched (fast)

        Returns a status string for display.
        """
        manifest = _load_manifest()

        # Version bump → must rebuild everything
        if manifest.get("version") != MANIFEST_VERSION:
            self.build_index(df, source_files, progress_callback)
            return "Full rebuild complete (document format updated)."

        stored = manifest.get("files", {})
        changed = [f for f in source_files if stored.get(f) != _file_hash(f)]

        if not changed:
            return "Index already up to date — nothing to do."

        # Only embed rows from new/changed files
        changed_names = {Path(f).name for f in changed}
        new_rows = df[df["_source_file"].isin(changed_names)] if "_source_file" in df.columns else df

        print(f"Incremental index: embedding {len(new_rows):,} rows from {len(changed)} file(s)...")
        self._upsert_rows(new_rows, progress_callback)

        # Update manifest — keep existing hashes, add new ones (filename keys only)
        updated = {**stored, **{_fname(f): _file_hash(f) for f in changed}}
        _save_manifest(updated)
        return f"Incremental update: {len(new_rows):,} rows from {len(changed)} file(s) added."

    # ── Internal ─────────────────────────────────────────────────────────────

    def _upsert_rows(self, df: pd.DataFrame, progress_callback=None):
        """Embed and upsert rows into the collection in batches."""
        docs, metas, ids = [], [], []
        for i, (_, row) in enumerate(df.iterrows()):
            docs.append(_build_doc_text(row))
            metas.append(_build_metadata(row))
            ids.append(_make_row_id(row, i))

        total = len(docs)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for start in tqdm(range(0, total, _BATCH_SIZE), desc="Embedding", leave=False):
                end = min(start + _BATCH_SIZE, total)
                self._collection.upsert(
                    documents=docs[start:end],
                    metadatas=metas[start:end],
                    ids=ids[start:end],
                )
                if progress_callback:
                    progress_callback(end, total)

    # ── Search ───────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = TOP_K,
        where: dict | None = None,
    ) -> list[dict]:
        count = self._collection.count()
        if count == 0:
            return []
        kwargs: dict = {
            "query_texts": [query],
            "n_results":   min(n_results, count),
        }
        if where:
            kwargs["where"] = where
        results = self._collection.query(**kwargs)
        return [
            {"document": doc, "metadata": meta, "distance": dist}
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]
