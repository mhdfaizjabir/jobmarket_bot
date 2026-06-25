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
"""

import asyncio
import json
import os
import re
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

from config import DATA_DIR, AVAILABLE_MODELS
from data_loader import load_all, parse_file_info, sort_timelines
from vector_store import VectorStore
from analytics import AnalyticsEngine
from rag_engine import RAGEngine
from session import SessionStore


# ---------------------------------------------------------------------------
# App state — loaded once at startup, shared across all requests
# ---------------------------------------------------------------------------

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Loading data and initialising engines...")

    source_files = sorted(
        str(p) for p in (list(DATA_DIR.glob("*.xlsx")) + list(DATA_DIR.glob("*.csv")))
        if not p.name.startswith("~$") and not parse_file_info(p)["is_ar"]
    )
    df, timelines = load_all(DATA_DIR)

    vs      = VectorStore()
    engine  = RAGEngine(AnalyticsEngine(df), vs)
    sessions = SessionStore()

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
                print(f"Session cleanup: removed {n} expired sessions")

    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.start()

    print(f"Ready — {len(df):,} postings | {vs.count():,} vectors in Qdrant")
    yield


# ---------------------------------------------------------------------------
# FastAPI app + rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="GCC Job Market Intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests — please slow down."},
    )

app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question:   str
    session_id: str
    model:      str = "fanar/Fanar-C-2-27B"
    dump_ids:   list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_by_dumps(df, dump_ids: list[str]):
    if not dump_ids or "_dump_id" not in df.columns:
        return df
    return df[df["_dump_id"].isin(dump_ids)]


def _parse_salary_mid(val) -> float | None:
    if not val or str(val).strip() == "":
        return None
    s = str(val)
    nums = re.findall(r"[\d,]+", s)
    if len(nums) < 2:
        return None
    try:
        lo, hi = float(nums[0].replace(",", "")), float(nums[1].replace(",", ""))
    except ValueError:
        return None
    if lo < 1 or hi < 1:
        return None
    if "year" in s.lower() or "annual" in s.lower():
        lo, hi = lo / 12, hi / 12
    if any(x in s.upper() for x in ["SAR", " SR", "SR "]):
        lo, hi = lo / 3.75, hi / 3.75
    return (lo + hi) / 2


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

@app.get("/health")
def health():
    return {
        "status":    "ok",
        "postings":  len(_state.get("df", [])),
        "vectors":   _state["vs"].count() if "vs" in _state else 0,
        "uptime_s":  round(time.time() - _state.get("started_at", time.time())),
        "sessions":  _state["sessions"].stats() if "sessions" in _state else {},
    }


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


@app.get("/api/dashboard")
def get_dashboard(
    dumps:    str = "",
    country:  str = "All",
    sector:   str = "All",
    timeline: str = "All",
    n_sectors:  int = 15,
    n_skills:   int = 20,
    n_titles:   int = 20,
    n_companies: int = 15,
):
    """
    Return all chart data for the dashboard in one call.
    Frontend passes active dump_ids as comma-separated string.
    """
    df = _state["df"]
    dump_ids = [d for d in dumps.split(",") if d]
    plot_df  = _filter_by_dumps(df, dump_ids) if dump_ids else df

    sec_col = "_sector_norm" if "_sector_norm" in plot_df.columns else "category"
    car_col = "_career_norm" if "_career_norm" in plot_df.columns else "career_level"
    emp_col = "_employment_norm" if "_employment_norm" in plot_df.columns else "employment_type"

    # Apply inline filters
    if country  != "All" and "_country"  in plot_df.columns:
        plot_df = plot_df[plot_df["_country"]  == country]
    if sector   != "All" and sec_col     in plot_df.columns:
        plot_df = plot_df[plot_df[sec_col]     == sector]
    if timeline != "All" and "_timeline" in plot_df.columns:
        plot_df = plot_df[plot_df["_timeline"] == timeline]

    if plot_df.empty:
        return {"error": "No data for selected filters"}

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
        tmp["_mid"] = tmp["salary"].apply(_parse_salary_mid)
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
            bins   = [0, 500, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000, float("inf")]
            labels = ["<$500","$500-1K","$1K-1.5K","$1.5K-2K","$2K-3K","$3K-5K","$5K-7.5K","$7.5K-10K","$10K-15K","$15K+"]
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

    return {
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


@app.post("/api/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest):
    """
    Streaming SSE chat endpoint.
    Returns text/event-stream — each event: data: {"token": "..."}
    Final event: data: [DONE]
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(body.question) > _MAX_QUESTION_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Question too long — maximum {_MAX_QUESTION_LEN} characters.",
        )

    model    = body.model if body.model in AVAILABLE_MODELS.values() else "fanar/Fanar-C-2-27B"
    dump_ids = [d for d in body.dump_ids if d] or None

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
            return engine._prepare(body.question, history, dump_ids=dump_ids)

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
