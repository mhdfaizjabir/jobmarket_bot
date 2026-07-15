"""
vector_store.py
---------------
Qdrant Cloud wrapper — uses requests (REST API) directly.
Avoids qdrant-client's httpcore dependency which has TLS issues on Windows.

Required in .env:
    QDRANT_URL=https://xxxx.us-east-2-0.aws.cloud.qdrant.io
    QDRANT_API_KEY=your-api-key

MANIFEST_VERSION: bump ONLY when document text format changes — forces full rebuild.
"""

import hashlib
import json
import os
import time
import uuid
import warnings
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from config import CHROMA_DIR, DESCRIPTION_TRUNCATE, EMBEDDING_MODEL, TOP_K, get_logger
from filter_registry import EXPLICIT_FILTER_COLUMNS
from observability import record_metric

load_dotenv()

logger = get_logger(__name__)

QDRANT_COLLECTION = "gulf_jobs"
MANIFEST_PATH     = CHROMA_DIR / "_manifest.json"
MANIFEST_VERSION  = 2
_BATCH_SIZE       = 256
_VECTOR_SIZE      = 384   # all-MiniLM-L6-v2 output dimension


# ---------------------------------------------------------------------------
# Minimal Qdrant REST client (requests-based, no httpcore)
# ---------------------------------------------------------------------------

class _QdrantREST:
    """Thin wrapper around Qdrant's REST API using requests."""

    def __init__(self, url: str, api_key: str):
        self._base = url.rstrip("/")
        self._s    = requests.Session()
        self._s.headers.update({"api-key": api_key, "Content-Type": "application/json"})

    def get_collections(self) -> list[str]:
        r = self._s.get(f"{self._base}/collections")
        r.raise_for_status()
        return [c["name"] for c in r.json()["result"]["collections"]]

    def create_collection(self, name: str):
        body = {"vectors": {"size": _VECTOR_SIZE, "distance": "Cosine"}}
        r = self._s.put(f"{self._base}/collections/{name}", json=body)
        r.raise_for_status()

    def delete_collection(self, name: str):
        r = self._s.delete(f"{self._base}/collections/{name}")
        # 404 is fine — collection may not exist yet
        if r.status_code != 404:
            r.raise_for_status()

    def count(self, name: str) -> int:
        r = self._s.get(f"{self._base}/collections/{name}")
        if r.status_code == 404:
            return 0
        r.raise_for_status()
        return r.json()["result"]["points_count"]

    def get_collection_info(self, name: str) -> dict:
        r = self._s.get(f"{self._base}/collections/{name}")
        r.raise_for_status()
        return r.json()["result"]

    def create_payload_index(
        self,
        name: str,
        field_name: str,
        field_type: str = "keyword",
        wait: bool = True,
    ) -> dict:
        body = {
            "field_name": field_name,
            "field_schema": {"type": field_type},
        }
        params = {"wait": str(wait).lower()} if wait is not None else {}
        r = self._s.put(
            f"{self._base}/collections/{name}/index",
            json=body,
            params=params,
        )
        r.raise_for_status()
        return r.json()["result"]

    def upsert(self, name: str, points: list[dict]):
        """points: list of {id, vector, payload}"""
        r = self._s.put(
            f"{self._base}/collections/{name}/points",
            json={"points": points},
        )
        r.raise_for_status()

    def search(
        self,
        name: str,
        vector: list[float],
        limit: int,
        filter_dict: dict | None = None,
    ) -> list[dict]:
        body: dict = {"vector": vector, "limit": limit, "with_payload": True}
        if filter_dict:
            body["filter"] = filter_dict
        r = self._s.post(f"{self._base}/collections/{name}/points/search", json=body)
        r.raise_for_status()
        return r.json()["result"]

    def scroll(
        self,
        name: str,
        limit: int = 500,
        offset: str | None = None,
        with_payload: bool = True,
    ) -> dict:
        """Paginate through all points in a collection (no vector similarity involved)."""
        body: dict = {"limit": limit, "with_payload": with_payload, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        r = self._s.post(f"{self._base}/collections/{name}/points/scroll", json=body)
        r.raise_for_status()
        return r.json()["result"]

    def set_payload(self, name: str, payload: dict, point_ids: list[str], wait: bool = True):
        """Merge `payload` into the existing payload of the given point ids (no re-embedding)."""
        body = {"payload": payload, "points": point_ids}
        params = {"wait": str(wait).lower()}
        r = self._s.post(f"{self._base}/collections/{name}/points/payload", json=body, params=params)
        r.raise_for_status()
        return r.json()["result"]


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
    return Path(path).name


# ---------------------------------------------------------------------------
# Document helpers (identical to previous version)
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

_BASE_META_COLS = [
    "job_title", "company", "category", "location",
    "career_level", "employment_type", "education",
    "salary", "_timeline", "_source_file", "_country",
    "_source", "_dump_id",
]

# Every registered explicit filter (sector today, more later) is captured into
# the payload automatically — no change needed here when a new one is added.
_META_COLS = list(dict.fromkeys(_BASE_META_COLS + sorted(EXPLICIT_FILTER_COLUMNS)))


def _build_doc_text(row: pd.Series) -> str:
    parts = []
    if "_country" in row.index and pd.notna(row["_country"]) and str(row["_country"]).strip():
        parts.append(f"Country: {row['_country']}")
    if "_timeline" in row.index and pd.notna(row["_timeline"]) and str(row["_timeline"]).strip():
        parts.append(f"Timeline: {row['_timeline']}")
    for col, label in _DOC_FIELDS:
        if col in row.index:
            val = row[col]
            if pd.notna(val) and str(val).strip():
                parts.append(f"{label}: {val}")
    for desc_col in ("description", "original_content"):
        if desc_col in row.index and pd.notna(row[desc_col]):
            parts.append(f"Description: {str(row[desc_col])[:DESCRIPTION_TRUNCATE]}")
            break
    # Arabic source text (merged from the AR portal file by job_id). Including it
    # makes each posting bilingual so Arabic queries retrieve the right job.
    if "_ar_content" in row.index and pd.notna(row["_ar_content"]) and str(row["_ar_content"]).strip():
        parts.append(f"النص الأصلي: {str(row['_ar_content'])[:DESCRIPTION_TRUNCATE]}")
    return "\n".join(parts)


def _build_metadata(row: pd.Series) -> dict:
    meta = {}
    for col in _META_COLS:
        if col in row.index and pd.notna(row[col]):
            meta[col] = str(row[col])
    return meta


def _make_row_id(row: pd.Series, idx: int) -> str:
    src = str(row.get("_source_file", "unknown"))
    jid = str(row.get("job_id", idx))
    return f"{src}::{jid}"


def _str_to_uuid(s: str) -> str:
    """Stable UUID from arbitrary string — Qdrant requires UUID or uint64 IDs."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, s))


# ---------------------------------------------------------------------------
# Filter conversion: ChromaDB where-clause → Qdrant REST filter dict
# ---------------------------------------------------------------------------

def _chroma_where_to_qdrant(where: dict | None) -> dict | None:
    """
    Convert ChromaDB-style where clause to Qdrant REST filter dict.
    Handles: {key: {"$eq": val}} and {"$and": [{key: {"$eq": val}}, ...]}
    """
    if not where:
        return None

    def _parse(d: dict) -> list[dict]:
        conditions: list[dict] = []
        for key, val in d.items():
            if key == "$and":
                for sub in val:
                    conditions.extend(_parse(sub))
            elif isinstance(val, dict):
                if "$eq" in val:
                    conditions.append({"key": key, "match": {"value": val["$eq"]}})
                elif "$in" in val:
                    # Qdrant: match any value in a list
                    conditions.append({"key": key, "match": {"any": val["$in"]}})
            else:
                conditions.append({"key": key, "match": {"value": val}})
        return conditions

    conditions = _parse(where)
    return {"must": conditions} if conditions else None


# ---------------------------------------------------------------------------
# VectorStore — same public interface as before
# ---------------------------------------------------------------------------

class VectorStore:
    def __init__(self):
        url     = os.getenv("QDRANT_URL", "")
        api_key = os.getenv("QDRANT_API_KEY", "")

        if not url or not api_key:
            raise ValueError(
                "QDRANT_URL and QDRANT_API_KEY must be set in .env\n"
                "Sign up free at https://cloud.qdrant.io — create a Free tier cluster."
            )

        self._client = _QdrantREST(url, api_key)
        self._model  = SentenceTransformer(EMBEDDING_MODEL)
        # First real .encode() call after load pays a one-time CPU thread-pool
        # / kernel warmup tax (observed ~15-20s on Windows) — pay it here, once,
        # at boot rather than on a random user's first chat message.
        self._model.encode("warm up", show_progress_bar=False)
        self._ensure_collection()
        self._count: int | None = None

    def _ensure_collection(self):
        existing = self._client.get_collections()
        if QDRANT_COLLECTION not in existing:
            self._client.create_collection(QDRANT_COLLECTION)

        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self):
        info = self._client.get_collection_info(QDRANT_COLLECTION)
        payload_schema = info.get("payload_schema", {}) or {}
        for field in {"_country", "_timeline", "career_level", "_dump_id", "_source"} | EXPLICIT_FILTER_COLUMNS:
            if field in payload_schema:
                continue
            try:
                self._client.create_payload_index(
                    QDRANT_COLLECTION,
                    field,
                    field_type="keyword",
                    wait=True,
                )
                logger.info("Created Qdrant payload index for %s", field)
            except Exception:
                logger.exception("Could not create Qdrant payload index for %s", field)

    # ── Status helpers ───────────────────────────────────────────────────────

    def count(self) -> int:
        if self._count is not None:
            return self._count
        try:
            self._count = self._client.count(QDRANT_COLLECTION)
            return self._count
        except Exception:
            logger.exception("Qdrant count() failed")
            return 0

    def has_vectors(self) -> bool:
        return self.count() > 0

    def needs_indexing(self, source_files: list[str]) -> bool:
        if self.count() == 0:
            return True
        manifest = _load_manifest()
        if manifest.get("version") != MANIFEST_VERSION:
            return True
        stored = manifest.get("files", {})
        return any(stored.get(_fname(f)) != _file_hash(f) for f in source_files)

    def new_files(self, source_files: list[str]) -> list[str]:
        if _load_manifest().get("version") != MANIFEST_VERSION:
            return source_files
        stored = _load_manifest().get("files", {})
        return [f for f in source_files if stored.get(_fname(f)) != _file_hash(f)]

    # ── Full rebuild ─────────────────────────────────────────────────────────

    def build_index(
        self,
        df: pd.DataFrame,
        source_files: list[str],
        progress_callback=None,
    ):
        """Full rebuild — deletes the Qdrant collection and re-embeds everything."""
        self._client.delete_collection(QDRANT_COLLECTION)
        self._ensure_collection()
        self._upsert_rows(df, progress_callback)
        self._count = self._client.count(QDRANT_COLLECTION)
        _save_manifest({_fname(f): _file_hash(f) for f in source_files})

    # ── Incremental (production default) ─────────────────────────────────────

    def build_index_incremental(
        self,
        df: pd.DataFrame,
        source_files: list[str],
        progress_callback=None,
    ) -> str:
        manifest = _load_manifest()
        if manifest.get("version") != MANIFEST_VERSION:
            self.build_index(df, source_files, progress_callback)
            return "Full rebuild complete (document format updated)."

        stored  = manifest.get("files", {})
        changed = [f for f in source_files if stored.get(_fname(f)) != _file_hash(f)]
        if not changed:
            return "Index already up to date — nothing to do."

        changed_names = {Path(f).name for f in changed}
        new_rows = (
            df[df["_source_file"].isin(changed_names)]
            if "_source_file" in df.columns
            else df
        )

        logger.info("Incremental index: embedding %s rows from %s file(s)...", f"{len(new_rows):,}", len(changed))
        self._upsert_rows(new_rows, progress_callback)
        self._count = self._client.count(QDRANT_COLLECTION)

        updated = {**stored, **{_fname(f): _file_hash(f) for f in changed}}
        _save_manifest(updated)
        return f"Incremental update: {len(new_rows):,} rows from {len(changed)} file(s) added."

    # ── Internal ─────────────────────────────────────────────────────────────

    def _upsert_rows(self, df: pd.DataFrame, progress_callback=None):
        """Embed rows and upsert to Qdrant in batches."""
        texts, metadatas, str_ids = [], [], []
        for i, (_, row) in enumerate(df.iterrows()):
            text = _build_doc_text(row)
            meta = _build_metadata(row)
            meta["_doc_text"] = text
            texts.append(text)
            metadatas.append(meta)
            str_ids.append(_make_row_id(row, i))

        total = len(texts)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for start in tqdm(range(0, total, _BATCH_SIZE), desc="Embedding", leave=False):
                end     = min(start + _BATCH_SIZE, total)
                vectors = self._model.encode(
                    texts[start:end], show_progress_bar=False
                ).tolist()
                points  = [
                    {"id": _str_to_uuid(sid), "vector": vec, "payload": meta}
                    for sid, vec, meta in zip(
                        str_ids[start:end], vectors, metadatas[start:end]
                    )
                ]
                self._client.upsert(QDRANT_COLLECTION, points)
                if progress_callback:
                    progress_callback(end, total)

    # ── Search ───────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = TOP_K,
        where: dict | None = None,
    ) -> list[dict]:
        if not self.has_vectors():
            return []

        t0 = time.perf_counter()
        query_vector  = self._model.encode(query).tolist()
        record_metric("embedding_duration_ms", (time.perf_counter() - t0) * 1000)

        qdrant_filter = _chroma_where_to_qdrant(where)

        t1 = time.perf_counter()
        results = self._client.search(
            QDRANT_COLLECTION,
            vector=query_vector,
            limit=n_results,
            filter_dict=qdrant_filter,
        )
        record_metric("qdrant_search_duration_ms", (time.perf_counter() - t1) * 1000)

        return [
            {
                "document": r["payload"].get("_doc_text", ""),
                "metadata": {k: v for k, v in r["payload"].items() if k != "_doc_text"},
                "distance": 1 - r["score"],   # cosine score → distance
            }
            for r in results
        ]
