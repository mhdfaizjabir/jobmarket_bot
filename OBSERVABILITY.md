# Observability

Three tiers, one interface (`RAG/observability.py`). Call sites never check
whether a backend is enabled — routing happens in that one file, so enabling
Sentry or Langfuse later touches **only `.env`**, zero code.

| Tier | Status | Enable by |
|---|---|---|
| Prometheus metrics | **ACTIVE** (no credentials needed) | nothing — always on at `/metrics` |
| Sentry error tracking | prepared, dormant | set `SENTRY_DSN` in `RAG/.env` (sdk already a dependency) |
| Langfuse LLM tracing | prepared, dormant | set `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` in `RAG/.env` (already a dependency) |

Startup logs state the posture explicitly — look for:
`Sentry ... / Langfuse ... / Prometheus metrics ACTIVE at /metrics.`

---

## Prometheus

`GET /metrics` (text exposition). **Blocked from public access by nginx in
production** — point your Prometheus at the backend container directly
(`backend:8000/metrics` on the compose network).

### Metric families

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_request_duration_ms` | histogram | `path`, `status` | every request, recorded by the logging middleware |
| `llm_call_duration_ms` | histogram | `call`, `model` | full streaming chat completion, wall time |
| `sql_generation_duration_ms` | histogram | — | text-to-SQL LLM call |
| `sql_execution_duration_ms` | histogram | — | SQLite execution of the generated query |
| `embedding_duration_ms` | histogram | — | query embedding (SentenceTransformer) |
| `qdrant_search_duration_ms` | histogram | — | Qdrant REST search round-trip |
| `dashboard_cache_total` | counter | `result` = hit\|miss | dashboard response cache effectiveness |
| `exceptions_captured_total` | counter | `type` | exceptions routed through `capture_exception` |
| `active_sessions` | gauge | — | in-memory chat sessions (refreshed at scrape) |
| `process_memory_mb` | gauge | — | RSS of the API process (refreshed at scrape) |
| `app_info` | gauge | `version`, `environment` | constant 1 — join it for dashboards |

Histogram buckets are ms-scaled up to 60 s (LLM streams are slow by nature).

### Useful queries

```promql
# p95 API latency by route
histogram_quantile(0.95, sum(rate(http_request_duration_ms_bucket[5m])) by (le, path))

# error rate
sum(rate(http_request_duration_ms_count{status=~"5.."}[5m]))
  / sum(rate(http_request_duration_ms_count[5m]))

# dashboard cache hit ratio
sum(rate(dashboard_cache_total{result="hit"}[15m]))
  / sum(rate(dashboard_cache_total[15m]))

# mean LLM stream duration by model
rate(llm_call_duration_ms_sum[15m]) / rate(llm_call_duration_ms_count[15m])
```

Grafana: any standard FastAPI/Prometheus dashboard works against
`http_request_duration_ms`; add panels for the RAG-specific families above.

---

## Sentry

`init_observability()` (called at startup) initializes Sentry when
`SENTRY_DSN` is set: error tracking only (`traces_sample_rate=0`, perf stays
with Prometheus/Langfuse), `send_default_pii=False`, release =`APP_VERSION`,
environment = `ENVIRONMENT`. Every unhandled exception already flows through
`capture_exception()` (global handler in `server.py`) with path/method tags.

## Langfuse

`trace_llm_call("rag_engine.answer", model=...)` already wraps the streaming
chat completion. When keys are configured **and** the package is installed, it
emits a span per call; otherwise it degrades to a debug log + the Prometheus
histogram (which records regardless). Startup warns explicitly if keys are set
but the package is missing.

Scope note: today this traces the *answer* call. Extending to the decompose
and SQL-generation calls is the same one-line wrap in `rag_engine._decompose`
/ `sql_engine._to_sql` when full trace trees are wanted.

## OpenTelemetry — deliberate deferral

Not wired. Reasoning: OTel only pays off with a collector/backend to export
to (an external decision), it would double-instrument what Prometheus +
request-IDs already cover for a single-service deployment, and it adds six+
packages. The attach point is ready — `_request_logging_middleware` in
`server.py` is where a tracer wraps every request, and `X-Request-ID` is the
correlation key logging already uses. Revisit when there's more than one
service or a chosen tracing backend.

## Log ↔ metric ↔ error correlation

Every request: one access-log line `req=<uuid> sess=<id> dur=Xms`, the same
UUID in the `X-Request-ID` response header, in every error body, and (when
Sentry is on) available to attach as an event tag. A user-reported error can
be traced from their error message's `request_id` straight to the log line.

**Known gap** (documented since Sprint 3): log calls made *inside*
`run_in_executor`/raw threads (deep RAG pipeline) show `req=- sess=-` —
contextvars don't cross thread boundaries automatically. The access log and
error bodies are unaffected. Fix (contextvars.copy_context) tracked in
PROJECT_SPEC.md technical debt.
