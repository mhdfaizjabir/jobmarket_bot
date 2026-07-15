# Security

This document is the security audit and posture for the GCC AI Job Market
Intelligence Platform as of Sprint 5. It states what is implemented, what was
reviewed and deemed not-applicable (and *why*), the residual risks, and the
manual steps required before a real public deployment.

Scope: a FastAPI backend (the data/LLM/vector surface) and a Next.js frontend
(static/SSR HTML). No authentication exists yet — everything is public, read-only
job-market analytics. This shapes the threat model: the primary concerns are
denial-of-service, injection into the SQL/vector/LLM layers, and information
disclosure — **not** account takeover or authorization bypass (there are no
accounts or privileged actions yet).

---

## 1. Implemented controls

### Transport & headers
- **Security headers on every API response** (`RAG/security.py` → applied in `server.py`'s request middleware): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a strict `Content-Security-Policy` (`default-src 'none'`), `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, and `Strict-Transport-Security`. The `Server` header is stripped.
- **Security headers on the frontend** (`frontend/next.config.ts`): `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS; `X-Powered-By` removed via `poweredByHeader: false`.
- **HSTS** is emitted but only takes effect once served over TLS (browsers ignore it on plain HTTP) — no action needed beyond terminating TLS at the proxy/host.

### Rate limiting & DoS
- **Per-IP rate limiting** via SlowAPI: 200/min global, 30/min on `/api/chat` (the expensive LLM path).
- **Request body size cap**: 64 KB, rejected with `413` before the body is read (`server.py` middleware).
- **Session-store cap**: `MAX_SESSIONS = 10_000` with least-recently-seen eviction (`session.py`), bounding memory against a session-flood (chat auto-creates sessions and rate limiting is per-IP only).
- **Per-session message cap** (20) and **2-hour idle TTL** with background cleanup — pre-existing, bounds per-session memory.

### Input validation (reject at the boundary)
- **Pydantic schema validation** on `ChatRequest` (`server.py`): `session_id` constrained to `^[A-Za-z0-9_\-]+$`, max 64 chars; `model` max 100; `dump_ids` capped at 100 items, each an identifier ≤128 chars; `filters` capped at 20 entries with identifier keys and values ≤200 chars. Malformed input → `422` in the standard error shape.
- **Filter registry allow-list**: unknown filter keys are silently dropped by `translate_explicit_filters` (`filter_registry.py`) — only registered filters ever reach any layer.
- **Question length**: friendly `400` at 2,000 chars (handler), hard-bounded by the 64 KB body cap.

### Injection defense
- **SQL** (`sql_engine.py`): the LLM-generated query runs read-only against an ephemeral, single-table in-memory SQLite copy. Additional hardening: only the first statement is kept (`;`-split) to block stacked-statement injection, the query must begin with `SELECT`, a `LIMIT` is force-injected, and every value interpolated into the scope subquery (`dump_ids`, filter values) is single-quote-escaped — layered on top of the boundary validation above.
- **Vector search** (`vector_store.py` / `rag_engine.py`): filters are structured dicts converted to Qdrant's typed filter API (not string-concatenated), and unindexed-field errors fall back to an unfiltered search + local post-filter rather than failing.
- **Prompt injection**: see §3 — partial mitigation, documented honestly.

### Secrets & configuration
- `.env` / `.env.local` / `*.env` are git-ignored at both repo root and `RAG/`. An `.env.example` documents required keys without values.
- **Startup environment validation** (`security.enforce_environment`): missing `QDRANT_URL`/`QDRANT_API_KEY`, absence of any LLM key, or a localhost `ALLOWED_ORIGINS` in production → hard failure to boot in production, warnings in development.
- **CORS**: origins from `ALLOWED_ORIGINS` (never `*`); methods narrowed to `GET/POST/DELETE/OPTIONS`; headers to `Content-Type`; `allow_credentials=False` (no cookies are used). `X-Request-ID` is exposed for support.
- **Log hygiene**: request logs contain only method/path/status/duration/ids — never bodies, keys, or question text. Full tracebacks go to logs only; clients get the generic error shape (§ error handling below).

### Error handling
- Every error path (`RateLimitExceeded`, `HTTPException`/404, `RequestValidationError`, catch-all `Exception`) returns `{success, error, message, request_id}` — **never** a stack trace. The catch-all logs the traceback server-side and routes it to `observability.capture_exception` (Sentry-ready).

---

## 2. Reviewed and not applicable (with rationale)

These common checklist items were reviewed and require **no code** because the
current design has no corresponding attack surface. Documented so a reviewer
doesn't mistake absence for oversight.

| Control | Why N/A today | Revisit when |
|---|---|---|
| **CSRF tokens** | No cookies/sessions in the browser; `session_id` travels in the JSON request body, and CORS `allow_credentials=False`. There is no ambient authority for a forged request to abuse. | Any cookie-based auth is added. |
| **Secure/HttpOnly cookies** | No cookies are set. | Auth is added. |
| **SSRF protection** | The backend makes outbound calls only to fixed, config-provided hosts (Qdrant, Fanar/OpenAI). No user input is ever used as a URL or fetched. | Any feature fetches a user-supplied URL (e.g. "analyze this job posting URL"). |
| **Directory traversal / safe file handling** | No request path or parameter is used to build a filesystem path. Data files are discovered by a fixed `DATA_DIR` glob at startup only. | Admin dataset upload (planned) — must validate filenames/paths then. |
| **Clickjacking** | Covered by `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`. | — |
| **Output sanitization (XSS)** | The API returns JSON, not HTML. The frontend renders assistant text through `react-markdown` **without** `dangerouslySetInnerHTML` (verified in `Chat.tsx`), so model output is not evaluated as HTML. | Any switch to raw HTML rendering. |
| **Content-Type validation** | FastAPI requires `application/json` for the body models; a wrong type yields `422` automatically. | — |

---

## 3. Prompt-injection posture (honest limitations)

This is a RAG system, so two injection vectors exist and neither is *fully*
solvable today:

1. **User-input injection** — a question crafted to override the system prompt.
   Mitigations: the user question is passed as a clearly-labelled `USER QUESTION`
   field separate from the system prompt and the retrieved `DATA CONTEXT`; the
   system prompt is authoritative and instructs the model to answer only from
   provided data. This raises the bar but is **not** a guarantee — LLMs can still
   be talked out of instructions.
2. **Retrieved-content injection** — a malicious job posting whose text contains
   instructions. Our corpus is curated Bayt/LinkedIn data (not open user uploads),
   so this vector is currently low-risk. It becomes real if/when the admin upload
   pipeline (planned) ingests untrusted sources.

**Explicitly not claimed**: prompt-injection is not "solved." The system limits
blast radius (read-only data, no tools/actions the model can invoke, no secrets
in context) rather than guaranteeing the model can't be manipulated into an
off-topic or awkward answer. Output-side guards already in place — grounded
company-name allow-lists, numeric verification in eval, "only use figures in the
context" instructions — reduce fabrication but are not security boundaries.

---

## 4. Residual risks & manual review checklist

Before any real public deployment:

- [ ] **Set a real `security.txt` contact.** `frontend/public/.well-known/security.txt` ships with a placeholder `security@example.com` and a `2027-01-01` expiry — replace both. A security.txt pointing at an unmonitored inbox is worse than none.
- [ ] **Set production env**: `ENVIRONMENT=production`, a real `APP_VERSION`, and a non-localhost `ALLOWED_ORIGINS` (the app will refuse to boot otherwise — by design).
- [ ] **Terminate TLS** at the proxy/host so HSTS and secure transport actually apply.
- [ ] **Run uvicorn with `--no-server-header`** (and `--proxy-headers` behind a reverse proxy). App-level code can't strip uvicorn's `Server: uvicorn` header — it's added after the app returns. This goes in the Dockerfile/production CMD (deployment sprint).
- [ ] **Tune a real CSP for the frontend** (the one deferred item): the app uses inline `style={}` + Recharts, so ship a `Content-Security-Policy-Report-Only` first, watch the violation reports against the live app, then promote to enforcing. Do **not** blindly add a strict `style-src` — it will break rendering.
- [ ] **Rotate any keys** that were ever committed or shared during development.
- [ ] **Decide the Qdrant/LLM egress**: outbound is currently unrestricted at the network layer. If deploying somewhere with egress controls, allow-list only the Qdrant + LLM provider hosts.
- [ ] **Load-test the rate limits** against expected traffic — 30/min on chat is conservative and may need tuning.

Known residual (accepted for now, no auth yet):
- The entire API is unauthenticated and world-readable. This is intentional for a
  public research showcase, but it means rate limits are the *only* abuse control.
- SlowAPI limits are per-IP and in-process (not shared across replicas). Behind a
  load balancer with multiple backend replicas, effective limits multiply by the
  replica count — move to a shared store (Redis) when scaling horizontally.

---

## 5. Responsible disclosure

If you find a vulnerability, please contact the security address in
`/.well-known/security.txt` (once set) rather than opening a public issue. We aim
to acknowledge reports promptly and will credit reporters who wish to be named.
