"""
server.py — FastAPI backend for GCC Job Market Intelligence
-----------------------------------------------------------
Run:  uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
  GET  /health              — health + index status
  GET  /api/datasets        — all dataset dumps with job counts
  GET  /api/dashboard       — aggregated analytics (filtered)
  POST /api/chat            — streaming SSE chat (RAG pipeline)
  POST /api/session         — create new session, returns session_id
  DELETE /api/session/{id}  — clear chat history for a session

TODO(structure, sprint 5+): this file mixes route handlers, the dashboard's
pandas-aggregation logic, and cross-cutting concerns (middleware, error
handlers) in one ~700-line module. Once there's a reason to touch these
independently, split into:
  - middleware/logging.py  <- _request_logging_middleware + the exception
                              handlers (_http_exception_handler etc.)
  - routers/dashboard.py    <- get_dashboard() — it alone is ~230 lines of
                              pandas aggregation that has nothing to do with
                              chat/session routing
  - routers/chat.py         <- chat(), _sse_stream(), the session endpoints
Not done now — nothing here is broken and the file still reads top-to-bottom
in request-handling order, which has real value while the route count is small.
"""

import asyncio
import io
import json
import re
import threading
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

from config import (
    ALLOWED_ORIGINS,
    APP_VERSION,
    AVAILABLE_MODELS,
    DATA_DIR,
    ENVIRONMENT,
    get_logger,
    set_request_id,
    set_session_id,
)
from data_loader import (
    load_all, parse_file_info, sort_timelines,
    parse_salary_mid, SALARY_BUCKET_BINS, SALARY_BUCKET_LABELS,
)
from filter_registry import translate_explicit_filters
from vector_store import VectorStore
from analytics import AnalyticsEngine
from rag_engine import RAGEngine
from retrieval import warm_up_reranker
from session import SessionStore
from observability import (
    capture_exception,
    increment_counter,
    init_observability,
    record_metric,
    render_prometheus,
    set_gauge_sources,
)
from security import (
    IDENTIFIER_PATTERN,
    MAX_DUMP_ID_LEN,
    MAX_DUMP_IDS,
    MAX_FILTER_KEY_LEN,
    MAX_FILTER_VALUE_LEN,
    MAX_FILTERS,
    MAX_MODEL_LEN,
    MAX_REQUEST_BYTES,
    MAX_SESSION_ID_LEN,
    apply_security_headers,
    enforce_environment,
)

logger = get_logger(__name__)

_IDENTIFIER_RE = re.compile(IDENTIFIER_PATTERN)


# ---------------------------------------------------------------------------
# App state — loaded once at startup, shared across all requests
# ---------------------------------------------------------------------------

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading data and initialising engines... (environment=%s, version=%s)", ENVIRONMENT, APP_VERSION)

    # Fail fast on a misconfigured production deploy before spending ~20s loading
    # models; in development this only logs warnings and continues.
    enforce_environment()

    source_files = sorted(
        str(p) for p in (list(DATA_DIR.glob("*.xlsx")) + list(DATA_DIR.glob("*.csv")))
        if not p.name.startswith("~$") and not parse_file_info(p)["is_ar"]
    )
    df, timelines = load_all(DATA_DIR)

    vs      = VectorStore()
    engine  = RAGEngine(AnalyticsEngine(df), vs)
    sessions = SessionStore()

    # Pay the reranker's one-time model-load cost here, not on a random
    # user's first chat message (same rationale as VectorStore's embedding
    # model above — both are eager-loaded exactly once at boot).
    warm_up_reranker()

    _state.update({
        "df":           df,
        "timelines":    timelines,
        "source_files": source_files,
        "vs":           vs,
        "engine":       engine,
        "sessions":     sessions,
        "started_at":   time.time(),
    })

    # Background cleanup thread — removes stale sessions every 30 min
    def _cleanup_loop():
        while True:
            time.sleep(1800)
            n = sessions.cleanup()
            if n:
                logger.info("Session cleanup: removed %d expired sessions", n)

    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.start()

    # Activate whichever observability backends have credentials (Sentry/Langfuse)
    # in the background — NOT awaited here. sentry_sdk.init() has been observed
    # to block for 1-2 minutes on some Windows setups (its HTTP transport does
    # proxy auto-detection via the Windows registry/WPAD, independent of actual
    # network reachability — confirmed via direct connectivity test taking
    # ~1.5s while sentry_sdk.init() alone took ~117s). The whole API being
    # unreachable for two minutes on every boot is a far worse tradeoff than
    # Sentry/Langfuse activating a little late; error tracking already
    # degrades to log-only until `_sentry_active` flips true, same as if the
    # DSN were never set.
    threading.Thread(target=init_observability, daemon=True).start()
    set_gauge_sources(
        memory_mb=_memory_mb,
        active_sessions=lambda: sessions.stats()["active_sessions"],
    )

    logger.info("Ready — %s postings | %s vectors in Qdrant", f"{len(df):,}", f"{vs.count():,}")
    yield


# ---------------------------------------------------------------------------
# FastAPI app + rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="GCC Job Market Intelligence API",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter


def _error_body(request: Request, error: str, message: str) -> dict:
    return {
        "success": False,
        "error": error,
        "message": message,
        "request_id": getattr(request.state, "request_id", "-"),
    }


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=_error_body(request, "rate_limited", "Too many requests — please slow down."),
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(request, "http_error", str(exc.detail)),
        headers=getattr(exc, "headers", None) or {},
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body(request, "validation_error", "Request body did not match the expected schema."),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full detail (including traceback) goes to the log only — never to the client.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    capture_exception(exc, path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content=_error_body(request, "internal_error", "Something went wrong. Please try again."),
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
# Registered against the Starlette base class (not fastapi.HTTPException) so
# this also catches routing-level exceptions like 404 — FastAPI's HTTPException
# is a subclass, so it's matched too via the normal MRO exception-handler lookup.
app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
app.add_exception_handler(RequestValidationError, _validation_exception_handler)
app.add_exception_handler(Exception, _unhandled_exception_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def _request_logging_middleware(request: Request, call_next):
    """
    Cross-cutting request handling in one place:
      - assigns a request id (X-Request-ID header + error bodies)
      - rejects over-sized bodies early (413) before they're read
      - applies security headers to every response (success or error)
      - logs one line per request (method, path, status, duration)

    Also the seam where a future APM/tracing integration (OpenTelemetry, etc.)
    attaches without touching individual route handlers.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    set_request_id(request_id)

    # Reject over-sized bodies up front. Declared Content-Length is the cheap
    # check; the field-level limits + streaming aren't relied on for this.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                resp = JSONResponse(
                    status_code=413,
                    content=_error_body(request, "payload_too_large",
                                        "Request body is too large."),
                )
                apply_security_headers(resp)
                resp.headers["X-Request-ID"] = request_id
                return resp
        except ValueError:
            pass  # malformed Content-Length — let downstream parsing 400/422 it

    # Best-effort: peek the body for a session_id so the access-log line below
    # can correlate to it too. Starlette caches the raw body after this read,
    # so the route handler's own JSON parsing downstream is unaffected.
    # NOTE(sprint 4+): this only covers the middleware's own log line — the
    # request handler still calls set_session_id() itself for logs emitted
    # from deeper in the call stack (rag_engine, sql_engine), because those
    # run via run_in_executor()/a raw Thread, which do NOT inherit contextvars
    # from the request task automatically (a real gap — fixing it needs
    # asyncio.to_thread or an explicit contextvars.copy_context().run(...)
    # wrapper around the executor/thread calls, left for a later sprint).
    if request.method == "POST" and request.url.path == "/api/chat":
        try:
            payload = json.loads(await request.body())
            session_id = payload.get("session_id")
            if session_id:
                set_session_id(session_id)
        except Exception:
            pass

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Full traceback is logged once by _unhandled_exception_handler (the
        # registered Exception handler) — this is just the access-log line.
        duration_ms = (time.perf_counter() - start) * 1000
        logger.warning(
            "%s %s -> 500 (unhandled)", request.method, request.url.path,
            extra={"duration_ms": duration_ms},
        )
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d", request.method, request.url.path, response.status_code,
        extra={"duration_ms": duration_ms},
    )
    record_metric("http_request_duration_ms", duration_ms, path=request.url.path, status=response.status_code)
    apply_security_headers(response)
    response.headers["X-Request-ID"] = request_id
    return response


# CORS audit (Sprint 5): origins come from ALLOWED_ORIGINS (never "*"); methods
# and headers are narrowed to what the frontend actually uses rather than "*".
# No cookies are used by the API (session_id travels in the JSON body), so
# allow_credentials is not required for auth today — kept False, which also
# keeps the CORS contract strict. X-Request-ID is exposed so the browser can
# read it for support/debugging.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    # question length is enforced with a friendly message in the handler (and
    # bounded hard by the 64 KB body-size cap); the other fields are validated
    # here so malformed input is rejected at the schema boundary — before it
    # can reach the SQL / Qdrant layers that interpolate ids and filters.
    question:   str
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LEN, pattern=IDENTIFIER_PATTERN)
    model:      str = Field(default="fanar/Fanar-C-2-27B", max_length=MAX_MODEL_LEN)
    dump_ids:   list[str] = Field(default=[], max_length=MAX_DUMP_IDS)
    filters:    dict[str, str] = Field(default={})

    @field_validator("dump_ids")
    @classmethod
    def _validate_dump_ids(cls, v: list[str]) -> list[str]:
        for d in v:
            if not isinstance(d, str) or len(d) > MAX_DUMP_ID_LEN or not _IDENTIFIER_RE.match(d):
                raise ValueError("dump_ids must be short alphanumeric identifiers")
        return v

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > MAX_FILTERS:
            raise ValueError(f"too many filters (max {MAX_FILTERS})")
        for key, value in v.items():
            if len(key) > MAX_FILTER_KEY_LEN or not _IDENTIFIER_RE.match(key):
                raise ValueError("filter keys must be short alphanumeric identifiers")
            if not isinstance(value, str) or len(value) > MAX_FILTER_VALUE_LEN:
                raise ValueError(f"filter values must be strings under {MAX_FILTER_VALUE_LEN} chars")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_by_dumps(df, dump_ids: list[str]):
    if not dump_ids or "_dump_id" not in df.columns:
        return df
    return df[df["_dump_id"].isin(dump_ids)]


def _scope_plot_df(dumps: str, country: str, timeline: str, explicit_active: dict) -> pd.DataFrame:
    """Apply dump/country/timeline/explicit-filter scoping — shared by /api/dashboard and its export."""
    df = _state["df"]
    dump_ids = [d for d in dumps.split(",") if d]
    plot_df = _filter_by_dumps(df, dump_ids) if dump_ids else df
    if country != "All" and "_country" in plot_df.columns:
        plot_df = plot_df[plot_df["_country"] == country]
    if timeline != "All" and "_timeline" in plot_df.columns:
        plot_df = plot_df[plot_df["_timeline"] == timeline]
    for column, value in translate_explicit_filters(explicit_active).items():
        if column in plot_df.columns:
            plot_df = plot_df[plot_df[column].astype(str).str.lower() == str(value).lower()]
    return plot_df


_AR_TO_EN_CITY: dict[str, str] = {
    "قطر": "Qatar", "الدوحة": "Doha", "الدوهة": "Doha", "دوحة": "Doha",
    "دبي": "Dubai", "أبوظبي": "Abu Dhabi", "أبو ظبي": "Abu Dhabi",
    "الرياض": "Riyadh", "رياض": "Riyadh", "جدة": "Jeddah",
    "المنامة": "Manama", "الكويت": "Kuwait City", "مسقط": "Muscat",
    "الشارقة": "Sharjah", "عجمان": "Ajman", "مكة": "Mecca",
}

def _extract_city(loc) -> str:
    if pd.isna(loc):
        return "Unknown"
    s = str(loc).strip()
    for sep in ["·", ","]:
        if sep in s:
            city = s.split(sep)[0].strip()
            if city and len(city) > 1:
                s = city
                break
    s = s[:35]
    return _AR_TO_EN_CITY.get(s, s)


_SIZE_BUCKETS = [
    (50,    "1–50"),
    (200,   "51–200"),
    (500,   "201–500"),
    (1_000, "501–1,000"),
    (5_000, "1,001–5,000"),
    (10_000,"5,001–10,000"),
    (50_000,"10,001–50,000"),
]
_SIZE_FALLBACK = "50,000+"

def _normalise_company_size(val) -> str | None:
    if pd.isna(val) or not str(val).strip():
        return None
    nums = re.findall(r"[\d,]+", str(val))
    ints = []
    for n in nums:
        cleaned = n.replace(",", "")
        if cleaned.isdigit():
            ints.append(int(cleaned))
    if not ints:
        return None
    top = max(ints)
    for threshold, label in _SIZE_BUCKETS:
        if top <= threshold:
            return label
    return _SIZE_FALLBACK


_MAX_QUESTION_LEN = 2000


async def _sse_stream(
    engine: RAGEngine,
    question: str,
    history: list[dict],
    model: str,
    dump_ids: list[str] | None = None,
    prepared: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Run the sync RAGEngine.answer() generator in a thread and yield SSE token events.
    Uses asyncio.Queue to bridge the sync generator and async world safely.
    """
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _run():
        try:
            for token in engine.answer(question, history, model=model, dump_ids=dump_ids, prepared=prepared):
                loop.call_soon_threadsafe(q.put_nowait, token)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, f"\n\n[Error: {e}]")
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    while True:
        token = await q.get()
        if token is None:
            yield "data: [DONE]\n\n"
            break
        yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"

    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _memory_mb() -> float | None:
    """Best-effort RSS memory in MB — psutil is cheap but optional; never fails health."""
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return None


@app.get("/health")
def health():
    vs: VectorStore | None = _state.get("vs")
    qdrant_status = "not_initialized"
    vector_count = 0
    if vs is not None:
        try:
            vector_count = vs.count()
            qdrant_status = "ok" if vector_count > 0 else "empty"
        except Exception:
            logger.exception("Qdrant health check failed")
            qdrant_status = "error"

    return {
        "status":            "ok",
        "environment":       ENVIRONMENT,
        "version":           APP_VERSION,
        "uptime_s":          round(time.time() - _state.get("started_at", time.time())),
        "postings":          len(_state.get("df", [])),
        "vectors":           vector_count,
        "qdrant_status":     qdrant_status,
        "model_configured":  next(iter(AVAILABLE_MODELS.values()), None),
        "models_available":  len(AVAILABLE_MODELS),
        "sessions":          _state["sessions"].stats() if "sessions" in _state else {},
        "memory_mb":         _memory_mb(),
    }


@app.get("/metrics")
def metrics():
    """
    Prometheus text exposition. NOTE: nginx blocks external access to this
    path in the production config — it's meant for the internal scraper only
    (see nginx/nginx.conf and OBSERVABILITY.md).
    """
    return Response(content=render_prometheus(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/session")
def create_session():
    """Create a new chat session. Frontend calls this on mount."""
    sid = _state["sessions"].create()
    return {"session_id": sid}


@app.delete("/api/session/{session_id}")
def clear_session(session_id: str):
    """Clear chat history for a session (user clicks 'Clear chat')."""
    _state["sessions"].clear(session_id)
    return {"ok": True}


@app.get("/api/datasets")
def get_datasets():
    """Return all dataset dumps with job counts — drives the sidebar selector."""
    df = _state["df"]
    if "_dump_id" not in df.columns:
        return {"dumps": []}

    group_cols = ["_dump_id", "_country", "_timeline", "_dump_label"]
    if "_source" in df.columns:
        group_cols.append("_source")
    groups = (
        df.groupby(group_cols)
        .size()
        .reset_index(name="count")
    )
    dumps = groups.to_dict("records")
    dumps.sort(key=lambda d: (d.get("_source", ""), d["_country"], d["_timeline"]))
    sources = sorted(df["_source"].dropna().unique().tolist()) if "_source" in df.columns else []
    return {"dumps": dumps, "timelines": _state["timelines"], "sources": sources}


@app.get("/api/models")
def get_models():
    """Return available LLM models so the frontend stays in sync with config."""
    return {
        "models": [
            {"label": label, "value": value}
            for label, value in AVAILABLE_MODELS.items()
        ],
        "default": next(iter(AVAILABLE_MODELS.values())),
    }


# In-process TTL cache for dashboard responses. The dataset only changes on
# restart, so identical filter combinations always produce identical charts —
# recomputing ~15 pandas aggregations (including a salary-regex pass over the
# whole frame) per request is pure waste. Bounded size + TTL keep memory flat.
_DASH_CACHE_TTL_S = 600
_DASH_CACHE_MAX   = 256
_dash_cache: dict[tuple, tuple[float, dict]] = {}
_dash_cache_lock = threading.Lock()


def _dash_cache_store(key: tuple, resp: dict) -> None:
    """Insert into the dashboard cache, evicting the oldest entry at capacity."""
    with _dash_cache_lock:
        if len(_dash_cache) >= _DASH_CACHE_MAX:
            oldest = min(_dash_cache, key=lambda k: _dash_cache[k][0])
            del _dash_cache[oldest]
        _dash_cache[key] = (time.time(), resp)


@app.get("/api/dashboard")
def get_dashboard(
    dumps:    str = "",
    country:  str = "All",
    sector:   str = "All",
    timeline: str = "All",
    employment_type: str = "All",
    career_level:    str = "All",
    company:         str = "All",
    experience:      str = "All",
    salary_bucket:   str = "All",
    n_sectors:  int = 15,
    n_skills:   int = 20,
    n_titles:   int = 20,
    n_companies: int = 15,
):
    """
    Return all chart data for the dashboard in one call.
    Frontend passes active dump_ids as comma-separated string.

    Every field in filter_registry.py gets one named query param here (kept
    named rather than a generic blob for a debuggable REST querystring — see
    PROJECT_SPEC.md Sprint 2 log) but all of them are applied to plot_df through
    one generic loop below, translated via the same translate_explicit_filters()
    the chat pipeline uses — adding a new registry entry needs one new param
    line here, not a new filtering branch.
    """
    explicit_raw = {
        "sector": sector, "employment_type": employment_type, "career_level": career_level,
        "company": company, "experience": experience, "salary_bucket": salary_bucket,
    }
    explicit_active = {k: v for k, v in explicit_raw.items() if v and v != "All"}

    cache_key = (dumps, country, timeline, tuple(sorted(explicit_active.items())),
                 n_sectors, n_skills, n_titles, n_companies)
    now = time.time()
    with _dash_cache_lock:
        hit = _dash_cache.get(cache_key)
        if hit and now - hit[0] < _DASH_CACHE_TTL_S:
            increment_counter("dashboard_cache", result="hit")
            return hit[1]
    increment_counter("dashboard_cache", result="miss")

    plot_df = _scope_plot_df(dumps, country, timeline, explicit_active)

    sec_col = "_sector_norm" if "_sector_norm" in plot_df.columns else "category"
    car_col = "_career_norm" if "_career_norm" in plot_df.columns else "career_level"
    emp_col = "_employment_norm" if "_employment_norm" in plot_df.columns else "employment_type"

    if plot_df.empty:
        empty_resp = {"error": "No data for selected filters"}
        _dash_cache_store(cache_key, empty_resp)
        return empty_resp

    total      = len(plot_df)
    timelines  = sort_timelines(plot_df["_timeline"].dropna().unique().tolist()) if "_timeline" in plot_df.columns else []
    countries  = sorted(plot_df["_country"].dropna().unique().tolist()) if "_country" in plot_df.columns else []

    # ── Sectors ───────────────────────────────────────────────────────────────
    sectors_data: list[dict] = []
    if sec_col in plot_df.columns:
        active_tl = sort_timelines(plot_df["_timeline"].dropna().unique().tolist()) if "_timeline" in plot_df.columns else []
        if len(active_tl) > 1:
            grp = plot_df.groupby([sec_col, "_timeline"]).size().reset_index(name="count")
            top = grp.groupby(sec_col)["count"].sum().nlargest(n_sectors).index
            grp = grp[grp[sec_col].isin(top)]
            sectors_data = grp.rename(columns={sec_col: "sector"}).to_dict("records")
        else:
            sc = plot_df[sec_col].value_counts().head(n_sectors).reset_index()
            sc.columns = ["sector", "count"]
            sectors_data = sc.to_dict("records")

    # ── Career level + Employment type ────────────────────────────────────────
    career_data = []
    if car_col in plot_df.columns:
        cl = plot_df[car_col].dropna().value_counts().reset_index()
        cl.columns = ["level", "count"]
        career_data = cl.to_dict("records")

    employment_data = []
    if emp_col in plot_df.columns:
        et = plot_df[emp_col].dropna().value_counts().reset_index()
        et.columns = ["type", "count"]
        employment_data = et.to_dict("records")

    # ── Salary ────────────────────────────────────────────────────────────────
    salary_data: dict = {"coverage_pct": 0, "n_disclosed": 0, "avg_usd": None, "distribution": [], "by_sector": []}
    if "salary" in plot_df.columns:
        tmp = plot_df.copy()
        tmp["_mid"] = tmp["salary"].apply(parse_salary_mid)
        sal_df = tmp[tmp["_mid"].notna()]
        n_sal  = len(sal_df)
        salary_data = {
            "coverage_pct": round(n_sal / total * 100, 1),
            "n_disclosed":  n_sal,
            "avg_usd":      round(sal_df["_mid"].mean(), 0) if n_sal > 0 else None,
            "distribution": [],
            "by_sector":    [],
        }
        if n_sal > 0:
            bins, labels = SALARY_BUCKET_BINS, SALARY_BUCKET_LABELS
            sal_df = sal_df.copy()
            sal_df["bracket"] = pd.cut(sal_df["_mid"], bins=bins, labels=labels, right=False)
            bkt = sal_df["bracket"].value_counts().reindex(labels).fillna(0).reset_index()
            bkt.columns = ["bracket", "count"]
            salary_data["distribution"] = bkt.to_dict("records")

            if sec_col in sal_df.columns:
                grp = (
                    sal_df.groupby(sec_col)["_mid"]
                    .agg(avg="mean", count="count")
                    .query("count >= 3")
                    .sort_values("avg", ascending=False)
                    .head(15)
                    .reset_index()
                )
                grp.columns = ["sector", "avg_usd", "count"]
                grp["avg_usd"] = grp["avg_usd"].round(0)
                salary_data["by_sector"] = grp.to_dict("records")

    # ── Skills ────────────────────────────────────────────────────────────────
    skills_data: list[dict] = []
    if "skills" in plot_df.columns:
        bag: Counter = Counter()
        for s in plot_df["skills"].dropna():
            for sk in re.split(r"[;,|\n/]+", str(s)):
                sk = sk.strip().lower()
                if 1 < len(sk) < 60:
                    bag[sk] += 1
        skills_data = [
            {"skill": sk, "count": cnt, "pct": round(cnt / total * 100, 1)}
            for sk, cnt in bag.most_common(n_skills)
        ]

    # ── Experience + Company size ─────────────────────────────────────────────
    experience_data: list[dict] = []
    if "experience" in plot_df.columns:
        exp = plot_df["experience"].dropna().value_counts().head(15).reset_index()
        exp.columns = ["experience", "count"]
        experience_data = exp.to_dict("records")

    company_size_data: list[dict] = []
    if "company_size" in plot_df.columns:
        buckets = plot_df["company_size"].apply(_normalise_company_size).dropna()
        if not buckets.empty:
            sz = buckets.value_counts().reset_index()
            sz.columns = ["size", "count"]
            order = [l for _, l in _SIZE_BUCKETS] + [_SIZE_FALLBACK]
            sz["_ord"] = sz["size"].apply(lambda x: order.index(x) if x in order else 99)
            sz = sz.sort_values("_ord").drop(columns="_ord")
            company_size_data = sz.to_dict("records")

    # ── Language + Location ───────────────────────────────────────────────────
    language_data: list[dict] = []
    if "language" in plot_df.columns:
        lang = (
            plot_df["language"].dropna()
            .loc[lambda s: s.str.strip() != ""]
            .value_counts().head(8).reset_index()
        )
        lang.columns = ["language", "count"]
        language_data = lang.to_dict("records")

    location_data: list[dict] = []
    if "location" in plot_df.columns:
        city_series = plot_df["location"].apply(_extract_city)
        city = city_series.value_counts().head(10).reset_index()
        city.columns = ["city", "count"]
        location_data = city.to_dict("records")

    # ── Job titles ────────────────────────────────────────────────────────────
    titles_data: list[dict] = []
    if "job_title" in plot_df.columns:
        t = plot_df["job_title"].dropna().value_counts().head(n_titles).reset_index()
        t.columns = ["title", "count"]
        titles_data = t.to_dict("records")

    # ── Companies ─────────────────────────────────────────────────────────────
    companies_data: list[dict] = []
    if "company" in plot_df.columns:
        co = plot_df["company"].value_counts().head(n_companies).reset_index()
        co.columns = ["company", "count"]
        companies_data = co.to_dict("records")

    # ── Country comparison ────────────────────────────────────────────────────
    country_data: list[dict] = []
    if "_country" in plot_df.columns and len(countries) > 1:
        vol = plot_df["_country"].value_counts().reset_index()
        vol.columns = ["country", "count"]
        country_data = vol.to_dict("records")

    # ── Trend (month-over-month) ──────────────────────────────────────────────
    trend_data = None
    if len(timelines) >= 2 and sec_col in plot_df.columns:
        t1, t2 = timelines[0], timelines[-1]
        sub1 = plot_df[plot_df["_timeline"] == t1]
        sub2 = plot_df[plot_df["_timeline"] == t2]
        n1, n2 = max(len(sub1), 1), max(len(sub2), 1)
        c1 = sub1[sec_col].value_counts()
        c2 = sub2[sec_col].value_counts()
        rows = []
        for sec in set(c1.index) | set(c2.index):
            r1 = c1.get(sec, 0) / n1
            r2 = c2.get(sec, 0) / n2
            if r1 > 0.005:
                pct = (r2 - r1) / r1 * 100
                rows.append({"sector": sec, "count_t1": int(c1.get(sec,0)),
                              "count_t2": int(c2.get(sec,0)), "pct_change": round(pct, 1)})
        rows.sort(key=lambda x: -x["pct_change"])
        trend_data = {
            "t1": t1, "t2": t2, "n1": n1, "n2": n2,
            "overall_pct": round((n2 - n1) / n1 * 100, 1),
            "growing":   [r for r in rows if r["pct_change"] > 0][:5],
            "declining": [r for r in rows if r["pct_change"] < 0][:5],
        }

    # ── KPIs ──────────────────────────────────────────────────────────────────
    kpi_mom = None
    if len(timelines) >= 2:
        t1, t2 = timelines[0], timelines[-1]
        counts = plot_df["_timeline"].value_counts() if "_timeline" in plot_df.columns else {}
        c1 = int(counts.get(t1, 0))
        c2 = int(counts.get(t2, 0))
        kpi_mom = {"t1": t1, "t2": t2, "c1": c1, "c2": c2,
                   "pct": round((c2 - c1) / c1 * 100, 1) if c1 > 0 else 0}

    resp = {
        "total":          total,
        "countries":      countries,
        "timelines":      timelines,
        "kpi_mom":        kpi_mom,
        "sectors":        sectors_data,
        "career_levels":  career_data,
        "employment_types": employment_data,
        "salary":         salary_data,
        "skills":         skills_data,
        "experience":     experience_data,
        "company_size":   company_size_data,
        "languages":      language_data,
        "locations":      location_data,
        "job_titles":     titles_data,
        "companies":      companies_data,
        "country_comparison": country_data,
        "trends":         trend_data,
    }
    _dash_cache_store(cache_key, resp)
    return resp


# Chart key (matches the frontend's download button) -> (xlsx sheet title,
# extractor pulling that chart's rows out of get_dashboard()'s response).
# "trends" is deliberately excluded — its growing/declining split doesn't fit
# this single-sheet-of-rows shape.
_EXPORT_CHARTS: dict[str, tuple[str, Callable[[dict], list]]] = {
    "sectors":             ("Postings by Sector",       lambda r: r["sectors"]),
    "career_levels":       ("Career Level",              lambda r: r["career_levels"]),
    "employment_types":    ("Employment Type",           lambda r: r["employment_types"]),
    "salary_distribution": ("Salary Brackets",           lambda r: r["salary"]["distribution"]),
    "salary_by_sector":    ("Avg Salary by Sector",      lambda r: r["salary"]["by_sector"]),
    "skills":              ("Top Skills",                lambda r: r["skills"]),
    "job_titles":          ("Most Advertised Positions", lambda r: r["job_titles"]),
    "companies":           ("Top Hiring Companies",      lambda r: r["companies"]),
    "experience":          ("Experience Required",       lambda r: r["experience"]),
    "company_size":        ("Company Size",              lambda r: r["company_size"]),
    "languages":           ("Language Requirements",     lambda r: r["languages"]),
    "locations":           ("Top Locations",             lambda r: r["locations"]),
    "country_comparison":  ("Volume by Country",         lambda r: r["country_comparison"]),
}

# Raw posting columns included in the export's "Job Postings" sheet — same
# canonical names as config/settings.py's COLUMN_ALIASES, plus the internal
# _country/_timeline/_source fields. (col, header) pairs, in output order.
_EXPORT_POSTING_COLUMNS: list[tuple[str, str]] = [
    ("job_title", "Job Title"), ("company", "Company"), ("_country", "Country"),
    ("location", "Location"), ("category", "Sector"), ("career_level", "Career Level"),
    ("employment_type", "Employment Type"), ("experience", "Experience"),
    ("salary", "Salary"), ("education", "Education"), ("language", "Language"),
    ("skills", "Skills"), ("post_date", "Posted"), ("_timeline", "Timeline"),
    ("_source", "Source"), ("url", "URL"),
]


@app.get("/api/dashboard/export")
def export_dashboard_chart(
    chart:    str,
    dumps:    str = "",
    country:  str = "All",
    sector:   str = "All",
    timeline: str = "All",
    employment_type: str = "All",
    career_level:    str = "All",
    company:         str = "All",
    experience:      str = "All",
    salary_bucket:   str = "All",
    n_sectors:  int = 15,
    n_skills:   int = 20,
    n_titles:   int = 20,
    n_companies: int = 15,
):
    """
    Download one dashboard chart as an .xlsx with two sheets: the chart's
    aggregate numbers (identical to what /api/dashboard returned for it) and
    the raw job postings behind them, scoped by the same dump/country/timeline/
    explicit-filter selection as the dashboard the user was looking at.
    """
    if chart not in _EXPORT_CHARTS:
        raise HTTPException(status_code=400, detail=f"Unknown chart '{chart}'")

    resp = get_dashboard(
        dumps=dumps, country=country, sector=sector, timeline=timeline,
        employment_type=employment_type, career_level=career_level, company=company,
        experience=experience, salary_bucket=salary_bucket,
        n_sectors=n_sectors, n_skills=n_skills, n_titles=n_titles, n_companies=n_companies,
    )
    if "error" in resp:
        raise HTTPException(status_code=404, detail=resp["error"])

    sheet_title, extract = _EXPORT_CHARTS[chart]
    chart_rows = extract(resp)
    if not chart_rows:
        raise HTTPException(status_code=404, detail="No data for selected filters")

    explicit_active = {
        k: v for k, v in {
            "sector": sector, "employment_type": employment_type, "career_level": career_level,
            "company": company, "experience": experience, "salary_bucket": salary_bucket,
        }.items() if v and v != "All"
    }
    plot_df = _scope_plot_df(dumps, country, timeline, explicit_active)

    cols    = [c for c, _ in _EXPORT_POSTING_COLUMNS if c in plot_df.columns]
    headers = [h for c, h in _EXPORT_POSTING_COLUMNS if c in plot_df.columns]
    postings_df = plot_df[cols].copy()
    postings_df.columns = headers

    # An unfiltered export (~31k rows) takes ~15-20s here — pandas' to_excel
    # cell-formatting loop dominates regardless of writer engine (openpyxl vs
    # xlsxwriter benchmarked identical). Acceptable: it's a background browser
    # download (this endpoint is reached via a plain <a href>, not a blocking
    # fetch), and the common case — some dump/filter already selected — is
    # low thousands of rows, ~1-2s.
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(chart_rows).to_excel(writer, sheet_name=sheet_title[:31], index=False)
        postings_df.to_excel(writer, sheet_name="Job Postings", index=False)
    buf.seek(0)

    filename = f"{chart}_{(dumps or 'all').replace(',', '-')}"[:80] + ".xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest):
    """
    Streaming SSE chat endpoint.
    Returns text/event-stream — each event: data: {"token": "..."}
    Final event: data: [DONE]
    """
    set_session_id(body.session_id)

    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(body.question) > _MAX_QUESTION_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Question too long — maximum {_MAX_QUESTION_LEN} characters.",
        )

    model    = body.model if body.model in AVAILABLE_MODELS.values() else "fanar/Fanar-C-2-27B"
    dump_ids = [d for d in body.dump_ids if d] or None
    explicit_filters = {k: v for k, v in body.filters.items() if v and str(v).strip()}

    sessions: SessionStore = _state["sessions"]
    history  = sessions.get_history(body.session_id)

    # Append user message immediately
    sessions.append(body.session_id, "user", body.question)

    engine: RAGEngine = _state["engine"]

    async def event_stream():
        loop = asyncio.get_running_loop()

        # Step 1: decompose + SQL once, shared by the retrieval-info panel and
        # the answer generator below — avoids redundant Fanar API calls.
        def _prepare():
            return engine._prepare(body.question, history, dump_ids=dump_ids, explicit_filters=explicit_filters)

        try:
            prepared = await loop.run_in_executor(None, _prepare)
        except Exception:
            prepared = None

        # Step 2: retrieval info as the very first event (decomposition + semantic hits)
        def _get_ret():
            return engine.get_retrieval_info(body.question, history, dump_ids=dump_ids, prepared=prepared)

        try:
            ret_info = await loop.run_in_executor(None, _get_ret)
            yield f"data: {json.dumps({'type': 'retrieval', 'info': ret_info})}\n\n"
        except Exception:
            pass

        # Step 3: stream answer tokens
        full_response: list[str] = []
        async for event in _sse_stream(engine, body.question, history, model, dump_ids=dump_ids, prepared=prepared):
            yield event
            if event.startswith("data: ") and '"token"' in event:
                try:
                    token = json.loads(event[6:]).get("token", "")
                    full_response.append(token)
                except Exception:
                    pass

        sessions.append(body.session_id, "assistant", "".join(full_response))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
