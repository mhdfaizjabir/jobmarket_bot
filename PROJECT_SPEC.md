# MASTER PROJECT SPECIFICATION — GCC AI Job Market Intelligence Platform

Status: living document. Every sprint should update the "Baseline / Progress" section below before moving to the next sprint. Do not let this drift from the code — if a section here becomes stale, fix it in the same PR that makes it stale.

## Context

Working AI-powered Job Market Intelligence System developed at HBKU. Current features:

- Hybrid RAG architecture (SQL + Pandas Analytics + Semantic Search)
- FastAPI backend, Next.js frontend, Qdrant Cloud vector database
- Dashboard analytics, dataset selector, incremental indexing
- Multilingual support (English + Arabic)
- Bayt + LinkedIn datasets
- Evaluation benchmark (MCQ + RAG benchmark)
- Streaming responses, dataset-aware retrieval

**Objective:** transform the current research prototype into a polished, production-ready public platform while preserving existing functionality. Not a redesign. Every change should be modular, maintainable, secure, and scalable.

---

## Baseline audit (2026-07-06)

Corrections/clarifications against the feature list above, established by reading the repo rather than assuming:

- **Vector store**: Qdrant Cloud, accessed via a hand-rolled REST wrapper in `RAG/vector_store.py` (avoids `qdrant-client`'s httpcore TLS issues on Windows). The `chroma_db/` directory and `CHROMA_DIR` name are legacy — not actually Chroma in production.
- **Frontend routes** (as of Sprint 7, 2026-07-07): `/` (landing), `/app` (chat + dashboard bundled in one page via `Chat.tsx`, `Dashboard.tsx`, `Sidebar.tsx`), plus `/about`, `/research`, `/docs`, `/settings`, `/admin`. Reports/Contact were folded into `/research` (benchmarks) and `/about` (contact) rather than built as standalone pages — see Sprint 7 log.
- **DevOps** (as of Sprint 6): `RAG/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`/`docker-compose.prod.yml`, `.github/workflows/ci.yml`, `RAG/tests/` all exist. `railway.toml` predates this and is no longer the only deployment path.
- **Backend modules present**: `server.py` (FastAPI), `rag_engine.py`, `sql_engine.py`, `analytics.py`, `vector_store.py`, `session.py`, `data_loader.py`, `build_index.py`, `evaluate.py` / `evaluate_mcq.py`, `filter_registry.py`, `security.py`, `observability.py`, `config/`.
- **Observability** (as of Sprint 6): Prometheus is genuinely active at `/metrics`. Sentry and Langfuse are fully coded but dormant — activate by setting `SENTRY_DSN` / `LANGFUSE_PUBLIC_KEY`+`SECRET_KEY` in `.env`, zero code changes needed. No Redis yet (dashboard cache is in-memory only) and no Grafana dashboards are checked into the repo.

This section is corrected as of the 2026-07-07 audit (done by reading code, not assuming prior notes were current — see Sprint 6/7 log entries for what that audit found stale). Everything else in the objectives below is accurate to the current repo.

---

## PRIMARY OBJECTIVES

### 1. Unified Dashboard + AI Assistant
Dashboard and chatbot must always agree. Selecting Qatar + Bayt + May 2026 + IT Sector updates every dashboard visualization **and** scopes the chatbot to that same filtered data. No mismatch between dashboard filters and chatbot retrieval ever.

### 2. Universal Dataset Filtering
Filters: Country, Source, Timeline, Sector, Career Level, Employment Type, Company, Salary Range, Experience Level, Language.

Must propagate: Frontend → Backend → Query Parser → SQL Layer → Analytics Layer → Vector Search → LLM Context. No layer may silently ignore an active filter.

### 3. Interactive Dashboard
Charts become navigation, not static images: click company → related jobs; click salary range → matching postings; click skill → jobs requiring it; click sector → filters chatbot automatically.

### 4. Modern Public Website
Landing, Dashboard, AI Assistant, Reports, Research, About, Documentation, Contact, Settings, Admin Portal. Responsive, dark mode, Arabic support, professional branding.

---

## AI SYSTEM IMPROVEMENTS
Improve the existing RAG pipeline without changing its architecture: better metadata filtering, follow-up question handling, conversation memory, confidence score, source transparency, retrieval explanation, better prompt management, context compression, semantic caching, cross-encoder reranking (optional), better error recovery. The chatbot should always explain where information came from.

## SETTINGS
Language, Theme, Model Selection, Temperature, Max Tokens, Streaming, Semantic Search toggle, Analytics Layer toggle, SQL Layer toggle, Prompt Style, Export Settings.

## ADMIN PORTAL
Upload/view/delete datasets, rebuild indexes, view indexing progress, manage users, monitor API usage, view logs, view analytics, trigger monthly pipeline.

## DATA PIPELINE
New dataset → Validation → Normalization → Deduplication → Metadata extraction → Embedding → Qdrant update → Dashboard refresh → Ready. No manual code changes for new datasets.

## PERFORMANCE
Redis cache, response cache, semantic cache, lazy loading, async APIs, pagination, compression, efficient filtering, incremental indexing, background jobs.

## SECURITY
HTTPS, env vars, secrets management, rate limiting, input validation, CORS, secure headers, SQL injection protection, prompt injection protection, request size limits, admin authentication/authorization, audit logs, error handling, health endpoint.

## OBSERVABILITY
Langfuse (prompt tracing, prompt versions, retrieval tracing, LLM latency, token usage, cost tracking, feedback tracking), Sentry (backend + frontend errors), Prometheus (app metrics), Grafana (dashboards), OpenTelemetry (optional, distributed tracing), structured logging, request IDs.

## DEVOPS
Docker, Docker Compose, Nginx, GitHub Actions (test + deploy), environment separation, production config, health checks, backup strategy.

## DOCUMENTATION
README, Architecture, Deployment, API docs, Developer Guide, User Guide, Admin Guide, Security Guide, Troubleshooting, Roadmap.

## TESTING
Unit, integration, API, frontend, load, regression, RAG evaluation, filter validation, security testing.

## USER EXPERIENCE
Responsive, accessible, loading/empty/error states, skeleton loaders, animations, copy answer, export answer, download report, feedback buttons, suggested questions, search history, saved reports.

## OPTIONAL AI FEATURES
Career advisor, skill gap analysis, monthly AI-generated reports, salary prediction, trend forecasting, job recommendations, market insights, CV analysis, explainability.

---

## SUCCESS CRITERIA
Feel like a professional AI SaaS product; support public users; secure and production-ready; easy to maintain; modular and scalable; new datasets require no code changes; demonstrate strong software/AI engineering and DevOps practice; showcase the HBKU research in a polished, deployable form.

---

## Proposed sprint order

Rationale: fix correctness (filters) before building surface area (pages), lock down security before anything is public, add observability before performance tuning (so we can measure the effect), save DevOps/testing/docs for once the shape has stabilized.

1. **Filter propagation** — audit and fix the frontend→SQL→analytics→vector→LLM chain so every filter is honored everywhere. Foundation; everything else assumes this works.
2. **Interactive dashboard wiring** — click-through from charts into filtered chat/results, built on sprint 1's plumbing.
3. **Frontend IA expansion** — add the missing routes (Settings, Admin, Reports, Research, About, Docs, Contact) as real pages, even if minimal initially.
4. **Security baseline** — env/secrets hygiene, rate limiting, input validation, CORS, admin auth. Must land before any public exposure.
5. **RAG quality improvements** — conversation memory, confidence score, source transparency, semantic caching.
6. **Admin portal + data pipeline automation** — dataset upload/validation/embedding pipeline, index rebuild UI.
7. **Observability** — Sentry first (cheap, immediate value), then Langfuse for RAG tracing, then Prometheus/Grafana.
8. **Performance** — Redis/response/semantic caching, async, pagination — now measurable against sprint 7's metrics.
9. **DevOps** — Docker, Compose, CI/CD, health checks.
10. **Testing** — unit/integration/API/RAG-eval, backfilled against the now-stable architecture.
11. **UX polish + optional AI features** — last, since it's additive and doesn't block anything else.
12. **Documentation** — written last so it describes what actually shipped, not what was planned.

## Sprint log
(update after each sprint closes: what shipped, what was deferred, what changed from plan)

### Sprint 1 — Filter propagation (2026-07-06)

**Shipped:** Fixed the sector filter, which was the concrete break matching the spec's example scenario (dashboard sector click was invisible to chat). Built as a generic `explicit_filters` mechanism (not a one-off `sector` param) so future filters (Employment Type, Salary Range, etc.) wire in the same way in Sprint 3.

- Frontend: `activeSector` state lifted from `Dashboard.tsx` to `app/app/page.tsx`, passed to both `Dashboard` and `Chat`; `Chat.tsx` sends it as `filters: {sector}` on every chat request; shown in the chat header for transparency.
- Backend: `ChatRequest.filters: dict[str, str]` added to `server.py`; `rag_engine.py`'s `_prepare()` merges explicit UI filters over LLM-decomposed filters (`sector` → internal `_sector_norm` key); `_apply_filters` (pandas), `_matches_filter_metadata` (semantic post-filter, normalizes raw `category` via `norm_sector()`), and `_CHROMA_EXACT_FIELDS` (Qdrant pre-filter) all handle `_sector_norm` now.
- `sql_engine.py`: sector is now a **hard** SQL subquery filter (`_scope_query`, mirrors the existing `dump_ids` mechanism) rather than a soft text hint to the SQL-generation LLM — deterministic, not guessed.
- `vector_store.py`: `_sector_norm` added to `_META_COLS` and to the Qdrant payload index list.
- One-time data migration (`RAG/migrate_sector_payload.py`, run against production Qdrant Cloud with user confirmation): backfilled `_sector_norm` onto all 30,795 existing points via payload merge (no re-embedding). Idempotent, safe to re-run.

**Verified (API-level):** `/api/dashboard?dumps=qatar_may_2026&sector=Technology` → total 254. `/api/chat` with the same `dump_ids` + `filters:{sector:"Technology"}` → SQL layer independently returns COUNT(*)=254, all semantic hits are genuinely Technology-sector postings, final answer states "254 job postings." Negative control without the sector filter → both dashboard and chat agree on 2,376 (the full unfiltered Qatar May 2026 count). Dashboard and chat numbers matched exactly in both cases.

**Not done / deferred:** No browser automation tool was available in-session, so the actual UI click-through (select sector on dashboard → switch to chat tab → confirm scoped answer) was not performed — only verified via direct API calls. Recommend a manual browser check before treating this as fully closed. Career Level, Employment Type, Company, Salary Range, Experience Level, Language filters still have no UI controls — that's Sprint 3 (Frontend IA expansion) plus one registry entry each (see Sprint 2 below).

### Sprint 2 — Generic filter infrastructure (2026-07-06)

**Goal:** replace the sector-specific plumbing from Sprint 1 with a registry-driven `explicit_filters` mechanism so future filters (Employment Type, Salary Range, Experience Level, Company, Language) are one registry entry each, touching zero pipeline code.

**Shipped:**
- New `RAG/filter_registry.py` — single source of truth. Each `FilterField` entry declares `key` (wire name), `column` (internal df/SQL/Qdrant field), `label` (for prompt scope notes), and an optional `normalize` fn. Currently one entry: `sector`.
- `rag_engine.py`: `_CHROMA_EXACT_FIELDS`, `_apply_filters`, `_matches_filter_metadata`, the summary-scoping + scope-note block in `_build_full_context`, and `answer()`'s `total_postings` restriction all now loop over `EXPLICIT_FILTER_COLUMNS` from the registry instead of branching on `_sector_norm` by name.
- `sql_engine.py`: `get_context`/`_scope_query` take a generic `explicit_filters: dict[str, str]` (already resolved to real column names) and validate each against the table's own columns — no `sector` parameter, no `_sector_norm` string anywhere in this file anymore.
- `vector_store.py`: `_META_COLS` and the Qdrant payload-index list are both built from `_BASE_META_COLS`/the fixed index set unioned with `EXPLICIT_FILTER_COLUMNS` — a new registry entry is automatically captured into future embeds and gets its Qdrant index created on next startup, with no code change.
- Frontend: `AppPage` now owns one `filters: Record<string, string>` state (not `activeSector`), with a single `handleFilterChange(key, value | null)` setter. Both `Dashboard` (via `filters`/`onFilterChange` props) and `Chat` (via a `filters` prop, sent straight through to `streamChat`) read the same object — no duplicated state, matching the spec's requirement.

**Why each change was required:** Sprint 1's fix worked but every layer had a bespoke `_sector_norm` branch and `sql_engine.get_context(..., sector=...)` had a dedicated parameter — adding Employment Type next would have meant repeating the same ~6-file change again. The registry makes the field list data, not code: `_apply_filters`, `_matches_filter_metadata`, `_CHROMA_EXACT_FIELDS`, the SQL scope, the Qdrant payload/index list, and the prompt scope-note text all derive from `EXPLICIT_FILTER_COLUMNS` rather than naming `sector` — so a second entry lights up in all of them simultaneously.

**Deliberately NOT touched (preserved architecture, not redesigned):**
- Country/Timeline/Source stay on the `dump_ids` mechanism — that was never broken and dump-based scoping (a dataset *selection*, not a metadata filter) is a different concern from `explicit_filters`.
- The LLM-decomposer's soft filters (`_country`, `_timeline`, `career_level` inferred from question text, `job_title`'s CONTAINS-matching) are untouched — different semantics (inferred + fuzzy) from explicit UI-driven exact-match filters, and they weren't broken.
- `/api/dashboard`'s query params (`country`, `sector`, `timeline`) were left as named params rather than folded into a generic filters blob — that endpoint does direct dataframe slicing for chart rendering with no repeated-pipeline-touching problem to solve; genericizing it would trade a debuggable REST querystring for a JSON-in-querystring with no corresponding benefit.

**Regression-verified:** re-ran the exact Sprint 1 checks after the refactor. `sector=Technology` in Qatar May 2026 → dashboard 254, chat SQL layer 254, same top semantic hit, same answer wording. No filter → both sides 2,376. Byte-for-byte identical to pre-refactor behavior.

**Technical debt / remaining gaps:**
1. Adding a new filter still needs a **one-time Qdrant payload backfill** for historical data (same pattern as `migrate_sector_payload.py`) — the registry automates the pipeline, not the data migration for already-embedded rows.
2. `career_level` exists in two parallel places: the decomposer's soft text-inferred filter, and a future candidate for the explicit registry (e.g., a dashboard dropdown). Not unified — left alone this sprint to avoid touching working, tested behavior beyond what was asked.
3. No UI controls exist yet for anything beyond sector — the registry is ready, but Employment Type/Salary Range/Experience Level/Company/Language need actual dashboard controls (Sprint 3).
4. The frontend's `Object.entries(filters)` display in the chat header will show raw wire keys (e.g. `employment_type`) once more filters are added — may want a display-label map (could reuse the registry's `label` field via a small `/api/filter-fields` endpoint, or just duplicate labels client-side) before Sprint 3 ships new controls.

**Suggested Sprint 3 scope:** add UI controls (dropdowns/pills) for Employment Type, Career Level (as an explicit filter, superseding the soft one), Experience Level, Company, and Language — each is one `filter_registry.py` entry + one frontend control + one payload backfill run. Also: make dashboard charts clickable (click a skill/company/salary-bracket → sets the corresponding explicit filter and jumps to Chat), per the spec's "interactive dashboard" objective.

*(Superseded — see below: the professor's guidance was "no more datasets/filters, package what exists." Sprint 3 became a platform-foundation sprint instead.)*

### Sprint 3 — Platform foundation / production readiness (2026-07-06)

**Goal:** clean architecture, logging, config, error handling, docs — no new user-visible behavior, no new filters, no new datasets.

**Shipped:**
1. **Config package** — `config.py` (215 lines) split into `config/settings.py` (paths/env/CORS/static constants), `config/llm.py` (model config + `make_client()` + `build_system_prompt()`), `config/logging.py` (structured logging setup). `config/__init__.py` re-exports every name, so all ~10 existing `from config import X` call sites needed zero changes. Added `ENVIRONMENT`, `APP_VERSION`, centralized `ALLOWED_ORIGINS` (previously computed ad hoc in `server.py`).
2. **Structured logging** — every log line: `timestamp | LEVEL | module | req=<id> sess=<id>[ dur=Xms] | message`. `request_id`/`session_id` are contextvars, populated automatically for any `logger.*` call made during request handling — no parameter threading needed at call sites. Replaced `print()` in `server.py`, `vector_store.py`, `rag_engine.py` (scoped to the live service path — left standalone CLI/eval/benchmark scripts' prints alone, since they're operator-run tools with their own console UX, not part of the request path).
3. **Request middleware** — assigns a UUID request id, times every request, logs one access-log line per request, sets `X-Request-ID` on the response.
4. **Consistent error handling** — every error path (rate limit, `HTTPException`, validation, and the catch-all `Exception` handler) now returns `{success: false, error, message, request_id}`. Fixed a bug caught during validation: the `HTTPException` handler was initially registered against `fastapi.HTTPException` (a subclass), which never fires for router-level 404s (raised as the Starlette base class) — re-registered against `starlette.exceptions.HTTPException` so both are caught via the normal MRO handler lookup.
5. **`RAG/observability.py`** — `capture_exception()`, `record_metric()`, `trace_llm_call()`. Backed by the logger only (no SDK installed, per instruction). Wired into the global exception handler, the request middleware, and around the streaming LLM call in `rag_engine.answer()` — actually exercised, not dead stubs.
6. **`/health` expanded** — `environment`, `version`, `uptime_s`, `postings`, `vectors`, `qdrant_status`, `model_configured`, `models_available`, `sessions`, `memory_mb` (via `psutil`, added to `requirements.txt`; degrades to `null` if unavailable rather than failing health).
7. **Dependency cleanup** — AST-based unused-import audit across the service modules found and removed two dead imports in `sql_engine.py` (`os`, `OpenAI`). Frontend-wide `eslint` audit surfaced pre-existing issues in `lib/i18n.tsx`/`lib/theme.tsx` (unrelated to Sprint 1–3 changes) — flagged, not fixed (out of this sprint's backend-focused scope).
8. **`ARCHITECTURE.md`** — project structure, request/dashboard/RAG/filter/Qdrant/SQL/LLM flows, error-handling contract, config layout, observability hook table, all with ASCII diagrams.
9. **Structure audit** — `TODO(structure, sprint 5+)` comments added to the top of `rag_engine.py` (~1550 lines) and `server.py` (~700 lines) naming specific extraction targets (`prompts/`, `retrievers/`, `routers/`, `middleware/`) — no code moved, per "only extract if safe."

**Found during validation (not just claimed — actually caught by re-testing):**
- The `HTTPException`-vs-`StarletteHTTPException` registration bug above (404s were silently still using the old error shape until re-tested and fixed).
- `session_id` wasn't reaching the middleware's own access-log line even though `set_session_id()` was called in the route handler — Starlette's `BaseHTTPMiddleware` runs the downstream app in a way that writes to a contextvar inside the route don't propagate back to the middleware's post-`call_next` code. Fixed by having the middleware peek the request body for `session_id` itself, before calling `call_next`, for the one route that has one (`POST /api/chat`).

**Regression-verified:** re-ran the exact Sprint 1/2 checks after every change. Dashboard: 254 (sector=Technology) / 2,376 (unfiltered) — unchanged. Chat: same SQL counts, same top semantic hit, same answer wording — unchanged. Frontend `tsc --noEmit` clean (no frontend files touched this sprint).

**Technical debt / remaining gaps (deliverable #4):**
1. **Contextvars don't cross thread boundaries.** `session_id`/`request_id` are correctly visible to any log call in the same asyncio task, but `rag_engine._prepare()` runs via `loop.run_in_executor()` and `_sse_stream` spawns a raw `threading.Thread` — neither inherits contextvars automatically (unlike `asyncio.to_thread`, which explicitly copies context). Any future `logger.*` calls added inside `rag_engine.py`/`sql_engine.py` will show `req=- sess=-` until this is addressed (needs `contextvars.copy_context().run(...)` wrapping around those executor/thread calls). Not fixed this sprint — no log statements currently live deep enough in that call path for it to matter yet, but it will bite the next person who adds one.
2. **`app.py`** (legacy Streamlit UI, ~1200 lines) still runs in parallel to the Next.js frontend + FastAPI backend. Unclear if it's an active dev tool or leftover. **Needs a manual decision** (deliverable #6).
3. **`rag_engine.py`/`server.py` size** — documented extraction targets via TODO comments, not executed.
4. **Frontend lint issues** (`lib/i18n.tsx`, `lib/theme.tsx`) — pre-existing, unrelated to this session's changes, not fixed (out of scope).
5. **`career_level`** still has two parallel mechanisms (soft decomposer + registry candidate) — unchanged since Sprint 2.

**Anything for manual review before deployment (deliverable #6):**
- Decide `app.py`'s fate (keep/archive/remove).
- `ENVIRONMENT`/`APP_VERSION` default to `"development"`/`"0.1.0-dev"` — set real values via env vars for any actual deployment.
- The contextvar/threading gap above should be fixed before anyone relies on `sess=`/`req=` correlation for debugging deep pipeline logs.

**Suggested Sprint 4:** per the discussion, this is Observability — Langfuse (LLM tracing, now that `trace_llm_call` is already wired at the right call site), Sentry (error tracking, now that `capture_exception` is already wired), Prometheus/Grafana (now that `record_metric` is emitting per-request duration). Each is now "swap the function body in `observability.py`," not a new integration point to design.

### Sprint 5 — Security hardening (2026-07-06)

**Reordering note:** the user presented a 16-phase "productionize everything" master prompt. Rather than execute it in one pass (the exact anti-pattern flagged in the very first message), it was mapped back onto the sprint cadence and the user chose to pull **Security (Phase 3)** ahead of Observability — it's fully self-contained (no external accounts/keys) and the most critical gate before public exposure. Observability remains queued (needs the user's Langfuse/Sentry keys, which can't be provisioned from a non-interactive session).

**Threat model:** no auth yet — the whole API is public, read-only analytics. So the real concerns are DoS, injection into the SQL/vector/LLM layers, and info disclosure; **not** authz/account-takeover (no accounts exist).

**Shipped (all in `RAG/security.py` as the single policy file, applied by `server.py`):**
- **Security headers** on every API response (nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, strict `default-src 'none'` CSP, Permissions-Policy, COOP/CORP, HSTS) + on the frontend via `next.config.ts` (safe subset; `poweredByHeader:false`).
- **Request body size cap** (64 KB → `413` before the body is read).
- **Input validation** on `ChatRequest`: `session_id`/`dump_ids`/filter-keys constrained to an identifier charset with length caps; `dump_ids` ≤100, filters ≤20, values ≤200 chars → malformed input `422`s at the schema boundary before reaching SQL/Qdrant.
- **SQL hardening** (`sql_engine.py`): keep only the first statement (`;`-split, blocks stacked injection), re-assert `SELECT`-only, single-quote-escape every interpolated `dump_id`/filter value (defense-in-depth for offline callers that bypass API validation).
- **Session-flood cap** (`session.py`): `MAX_SESSIONS=10_000` with LRU eviction.
- **CORS audit**: methods narrowed to `GET/POST/DELETE/OPTIONS`, headers to `Content-Type`, `allow_credentials=False` (no cookies used), `X-Request-ID` exposed.
- **Startup env validation** (`enforce_environment`): fail-fast in production on missing Qdrant/LLM keys or localhost `ALLOWED_ORIGINS`; warn in dev.
- **`SECURITY.md`** — full audit: implemented controls, a "reviewed & N/A with rationale" table (CSRF, cookies, SSRF, directory traversal, clickjacking, XSS, content-type), an honest prompt-injection posture section (mitigated, *not* solved), residual risks, and a pre-deploy manual checklist.
- **`robots.txt`** + **`.well-known/security.txt`** (placeholder contact, flagged for replacement).

**Found during validation (caught by re-testing, not assumed):**
- The `Server: uvicorn` header can't be stripped in app code — uvicorn injects it *after* the app returns. Corrected the misleading "removes it" comment; the real fix (`uvicorn --no-server-header`) is now a `SECURITY.md` checklist item + will go in the Dockerfile CMD. Every *app-level* header is correct.

**Regression-verified:** headers present; `413`/`422` rejections all return the standard `{success,error,message,request_id}` shape; dashboard still 254 (sector=Technology) / 2,376 (unfiltered); chat still returns SQL count 254 + correct answer; CORS preflight from `localhost:3000` succeeds with the narrowed methods. Frontend `tsc` clean.

**Deliberately deferred (documented, not silently skipped):**
- **Frontend blocking CSP** — the app uses inline `style={}` + Recharts injected styles, so a strict `style-src` would break rendering. Ship `Content-Security-Policy-Report-Only` first, tune against the live app, then enforce. This is the one frontend security item left open, called out in `SECURITY.md`.
- SSRF/traversal/CSRF/cookie controls — reviewed and genuinely N/A for the current design (no user-supplied URLs, no request-derived file paths, no cookies); documented with "revisit when" triggers rather than adding unused code.

**Manual review before deploy (from `SECURITY.md`):** set a real `security.txt` contact; set `ENVIRONMENT=production` + real `APP_VERSION` + non-localhost `ALLOWED_ORIGINS`; terminate TLS; run uvicorn `--no-server-header`; tune + enforce the frontend CSP; rotate any dev-shared keys; move rate-limit state to Redis when running multiple replicas (SlowAPI is per-process).

### Sprint 6 — Observability (retroactively logged 2026-07-07)

**This entry was missing from the log** — the work shipped (evidenced by `RAG/observability.py`'s own "Sprint 6" docstring, `RAG/tests/`, `.github/workflows/ci.yml`, `Dockerfile`s, and `docker-compose*.yml` all already existing in the repo) but was never written up here, in violation of this doc's own "living document" rule. Reconstructed from the code during the 2026-07-07 audit rather than from a contemporaneous note, so some rationale below is inferred, not quoted.

**Shipped:**
- **Prometheus** — genuinely active (`GET /metrics`), not just interface stubs: histograms for HTTP/LLM/SQL-generation/SQL-execution/embedding/Qdrant-search durations, counters for dashboard cache hits and captured exceptions, gauges for active sessions and process memory. Blocked from public access at the nginx layer in production.
- **Sentry** — coded and wired (`init_observability`, `capture_exception`), dormant until `SENTRY_DSN` is set; degrades to logging otherwise.
- **Langfuse** — coded and wired (`trace_llm_call` around the streaming chat completion), dormant until both `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` are set and the package is installed.
- Test suite (`RAG/tests/`): filter registry, session store, security policy, SQL scoping, chat request schema, plus a `live` marker for tests that need a running server + credentials.
- CI (`.github/workflows/ci.yml`): backend unit tests, frontend typecheck+build, advisory pip-audit/npm audit, Docker image builds (main branch only).
- `Dockerfile`s (backend + frontend), `docker-compose.yml` (dev) / `docker-compose.prod.yml` (nginx-fronted prod), `DEPLOYMENT.md`, `RUNBOOK.md`, `OBSERVABILITY.md`.

**Bug found during the 2026-07-07 audit:** `prometheus_client` is imported unconditionally at module load in `observability.py`/`server.py` but was missing from `RAG/requirements.txt` — a fresh clone or Docker build would have hit `ImportError` on startup despite `/metrics` being documented as "ACTIVE, no credentials needed." Fixed by adding `prometheus-client>=0.20.0` to `requirements.txt`.

**Still blocked (needs the user, not code):** Sentry/Langfuse activation needs real `SENTRY_DSN`/`LANGFUSE_PUBLIC_KEY`+`SECRET_KEY` values, which can't be provisioned from a non-interactive session.

### Sprint 7 — Frontend IA expansion (2026-07-07)

**Reordering note:** the user was handed a large "productionize everything, don't stop to ask" prompt from another AI session. Rather than executing it literally, it was audited against the real repo state first (see Sprint 6 entry above for what that audit found) and mapped back onto the sprint cadence. Two decisions came out of that check-in with the user: (1) the professor's standing guidance — "no more datasets/filters, package what exists" — still holds, so the mega-prompt's filter-expansion section (Employment Type/Experience Level/Company/Language/Salary Range/Remote/Education) was explicitly **not** built; (2) of the genuinely missing work, **Frontend IA expansion** (this sprint's original Sprint 3 scope, superseded once already) was picked as the next priority.

**Shipped:** the previously-missing routes, built "minimal initially" per the original Sprint 3 note — real content and real wiring, no placeholder/fake controls.
- **`/about`** — mission, institution, team table, GitHub/docs links. Content sourced from the root `README.md`, not invented.
- **`/research`** — methodology (SQL/analytics/semantic layers), architecture summary, technology stack (real model names/versions from `config/llm.py`), MCQ benchmark results (82.5% overall, real numbers from `RAG/mcq_summary.txt` — 83.0% EN / 82.0% AR, 76.3–86.1% by country), known limitations, future work, research foundation.
- **`/docs`** — links out to the Markdown docs in the repo (GitHub blob URLs) rather than duplicating their content, so nothing can drift out of sync.
- **`/settings`** — theme, language, and a persisted default AI model (`localStorage` key shared with the app shell via `lib/preferences.ts`; the app shell's own model picker now also writes this key, so either surface updates the same preference). Deliberately **no** temperature/top-p/max-tokens/reranker-toggle controls — the backend doesn't expose those knobs, and fake controls that don't do anything were treated as worse than no controls.
- **`/admin`** — a live-polling (10s) status view built entirely on the existing public `/health` endpoint, plus a link to raw `/metrics` (dev-only; nginx blocks it externally in prod). No new data is exposed beyond what `/health` already serves publicly — there's still no auth on this platform (see `SECURITY.md`), so this is explicitly a thin UI over already-public data, not a real gated admin portal.
- Shared `components/SiteHeader.tsx` (nav consistent across the five new pages), new `lib/site.ts` (factual project metadata: team, GitHub URL, benchmark numbers, tech stack, limitations — single source so pages can't drift from each other), nav links added to the landing page header/footer and the app shell header (⚙ Settings / 🛠 Admin icons).

**Deliberately deferred:** full Arabic translation of the new pages' body content. The shared header/nav (`SiteHeader`, landing page nav) is bilingual via the existing `i18n` system; the informational prose on About/Research/Docs/Settings/Admin is English-only for now rather than shipping a rushed machine translation of technical/methodology content for an Arabic-first institution.

**Verified:** `tsc --noEmit` clean; `eslint` clean on every new/modified file (pre-existing `lib/i18n.tsx`/`lib/theme.tsx` findings from Sprint 3's technical debt were left alone, per that sprint's documented scope decision); all 7 routes (`/`, `/app`, `/about`, `/research`, `/docs`, `/settings`, `/admin`) return HTTP 200 from the dev server with the expected page-specific content confirmed present (team names, benchmark numbers, doc links, health fields) and no compile/hydration errors in the dev server log. **Not done:** true visual/browser verification (dark/light theme rendering, RTL Arabic layout, responsive breakpoints) — no browser-automation tool was available in-session; recommend a manual look before treating this as fully closed.

**Technical debt / remaining gaps:**
1. Arabic translation of new page content (see "Deliberately deferred" above).
2. `/admin` has no authentication, matching the rest of the platform's current posture — revisit together with the platform-wide auth question if one is ever added.
3. The GitHub URL used on About/Docs (`AlbaraaAloush/ai-powered-job-market-intelligence`) was chosen as the apparent canonical team repo over the `origin` remote (`mhdfaizjabir/jobmarket_bot`) — a judgment call, not a confirmed fact; correct `frontend/lib/site.ts`'s `GITHUB_URL` if wrong.

### Sprint 8 — Interactive dashboard drill-down (2026-07-07)

**Reordering note:** the user was handed another large "productionize everything" mega-prompt from an external AI session. Per [[feedback_audit_before_mega_prompts]] this was audited against the real repo first rather than executed literally — most of the prompt's phases (CI/CD, Docker, docs, testing) turned out already shipped (Sprints 3–7). Of what remained, the professor's own explicit ask ("better interactive dashboard") was picked as Priority 1.

**Scope conflict surfaced and resolved with the user before building:** wiring chart clicks for Company/Salary/Employment Type/Career Level/Experience means adding each as an `explicit_filters` registry entry — exactly the "new filter types" work Sprint 2/3 deliberately did NOT build because of the professor's "no more datasets/filters, package what exists" guidance (see [[project_scope_constraint]]). Flagged this directly; user chose to proceed the same way `sector` was already built (hard exact-match filter via the registry), reasoning that the professor's own requirement list explicitly includes "better interactive dashboard" as a separate, still-open item distinct from the closed "no more filters" scope.

**Shipped:**
- `RAG/filter_registry.py`: five new entries — `employment_type` (→ `_employment_norm`, already computed), `career_level` (→ `_career_norm`, already computed — also resolves the Sprint 2 tech-debt item of two parallel career-level mechanisms), `company` (→ raw `company` column), `experience` (→ raw `experience` column), `salary_bucket` (→ new `_salary_bucket_norm`).
- `RAG/data_loader.py`: added the canonical salary parser/bucketer (`parse_salary_mid`, `norm_salary_bucket`, `SALARY_BUCKET_BINS/LABELS`) and wired `_salary_bucket_norm` into the same per-file ingestion pass as `_sector_norm`/`_employment_norm`/`_career_norm`. `RAG/server.py`'s dashboard salary-bracket code now imports these instead of keeping its own duplicate bins/labels/parser (there were previously three independent copies of this parser across `app.py`, `server.py`, and `analytics.py` — this reduces it to one canonical copy plus the two untouched legacy ones in `app.py`/`analytics.py`, left alone as out-of-scope).
- `RAG/server.py`'s `/api/dashboard`: now applies every registered explicit filter generically via `translate_explicit_filters()` (one new named query param per field, one shared filtering loop) instead of the old `sector`-only hardcoded branch — so a company/salary/experience click now re-filters *every* chart on the dashboard, not just the chatbot, matching how sector always worked.
- `frontend/lib/api.ts`: `DashboardParams`/`fetchDashboard` extended to send all six explicit filter fields as named query params.
- `frontend/components/Dashboard.tsx`: `HBar`/`VBar`/`Donut` now accept optional `filterKey`/`activeValue`/`onFilterChange` props — clicking a bar/segment toggles that filter, with dimmed/highlighted styling on the active selection and a clear-chip in the card header. Wired to Career Level, Employment Type, Salary Brackets, Top Hiring Companies, and Experience Required. The dataset-change reset effect now clears every explicit filter (previously sector-only).
- `frontend/lib/filters.ts`: new `FILTER_LABELS` map (mirrors each registry entry's `label`) so the chat header shows "employment type: Full-Time" instead of the raw wire key — closes Sprint 2's tech-debt item #4.
- `RAG/migrate_explicit_filters_payload.py`: new generalized backfill script (derives `_employment_norm`/`_career_norm`/`_salary_bucket_norm` from each point's already-stored raw payload field, same idempotent pattern as `migrate_sector_payload.py`). **Run against production Qdrant Cloud with the user's explicit go-ahead** (asked first, since it's a live write to ~30k production points): 15,074 employment_type, 22,678 career_level, and 1,602 salary_bucket points backfilled (remainder genuinely lack that source data).

**Deliberately NOT built:**
- **Skill click-filtering.** Postings carry a delimited multi-value skills string (parsed via regex split), not a single scalar column — the registry's exact-match semantics (SQL `col = value`, pandas `==`, Qdrant keyword-match index) only fit single-value fields. Supporting it needs CONTAINS/array-match semantics added across `sql_engine._scope_query`, `rag_engine._apply_filters`, and `rag_engine._matches_filter_metadata` — a real architecture extension, not "one registry entry," and the user's instruction was explicitly to reuse the existing architecture without redesigning it. Left for a future sprint.
- Company/experience/salary-bucket click-filtering does **not** need this caveat — those are already single-value columns.

**Verified (regression, API-level against a local dev server):** `sector=Technology` on `qatar_may_2026` → still 254 (unchanged from Sprint 1); no filters → still 2,376. New filters individually match their own chart's displayed count exactly (`employment_type=Full-Time` → 415, `company=Premium Solutions Consultancy` → 225, `salary_bucket=$500-1K` → 19), combine with AND semantics as expected (`sector=Technology` + `employment_type=Full-Time` → 7), and clearing all filters restores the 2,376 baseline. Chat SQL-layer counts match dashboard counts exactly for both a pre-migration field (company: 225/225) and a post-migration field (employment_type: 415/415); semantic hits were empty for `employment_type`/`career_level`/`salary_bucket` before the Qdrant backfill and non-empty after, confirming the migration was actually necessary and effective, not just cosmetic. `pytest -m "not live"` (37 tests), `tsc --noEmit`, and `next build` (all 8 routes) all pass clean. `eslint` shows zero *new* findings — the one remaining hit (`react-hooks/set-state-in-effect` on `Dashboard.tsx`'s existing dashboard-fetch effect) was confirmed via `git diff` to be pre-existing, unchanged code, same category as the already-documented Sprint 3 `lib/i18n.tsx`/`lib/theme.tsx` debt.

**Found during this session's testing, not caused by it (documented, not fixed — out of scope):** semantic-search hits returned by the chatbot are not reliably scoped to the selected `dump_ids` — a `sector=Technology` + `dump_ids=[qatar_may_2026]` query returned semantic hits from UAE/Saudi Arabia and later timelines alongside Qatar/May-2026 ones, even though the SQL-layer count (and thus the stated answer) was correct. Reproduced identically with the pre-existing `sector` filter, so this predates this session; Sprint 1's own verification only checked that hits matched the *sector*, never that they matched the *dump selection*. Worth a dedicated look — a hard Qdrant `_dump_id` pre-filter exists in the code (`rag_engine.py` ~line 1209) but doesn't appear to be constraining results as expected.

**Not done — no browser automation tool was available in this session** (only static HTML fetch, no real browser/screenshots/console-error capture): true visual verification of dark/light theme, mobile responsiveness, and Arabic RTL layout on the new clickable charts was not performed. Verified instead via: production `next build` succeeding for all 8 routes, `tsc --noEmit` clean, HTTP 200 on every route from a live dev server, and confirming (via `git diff`) that this sprint touched none of the theme/i18n/RTL infrastructure (`lib/theme.tsx`, `lib/i18n.tsx`, `layout.tsx` were untouched). Recommend an actual manual/browser pass before treating dashboard drill-down as fully closed — same caveat Sprint 1 and Sprint 7 both left open and neither has yet been picked up.

**Technical debt / remaining gaps:**
1. Semantic-hit dump scoping bug above (pre-existing, newly documented).
2. Skill click-filtering deferred (needs a CONTAINS-match extension to the filter architecture).
3. Real browser/visual QA (dark/light/RTL/mobile) still never performed for *any* sprint to date — recommend doing this once, covering everything built since Sprint 7, rather than repeatedly deferring it sprint by sprint.
4. `frontend/lib/filters.ts`'s `FILTER_LABELS` map must be kept in sync by hand with `RAG/filter_registry.py`'s `label` fields — no shared runtime between Python and the frontend to enforce this automatically.

### Sprint 9 — Semantic-hit dump-scoping fix + hybrid retrieval (2026-07-08)

**Context:** a fresh ground-truth audit (git log showed nothing committed since before Sprint 3 — see [[project_sprint_state]] for that finding, handled separately) surfaced two concrete, user-requested items: fix the Sprint 8 semantic-hit scoping bug, and build the BM25/hybrid retrieval + reranking the spec's "AI system improvements" section had never picked up.

**Root cause of the scoping bug (more specific than Sprint 8's note):** `get_retrieval_info()` — the function that powers the chat "sources shown" transparency panel — built its Qdrant `where` clause from `filters` only and **never merged in `_dump_id` scoping at all**, unlike the answer-generation path (`_build_full_context`), which did attempt it. That's why the stated answer numbers (SQL-backed) were always correct while the sources panel could show cross-country/timeline hits. Separately, `_build_full_context`'s own dump-scoping was fragile: its exception fallback dropped *all* filtering (including dump scope) on any Qdrant-side error (e.g. an unindexed field).

**Shipped:**
- `RAG/rag_engine.py`: two new pure helpers — `_merge_dump_filter()` (merges a hard `_dump_id` scope into a where clause, returning a dump-only fallback filter for graceful degradation) and `_dump_scoped()` (a local safety net that re-enforces `_dump_id` membership on results regardless of which Qdrant code path ran). Both call sites (`_build_full_context`, `get_retrieval_info`) now: try the combined filter → retry with dump-only on failure → retry fully unfiltered as a last resort → always locally re-filter by `_dump_id` before results are used. `get_retrieval_info` previously had none of this.
- Extracted `_narrow_by_soft_filters()` (country/timeline/explicit-filter narrowing) out of `_build_full_context`'s inline `summary_df` construction so `get_retrieval_info` could reuse the identical scoping logic for its own BM25 candidate pool, instead of a second hand-copied version.
- **`RAG/retrieval.py` (new module)** — hybrid retrieval: BM25 keyword search (`rank_bm25`, rebuilt per-request over the already dump/filter-scoped DataFrame — no persistent index, ~1s worst case for the full ~31k-row corpus, less once scoped) fused with the existing vector search via Reciprocal Rank Fusion, then an optional cross-encoder reranking pass (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` — multilingual EN/AR, same weight class as the existing embedding model). Wired into both `_build_full_context` (the answer path) and `get_retrieval_info` (the transparency panel, for consistency — it now shows the same ranking that informed the answer). Toggleable via `ENABLE_HYBRID_RETRIEVAL`/`ENABLE_RERANKER` env vars; both degrade to a no-op on failure (no network, model load error) rather than breaking retrieval.
- **Latency fix found during live verification, not assumed:** the first real `.encode()`/reranker-inference call in a fresh process paid a one-time ~15-20s CPU thread-pool warmup tax on this Windows dev machine. Originally this would have landed on whichever user's chat message happened to be first. Fixed by eager-warming both the embedding model (`VectorStore.__init__`) and the reranker (`warm_up_reranker()`, called from `server.py`'s startup lifespan right after `VectorStore()`) — paid once at boot instead. Adds roughly 15-20s to the documented ~30s cold start (now ~45-50s) — `DEPLOYMENT.md` updated.
- `RAG/requirements.txt`: added `rank_bm25>=0.2.2` (pure Python, ~9KB, only depends on numpy which was already a dependency). No new package needed for the reranker — `sentence-transformers` (already required) ships `CrossEncoder` alongside the bi-encoder `SentenceTransformer` already in use.
- Tests: `RAG/tests/test_rag_engine_dump_scoping.py` (6 tests — `_merge_dump_filter`/`_dump_scoped` behavior) and `RAG/tests/test_retrieval.py` (13 tests — BM25 ranking, RRF fusion incl. collision/identity edge cases, reranker ordering). The reranker-inference test skips (not fails) if the model can't load, mirroring the existing `live`-marker skip-if-unreachable pattern, so offline CI doesn't break on it.

**Verified (live, against real production data — not just unit tests):** started an isolated backend instance (port 8001, separate from any already-running dev server) against real Qdrant Cloud + Fanar credentials. Sent a real chat request scoped to `dump_ids=["qatar_may_2026"]` only, asking about software engineer jobs — every one of the 12 `semantic_hits` in the transparency panel came back `"country": "Qatar"`, `"timeline": "May 2026"` (previously the exact class of leak Sprint 8 documented). The streamed answer correctly cited only Qatar-scoped, dataset-grounded company names. Confirmed steady-state (warm) added latency from hybrid retrieval + reranking is ~1-2s total per request (measured via server-side batch timing before/after the warm-up fix — dropped from an unwarmed ~20-30s to ~1s once both models are pre-loaded). `pytest -m "not live"` (77 tests, 3 skipped, same 3 as before), `python -c "import ast; ast.parse(...)"` on every touched file, and a full manual walkthrough of the live SSE stream all passed.

**Not done / deferred:**
1. `answer_eval()` (used by the MCQ/offline benchmark, not the live chat path) was not updated to use hybrid retrieval — out of scope for this sprint's live-chat-focused fix; worth revisiting if the benchmark should reflect the same retrieval quality.
2. No re-run of the MCQ benchmark (`RAG/evaluate_mcq.py`) against the new retrieval pipeline to quantify whether hybrid+rerank actually improves the 82.5% overall score cited on `/research` — the live spot-check above confirms correctness (right country/timeline, no crashes, reasonable latency) but not a measured quality delta. Recommended next step if the benchmark numbers are going to be updated/re-cited anywhere.
3. Real browser/visual QA — still never done, same standing gap as every prior sprint.

### Sprint 10 — Observability activation prep (2026-07-08)

**Goal:** user chose to activate Sentry + Langfuse next. Before sending them off to create accounts and generate keys, audited the actual integration code against the currently-installed SDK versions (per [[feedback_audit_before_mega_prompts]]'s standing rule — don't assume "prepared, dormant" docs are still accurate).

**Found two real bugs, both fixed:**
1. **`sentry-sdk` was missing from `requirements.txt`** despite `OBSERVABILITY.md`/`.env.example` both claiming "sdk already installed" — it was only ambiently present in this dev machine's environment, not pinned. A fresh clone/Docker build would have `import sentry_sdk` silently fail (caught by the surrounding try/except, so no crash — but Sentry would never actually activate). Same bug class as the Sprint 6 `prometheus-client` miss. Fixed: added `sentry-sdk>=2.0.0` to `requirements.txt`.
2. **`observability.py`'s `trace_llm_call()` called `lf.start_span(name=..., metadata=...)`, a method that doesn't exist on the currently-published `langfuse` SDK (4.13.2).** Confirmed by installing the real package and inspecting the `Langfuse` class — the v3+ OTEL-based rewrite renamed this to `start_observation()`/`start_as_current_observation()`. The old call was silently swallowed by `trace_llm_call`'s own try/except, so a user who activated Langfuse would see "Langfuse LLM tracing ACTIVE" in the startup log and never get a single trace, with no visible error. Fixed: `lf.start_observation(name=name, as_type="generation", metadata=metadata)` — `as_type="generation"` is a bonus improvement over the old generic span, giving proper token/cost fields in the Langfuse UI since this always wraps an LLM completion. `sentry_sdk`'s API (`new_scope`, `capture_exception`, `init`) was checked against the installed 2.57.0 and is unaffected.

**Verified:** installed `langfuse` fresh and confirmed `start_span` genuinely doesn't exist on the class (`AttributeError`) before writing the fix, then confirmed `start_observation` does and returns an object with `.end()`. New `RAG/tests/test_observability.py` (4 tests, mocking `_langfuse_client()` — no real credentials needed) locks in the correct method name/call shape so this can't silently regress again. Full suite: 81 tests (77 + 4 new), all passing.

**Still needs the user, not code:** real `SENTRY_DSN` (from a Sentry.io project) and `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (from a cloud.langfuse.com project) — account creation can't happen from a non-interactive session. Once the user has real keys, the remaining step is a live verification (trigger a real error, confirm it lands in the Sentry dashboard; send a real chat message, confirm a trace lands in Langfuse) — not yet done since no real credentials exist yet.
