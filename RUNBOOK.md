# Runbook

Operational procedures for whoever is on the hook when something breaks.
Assumes the production compose stack ([DEPLOYMENT.md](DEPLOYMENT.md)).

## Start / stop / status

```bash
docker compose -f docker-compose.prod.yml up -d          # start
docker compose -f docker-compose.prod.yml down            # stop
docker compose -f docker-compose.prod.yml ps              # status + health
docker compose -f docker-compose.prod.yml logs -f backend # follow logs
curl -s localhost/health | python -m json.tool            # quick check
```

Healthy startup log sequence: `Environment validation passed.` →
`Sentry/Langfuse/Prometheus...` posture lines → `Ready — N postings | N vectors in Qdrant`.

## Reading the logs

Format: `timestamp | LEVEL | module | req=<uuid> sess=<id> dur=Xms | message`.
A user error report includes a `request_id` — grep for it:

```bash
docker compose -f docker-compose.prod.yml logs backend | grep <request_id>
```

`req=- sess=-` on deep pipeline lines is a known limitation (thread-boundary
contextvars), not a bug in your incident.

## Failure scenarios

### Backend won't boot, exits immediately
Almost always `enforce_environment()` refusing a bad production config —
the log names the exact problem (missing Qdrant/LLM keys, localhost in
`ALLOWED_ORIGINS`). Fix `RAG/.env`, restart. This is intentional fail-fast.

### `/health` shows `"qdrant_status": "error"` or `"vectors": 0`
Qdrant Cloud unreachable or the collection is gone.
- Check cluster status at cloud.qdrant.io; verify `QDRANT_URL`/`QDRANT_API_KEY`.
- Chat degrades but does not crash: vector search errors fall back to
  SQL/pandas-only answers (semantic hits disappear from the retrieval panel).
- If the collection was deleted: `cd RAG && python build_index.py` re-embeds
  everything (~30k rows), or restore a Qdrant Cloud snapshot.

### Chat returns `[Error: ...]` tokens or empty answers
LLM provider issue (Fanar/OpenAI outage, expired key, timeout).
- Check `exceptions_captured_total` on `/metrics` and the log around the request.
- Verify the key; try the other provider via the UI model selector.
- Timeouts: `LLM_TIMEOUT_SECONDS` (default 30) may be too tight for long answers.

### Everything 429
Per-IP rate limit (200/min global, 30/min chat). One legitimate NAT'd campus
IP can trip this. Limits live in `server.py` (`default_limits`, chat
decorator). Raise deliberately; remember they're per-process.

### Frontend loads but "Could not reach the server"
- Same origin? In prod the frontend must be built with `NEXT_PUBLIC_API_URL=""`.
- CORS: exact public origin (scheme + host) must be in `ALLOWED_ORIGINS`.
- Check nginx: `docker compose -f docker-compose.prod.yml logs nginx`.

### Streaming answers arrive all-at-once at the end
A proxy is buffering the SSE stream. In-repo nginx already sets
`proxy_buffering off` on `/api/chat` — check any *additional* proxy/CDN in
front (Cloudflare needs the response header `X-Accel-Buffering: no` or an
equivalent rule).

### Memory climbing
`process_memory_mb` on `/metrics`. Baseline ≈1–1.3 GB (dataframe + embedding
model). Bounded stores: sessions (10k LRU), dashboard cache (256 entries).
A leak beyond that: capture `/metrics`, restart (`docker compose restart
backend` — sessions are ephemeral by design), investigate offline.

## Routine operations

### Adding a monthly data dump
```bash
# 1. drop the new file into RAG/data/  (naming convention in RAG/data_loader.py)
cd RAG && python build_index.py        # incremental — embeds only the new file
# 2. rebuild + redeploy the backend image
docker compose -f docker-compose.prod.yml up --build -d backend
```

### Rotating secrets
Update `RAG/.env` → `docker compose -f docker-compose.prod.yml up -d backend`
(recreates the container; images never contain secrets). Rotate Qdrant keys in
their console first, then here.

### Upgrading dependencies
Bump pins in `RAG/requirements.txt` / `frontend/package.json` on a branch —
CI runs tests, audits, and image builds; the live pytest suite
(`cd RAG && pytest`) against a staging stack is the final gate.

## Escalation data to collect
`/health` body · `/metrics` snapshot · backend logs around the failing
`request_id` · the request body that reproduces it (chat bodies are not
logged — ask the reporter).
