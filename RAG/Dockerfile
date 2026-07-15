# Backend image — FastAPI + RAG pipeline.
#
# Build from the RAG/ directory:  docker build -t gcc-jobs-api ./RAG
#
# Notes:
#  - torch is installed from the CPU-only index first: sentence-transformers
#    would otherwise pull the CUDA build (~2.5 GB) for a container with no GPU.
#  - The embedding model is baked into the image so cold starts don't depend
#    on a ~470 MB Hugging Face download at runtime (adds size, buys determinism).
#  - Secrets are NOT baked — pass them at runtime via env_file/environment.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/appuser/.cache/huggingface

WORKDIR /app

# CPU-only torch first (see note above), then the rest of the requirements.
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

# Non-root user before model download so the cache lands in its home dir.
RUN useradd --create-home appuser
USER appuser

# Bake the embedding model into the image layer.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# App code last — changes here don't invalidate the heavy layers above.
COPY --chown=appuser:appuser . .

EXPOSE 8000

# Startup loads ~30k rows + the embedding model: give the healthcheck a
# generous start period before it begins counting failures.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

# --no-server-header: see SECURITY.md (can't be stripped at app level)
# --proxy-headers: trust X-Forwarded-* from the nginx container in front
CMD ["python", "-m", "uvicorn", "server:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-server-header", "--proxy-headers"]
