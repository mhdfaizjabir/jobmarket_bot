# Architecture — GCC AI Job Market Intelligence Platform

This document describes how the system is put together as of Sprint 3
(platform foundation / production readiness). See [PROJECT_SPEC.md](PROJECT_SPEC.md)
for the feature roadmap and sprint history — this file is the "how it works,"
that file is the "what we're building and why." [SCHEMA.md](SCHEMA.md) documents
the data shape (postings, Qdrant points, sessions) as an ER diagram.

---

## 1. Project structure

```
HBKU/
├── PROJECT_SPEC.md          # living spec + sprint log
├── ARCHITECTURE.md          # this file
├── frontend/                # Next.js app (App Router)
│   ├── app/
│   │   ├── page.tsx         # landing page
│   │   └── app/page.tsx     # main app shell (Sidebar + Dashboard/Chat tabs)
│   ├── components/
│   │   ├── Sidebar.tsx      # dataset (dump_id) + model selection
│   │   ├── Dashboard.tsx    # charts, country/timeline/sector pills
│   │   └── Chat.tsx         # streaming chat UI + retrieval transparency panel
│   └── lib/
│       ├── api.ts           # typed fetch/SSE wrappers around the backend
│       ├── types.ts         # shared TS types
│       ├── theme.tsx        # dark/light theme context
│       └── i18n.tsx         # EN/AR language context
│
└── RAG/                     # FastAPI backend + RAG pipeline
    ├── server.py             # FastAPI app: routes, middleware, error handlers
    ├── config/               # centralized configuration (see §9)
    │   ├── settings.py        # paths, environment, CORS, static constants
    │   ├── llm.py              # model config, make_client(), system prompt
    │   └── logging.py          # structured logging setup
    ├── filter_registry.py    # single source of truth for explicit_filters (see §4)
    ├── security.py           # security policy: headers, body cap, input validation, CORS, env checks
    ├── observability.py      # Prometheus (active) + Sentry/Langfuse hooks (dormant until keys set)
    ├── data_loader.py        # reads Excel/CSV -> normalized DataFrame
    ├── analytics.py          # pandas statistics (AnalyticsEngine)
    ├── sql_engine.py         # text-to-SQL over an in-memory SQLite copy
    ├── vector_store.py       # Qdrant Cloud REST wrapper (embed/search/payload)
    ├── rag_engine.py         # orchestrates decompose -> SQL -> pandas -> Qdrant -> LLM
    ├── session.py            # in-memory chat session/history store
    ├── app.py                # legacy Streamlit UI — see §11, flagged for review
    ├── build_index.py        # CLI: (re)build the Qdrant index from data/
    ├── migrate_sector_payload.py       # one-off Qdrant payload backfill (Sprint 1)
    ├── migrate_explicit_filters_payload.py  # generalized payload backfill (Sprint 8)
    ├── tests/                # pytest suite (registry, session, security, SQL, chat schema, live)
    └── evaluate*.py, generate_*.py, compare_rag.py  # offline eval/benchmark tools
```

---

## 2. Request flow (every HTTP request)

```
Browser
  |
  v
Next.js frontend (localhost:3000)  --- fetch/SSE --->  FastAPI backend (localhost:8000)
                                                          |
                                    CORSMiddleware  <-----+
                                          |
                              SlowAPIMiddleware (rate limit: 200/min global,
                                          |               30/min on /api/chat)
                              _request_logging_middleware
                                (assigns request_id, times the call,
                                 logs "METHOD path -> status  dur=Xms",
                                 sets X-Request-ID response header)
                                          |
                              route handler (server.py)
                                          |
                    +---------------------+----------------------+
                    |                     |                      |
              /api/datasets         /api/dashboard           /api/chat (SSE)
              /api/models           (pandas agg)             /api/session
              /health                                        DELETE /api/session/{id}
```

Any exception raised anywhere below the middleware is caught by one of four
registered handlers (all return the same JSON shape — see §8):
`RateLimitExceeded`, `HTTPException`, `RequestValidationError`, or the
catch-all `Exception` handler (which also calls `observability.capture_exception`).

---

## 3. Dashboard flow

```
Dashboard.tsx
  |  activeSector = filters.sector ?? 'All'   (filters object owned by AppPage)
  |
  v
fetchDashboard({ dumps, country?, sector?, timeline? })
  |
  v
GET /api/dashboard?dumps=...&sector=...
  |
  v
server.py: get_dashboard()
  |  1. filter df by dump_ids (self._filter_by_dumps)
  |  2. filter by country / sector / timeline query params (inline pandas)
  |  3. compute every chart's data directly from the filtered DataFrame
  |     (sectors, career levels, employment types, salary distribution,
  |      skills frequency, experience, company size, languages, locations,
  |      job titles, companies, country comparison, month-over-month trend)
  v
one JSON response -> Dashboard.tsx renders all charts (Recharts)
```

This endpoint does **not** go through RAGEngine at all — it's a direct,
synchronous pandas aggregation. That's why it was never affected by the
Sprint 1 chat/dashboard mismatch bug (which was specifically about the
*chat* pipeline not seeing the same filters).

---

## 4. Filter flow (explicit_filters — Sprint 1 & 2)

Two independent filter mechanisms feed into the same chat request:

```
Frontend                    Backend (server.py)              rag_engine.py
--------                    -------------------              -------------
dump_ids (checkboxes)  ---> ChatRequest.dump_ids  ----------> hard-scopes every
                                                                layer (SQL subquery,
                                                                pandas .isin(),
                                                                Qdrant $in filter)

filters: {sector: X} --->   ChatRequest.filters   ----------> translate_explicit_filters()
(AppPage's single                                              [filter_registry.py]
 `filters` state,                                                    |
 shared by Dashboard                                                 v
 and Chat)                                                    {"_sector_norm": X}
                                                                merged into decomposed
                                                                filters dict, then used
                                                                by: _apply_filters (pandas),
                                                                _matches_filter_metadata
                                                                (Qdrant post-filter safety
                                                                net), _CHROMA_EXACT_FIELDS
                                                                (Qdrant pre-filter),
                                                                sql_engine's _scope_query
                                                                (hard SQL subquery),
                                                                and a "<LABEL> SCOPE" note
                                                                injected into the LLM prompt

question text          --->  (no wire field — this is        _decompose() LLM call extracts
"jobs in Qatar,                inferred by the LLM, not        _country, _timeline,
entry level"                   sent by the frontend)           career_level, job_title
                                                                (soft filters — best-effort,
                                                                 not a hard UI-driven scope)
```

`filter_registry.py` is the single place a new UI-driven filter is declared
(`key`, internal `column`, prompt `label`, optional `normalize` fn). Every
consumer (`_apply_filters`, `_matches_filter_metadata`, `_CHROMA_EXACT_FIELDS`,
`sql_engine.get_context`, `vector_store`'s payload/index lists, the scope-note
text) reads `EXPLICIT_FILTER_COLUMNS` from the registry instead of naming a
field — adding a filter is one registry entry, not a multi-file change.

---

## 5. RAG / chat flow

```
POST /api/chat  (question, session_id, model, dump_ids, filters)
  |
  v
sessions.append("user", question)
  |
  v
engine._prepare(question, history, dump_ids, explicit_filters)
  |
  |-- 1. _normalize_decomposed()
  |       - chitchat check (regex) -> skip retrieval entirely if greeting/thanks
  |       - _decompose(): one LLM call (INTERNAL_MODEL) -> {filters, semantic_query,
  |         needs_aggregation, analysis_types, resolved_question}
  |       - country inheritance from history, follow-up resolution, job_title
  |         extraction safety nets (all regex/heuristic post-processing)
  |
  |-- 2. merge explicit_filters over decomposed filters  (see §4)
  |
  |-- 3. IF needs_aggregation:
  |       sql_engine.get_context(question, dump_ids, explicit_filters)
  |         -> LLM (INTERNAL_MODEL) generates SQL against a dynamic schema prompt
  |         -> FROM jobs rewritten to a dump/filter-scoped subquery
  |         -> runs against an in-memory SQLite copy of the DataFrame
  |
  v
engine.get_retrieval_info(...)  -> sent as the FIRST SSE event ("retrieval")
  so the frontend can render the transparency panel before tokens arrive
  |
  v
engine.answer(...)  (generator, streamed as SSE "token" events)
  |
  |-- _build_full_context():
  |     - DATASET SUMMARY + SCOPE NOTE lines (country/timeline/sector/...)
  |     - job-title grounding check (closest real titles if <3 exact matches)
  |     - pandas analytics for types SQL didn't cover (skills/salary/language/...)
  |     - Qdrant semantic search (trace_llm_call is NOT wrapped here — this is
  |       an embedding call, not a chat completion)
  |     - GROUNDED COMPANY NAMES guard (LLM can't cite a company it never saw)
  |
  |-- build_system_prompt() [config/llm.py] — dynamic, built from the live
  |     DataFrame's countries/timelines/top employers, never hardcoded
  |
  v
client.chat.completions.create(..., stream=True)   <- wrapped in
                                                        observability.trace_llm_call()
  |
  v
tokens streamed back as SSE "token" events -> [DONE]
  |
  v
sessions.append("assistant", full_response)
```

---

## 6. Qdrant (vector search) flow

```
Indexing (build_index.py / incremental on data change):
  DataFrame row -> _build_doc_text() (human-readable text blob)
                -> _build_metadata() (payload: job_title, company, category,
                   _sector_norm, _country, _timeline, _dump_id, ...
                   — driven by filter_registry.EXPLICIT_FILTER_COLUMNS,
                   so a new registered filter is captured automatically)
                -> SentenceTransformer.encode() -> 384-dim vector
                -> upsert to Qdrant Cloud collection "gulf_jobs"

Search (per chat request):
  semantic_q -> encode() -> query vector
  filters    -> _to_chroma_where() -> Qdrant REST filter (must/match/any)
             -> VectorStore.search(vector, filter, limit)
             -> falls back to unfiltered search + local post-filter
                (_post_filter_semantic_results) if Qdrant errors on a
                not-yet-indexed field
```

Payload indexes (`_country`, `_timeline`, `career_level`, `_dump_id`,
`_source`, plus every `EXPLICIT_FILTER_COLUMNS` entry) are created on
startup if missing (`_ensure_payload_indexes`). Historical points still need
a one-time payload backfill when a *new* filter is registered — see
`migrate_sector_payload.py` for the pattern (scroll + compute + set-payload,
no re-embedding).

---

## 7. SQL flow

```
sql_engine.SQLEngine.__init__(df)
  -> loads the DataFrame into an in-memory SQLite table "jobs"
  -> builds a system prompt with the REAL schema, countries, timelines,
     top sectors (never hardcoded)

get_context(question, dump_ids, explicit_filters)
  -> _to_sql(): one LLM call (INTERNAL_MODEL) generates a SELECT statement
     (post-processed: location exact-match -> LIKE, LIMIT injected if missing)
  -> _scope_query(): rewrites "FROM jobs" -> a filtered subquery
     (_dump_id IN (...) AND <registered column> = '<value>' ...)
  -> runs against SQLite, formats the result as a small text table
```

---

## 8. Error handling & logging

```
Any exception
  |
  v
RateLimitExceeded / HTTPException / RequestValidationError / Exception
  |
  v
JSON body (every handler returns this exact shape):
{
  "success": false,
  "error": "rate_limited" | "http_error" | "validation_error" | "internal_error",
  "message": "<human-readable, never a stack trace>",
  "request_id": "<uuid4, matches X-Request-ID header>"
}
```

Logging: `config/logging.py` configures one root handler with the format
`timestamp | LEVEL | module | req=<id> sess=<id>[ dur=Xms] | message`.
`request_id`/`session_id` are contextvars set by the request middleware
(and `set_session_id()` in the chat route) — any `logger.info(...)` call
anywhere in the codebase automatically carries the current request's IDs
with no parameter threading required.

---

## 9. Configuration

```
config/
  settings.py  — ENVIRONMENT, APP_VERSION, paths, ALLOWED_ORIGINS,
                 TOP_K, DESCRIPTION_TRUNCATE, COUNTRY_FLAGS/COLORS,
                 COLUMN_ALIASES
  llm.py        — make_client(), CHAT_MODEL, INTERNAL_MODEL,
                 EMBEDDING_MODEL, AVAILABLE_MODELS, build_system_prompt()
  logging.py    — configure_logging(), get_logger(), request/session
                 context vars
  __init__.py   — re-exports everything above, so `from config import X`
                 works exactly as it did when this was one config.py file
```

Environment variables read (`.env` in `RAG/`): `OPENAI_API_KEY`,
`FANAR_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `ALLOWED_ORIGINS`,
`LLM_TIMEOUT_SECONDS`, `LOG_LEVEL`, `ENVIRONMENT`, `APP_VERSION`.

---

## 10. Observability hooks (Sprint 3 — interfaces only)

`observability.py` defines three functions, currently backed by the
structured logger, meant to be the only edit point when a real backend is
added in a later sprint:

| Function | Called from | Future backend |
|---|---|---|
| `capture_exception(exc, **ctx)` | the global `Exception` handler | Sentry |
| `record_metric(name, value, **tags)` | the request-logging middleware | Prometheus |
| `trace_llm_call(name, **meta)` (context manager) | around the streaming chat completion in `rag_engine.answer()` | Langfuse / OpenTelemetry |

No external SDK is installed yet — this sprint intentionally stops at the
interface, per the "don't add Langfuse/Sentry yet" instruction for Sprint 3.

---

## 11. Known structural debt (flagged, not fixed this sprint)

- **`app.py`** is a full parallel Streamlit UI (dashboard + chat) that predates
  the Next.js frontend. It still imports and runs, but it's unclear whether
  it's an active dev tool or leftover from before the current frontend existed.
  **Needs a human decision**: keep as an internal/demo tool, archive, or remove.
- **`rag_engine.py`** (~1550 lines) and **`server.py`** (~700 lines) mix
  several concerns — see the `TODO(structure, sprint 5+)` comments at the top
  of each file for the specific proposed split (`prompts/`, `retrievers/`,
  `routers/`, `middleware/`). Not extracted now — nothing there is broken.
- **`career_level`** exists as both a soft (LLM-inferred) filter and a future
  candidate for the explicit filter registry — not unified (see Sprint 2 log
  in PROJECT_SPEC.md).
