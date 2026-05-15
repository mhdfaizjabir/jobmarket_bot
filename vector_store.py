"""
vector_store.py
---------------
ChromaDB wrapper for building and querying the semantic index.

A manifest file (chroma_db/_manifest.json) tracks which source files
have been indexed (by MD5 hash).  needs_indexing() returns True whenever
a file is new, modified, or not yet indexed at all.

Adding a new dataset file:  call build_index() once → manifest updates.
Changing document text format: bump MANIFEST_VERSION to force a rebuild.
"""

import json
import hashlib
import warnings

import chromadb
import pandas as pd
from chromadb.utils import embedding_functions
from pathlib import Path
from tqdm import tqdm

from config import (
    CHROMA_DIR,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    DESCRIPTION_TRUNCATE,
    TOP_K,
)

MANIFEST_PATH = CHROMA_DIR / "_manifest.json"
MANIFEST_VERSION = 1  # bump this to force a full rebuild
_BATCH_SIZE = 128


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
    data = {"version": MANIFEST_VERSION, "files": file_hashes}
    MANIFEST_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _file_hash(path: str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

# Fields included in the embedded text, in display order
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

# Metadata columns stored in ChromaDB (used for filtered queries)
_META_COLS = [
    "job_title", "company", "category", "location",
    "career_level", "employment_type", "education",
    "salary", "_timeline", "_source_file",
]


def _build_doc_text(row: pd.Series) -> str:
    parts = []
    for col, label in _DOC_FIELDS:
        if col in row.index:
            val = row[col]
            if pd.notna(val) and str(val).strip():
                parts.append(f"{label}: {val}")

    # Truncated description (if present)
    for desc_col in ("description", "original_content"):
        if desc_col in row.index and pd.notna(row[desc_col]):
            desc = str(row[desc_col])[:DESCRIPTION_TRUNCATE]
            parts.append(f"Description: {desc}")
            break

    if "_timeline" in row.index and pd.notna(row["_timeline"]):
        parts.append(f"Timeline: {row['_timeline']}")

    return "\n".join(parts)


def _build_metadata(row: pd.Series) -> dict:
    """ChromaDB metadata must be str/int/float/bool — no None/NaN."""
    meta = {}
    for col in _META_COLS:
        if col in row.index and pd.notna(row[col]):
            meta[col] = str(row[col])
    return meta


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

    # ── public API ───────────────────────────────────────────────────────────

    def count(self) -> int:
        return self._collection.count()

    def needs_indexing(self, source_files: list[str]) -> bool:
        """True when the index is missing, empty, or any source file has changed."""
        if self._collection.count() == 0:
            return True
        manifest = _load_manifest()
        if manifest.get("version") != MANIFEST_VERSION:
            return True
        stored = manifest.get("files", {})
        for f in source_files:
            if stored.get(f) != _file_hash(f):
                return True
        return False

    def build_index(
        self,
        df: pd.DataFrame,
        source_files: list[str],
        progress_callback=None,
    ):
        """
        (Re)build the entire ChromaDB collection from *df*.

        progress_callback(done: int, total: int) is called after each batch
        if provided (useful for Streamlit progress bars).
        """
        # Wipe and recreate the collection
        try:
            self._client.delete_collection(CHROMA_COLLECTION)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=self._ef,
        )

        # Build parallel lists
        docs, metas, ids = [], [], []
        for i, (_, row) in enumerate(df.iterrows()):
            docs.append(_build_doc_text(row))
            metas.append(_build_metadata(row))
            ids.append(str(i))

        total = len(docs)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for start in tqdm(range(0, total, _BATCH_SIZE), desc="Indexing", leave=False):
                end = min(start + _BATCH_SIZE, total)
                self._collection.add(
                    documents=docs[start:end],
                    metadatas=metas[start:end],
                    ids=ids[start:end],
                )
                if progress_callback:
                    progress_callback(end, total)

        _save_manifest({f: _file_hash(f) for f in source_files})

    def search(
        self,
        query: str,
        n_results: int = TOP_K,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Semantic search.  Returns a list of dicts:
          {document, metadata, distance}
        """
        count = self._collection.count()
        if count == 0:
            return []

        kwargs: dict = {
            "query_texts": [query],
            "n_results": min(n_results, count),
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
