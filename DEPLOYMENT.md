# Deployment

How to run the platform locally, in Docker, and in production. The security
pre-deploy checklist lives in [SECURITY.md](SECURITY.md); operational
procedures in [RUNBOOK.md](RUNBOOK.md).

---

## 1. Local development (no Docker)

```bash
# Backend — from RAG/
cp .env.example .env          # fill in QDRANT_URL, QDRANT_API_KEY, FANAR_API_KEY / OPENAI_API_KEY
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --no-server-header

# Frontend — from frontend/
npm install
npm run dev                   # http://localhost:3000 (talks to localhost:8000)
```

First backend start takes ~45-50 s (loads ~30k postings, the embedding model,
and the hybrid-retrieval reranker — all three are eager-warmed at boot rather
than on a random user's first chat message; set `ENABLE_RERANKER=false` to
skip the reranker's share of that if the extra ~15-20s matters more than
reranking quality for your deploy). "Ready — N postings | N vectors in
Qdrant" in the log means it's up.

## 2. Docker (development stack)

```bash
cp RAG/.env.example RAG/.env  # fill in keys
docker compose up --build     # backend :8000, frontend :3000
```

The frontend image bakes `NEXT_PUBLIC_API_URL=http://localhost:8000` so the
browser calls the backend directly. Both containers have healthchecks; the
frontend waits for the backend to be healthy.

## 3. Docker (production stack)

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Topology — nginx is the only published port (80):

```
                    ┌─────────────────────── docker network ───────────────────────┐
Internet ──:80──▶ nginx ──▶ /            ──▶ frontend:3000  (Next.js standalone)   │
                    │  ──▶ /api/*, /health ──▶ backend:8000 (uvicorn, internal)    │
                    │  ──▶ /metrics  ──▶ 404 (scraped internally, never public)    │
                    └───────────────────────────────────────────────────────────────┘
```

Required in `RAG/.env` for production (the backend **refuses to boot** if these
are wrong — that's `security.enforce_environment()` doing its job):

| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `production` |
| `APP_VERSION` | your release tag (shown on `/health` and in Sentry) |
| `ALLOWED_ORIGINS` | the public origin, e.g. `https://jobs.example.org` — **not** localhost |
| `QDRANT_URL`, `QDRANT_API_KEY` | Qdrant Cloud cluster |
| `FANAR_API_KEY` and/or `OPENAI_API_KEY` | at least one LLM provider |
| `SENTRY_DSN` *(optional)* | enables error tracking (see OBSERVABILITY.md) |
| `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` *(optional)* | enables LLM tracing |

The frontend image is built with `NEXT_PUBLIC_API_URL=""` → same-origin
relative URLs; every request flows through nginx.

### TLS

Not configured in-repo (host-specific). Two options:
1. **Platform TLS** (Railway/Render/Fly/a cloud LB): terminate there, keep
   nginx on port 80 behind it. `--proxy-headers` is already set on uvicorn.
2. **Self-managed**: add a 443 server block + certs to `nginx/nginx.conf`
   (marked with a TODO) and publish 443 in the prod compose.

HSTS headers are already emitted by both apps and activate the moment TLS is live.

## 4. Environment separation

| | development | production |
|---|---|---|
| config validation | warns and continues | **fails to boot** on problems |
| `ALLOWED_ORIGINS` | localhost:3000 | public origin only (localhost rejected) |
| ports | backend+frontend published | nginx only |
| compose file | `docker-compose.yml` | `docker-compose.prod.yml` |

## 5. Data & index lifecycle

- Job data (`RAG/data/*.xlsx`) is baked into the backend image at build time.
- Vectors live in **Qdrant Cloud** — not in the image, not in a volume. The
  manifest (`chroma_db/_manifest.json`, hash of source files) is baked in so a
  fresh container recognises the index is already built and skips re-embedding.
- Adding a new data dump = drop the file in `RAG/data/`, run
  `python build_index.py` once (incremental — embeds only the new file),
  rebuild the backend image.

## 6. Backup & recovery

- **Source data**: the `.xlsx` files in git are the source of truth.
- **Vectors**: recoverable from source data at any time via `build_index.py`
  (full rebuild ≈ embedding 30k rows). Qdrant Cloud's own snapshots are the
  faster path — enable them in the cluster settings.
- **Sessions**: in-memory by design (2 h TTL); lost on restart. Acceptable for
  a stateless public assistant — nothing durable lives in the backend process.
- **Rollback**: images are immutable; keep the previous tag and
  `docker compose -f docker-compose.prod.yml up -d` with it.

## 7. Scaling notes (read before adding replicas)

Two things are per-process today and must move to shared stores before
horizontal scaling:
1. **Rate limits** (SlowAPI, in-memory) — effective limit multiplies by
   replica count. Move to Redis-backed storage.
2. **Sessions** (in-memory dict) — a second replica won't see the first's
   chat history. Move to Redis, or pin sessions to a replica (sticky LB).

Single-replica vertical scaling has no such constraints; the app is CPU-bound
on embedding (per chat request) and pandas (mitigated by the dashboard cache).
