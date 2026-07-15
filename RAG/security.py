"""
security.py
-----------
Security policy for the FastAPI backend, grouped in one auditable place and
documented in SECURITY.md:

  - response security headers (applied by server.py's request middleware)
  - request-size + input-validation bounds (used by the Pydantic models)
  - startup environment validation (fail-fast in production)

This module holds *policy* (the limits, the header set, the validation rules).
server.py *applies* it — so the whole security surface is reviewable here
without reading request-handling code.
"""

import os

from config import IS_PRODUCTION, get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request-size + input-validation bounds
# ---------------------------------------------------------------------------
# Chat request bodies are a question + a handful of ids/filters — a few hundred
# bytes in normal use. 64 KB is a generous ceiling that still rejects abuse
# (mega-payloads meant to exhaust memory or the LLM context) outright.
MAX_REQUEST_BYTES     = 64 * 1024

MAX_SESSION_ID_LEN    = 64
MAX_MODEL_LEN         = 100
MAX_DUMP_IDS          = 100
MAX_DUMP_ID_LEN       = 128
MAX_FILTERS           = 20
MAX_FILTER_KEY_LEN    = 64
MAX_FILTER_VALUE_LEN  = 200

# session_id and dump_id are server-generated / dataset-derived identifiers —
# constraining them to this charset at the API boundary means they can never
# carry SQL/Qdrant metacharacters into the layers that interpolate them.
IDENTIFIER_PATTERN    = r"^[A-Za-z0-9_\-]+$"


# ---------------------------------------------------------------------------
# Response security headers
# ---------------------------------------------------------------------------
# The API returns JSON only and never renders HTML in a browser context, so a
# maximally-restrictive CSP is safe here (unlike the frontend, which renders a
# real app — see SECURITY.md for why the frontend CSP is handled separately).
# HSTS is a no-op over plain HTTP (browsers ignore it on http://) and takes
# effect automatically once the service is behind TLS.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options":       "nosniff",
    "X-Frame-Options":              "DENY",
    "Referrer-Policy":              "no-referrer",
    "Content-Security-Policy":      "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Permissions-Policy":           "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy":   "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Strict-Transport-Security":    "max-age=63072000; includeSubDomains",
}


def apply_security_headers(response) -> None:
    """Set security headers on a response without clobbering any already present."""
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    # Drop any app-level Server header. NOTE: uvicorn injects its own
    # `Server: uvicorn` *after* the app returns, so this does NOT remove that
    # one — it must be suppressed at the server layer with uvicorn's
    # `--no-server-header` flag (documented in SECURITY.md / the Dockerfile CMD).
    if "server" in response.headers:
        del response.headers["server"]


# ---------------------------------------------------------------------------
# Startup environment validation
# ---------------------------------------------------------------------------
def validate_environment() -> list[str]:
    """
    Return a list of configuration problems (empty = healthy). The caller
    decides severity: fatal in production, warning in development.
    """
    problems: list[str] = []

    if not os.getenv("QDRANT_URL"):
        problems.append("QDRANT_URL is not set — vector search will fail.")
    if not os.getenv("QDRANT_API_KEY"):
        problems.append("QDRANT_API_KEY is not set — vector search will fail.")
    if not (os.getenv("FANAR_API_KEY") or os.getenv("OPENAI_API_KEY")):
        problems.append("No LLM key set — set FANAR_API_KEY and/or OPENAI_API_KEY.")

    if IS_PRODUCTION:
        origins = os.getenv("ALLOWED_ORIGINS", "")
        if not origins.strip():
            problems.append("ALLOWED_ORIGINS is empty in production — CORS will block the frontend.")
        elif "localhost" in origins or "127.0.0.1" in origins:
            problems.append("ALLOWED_ORIGINS still points at localhost in production.")

    return problems


def enforce_environment() -> None:
    """
    Validate env at startup. In production, raise on any problem so a
    misconfigured service refuses to boot rather than serving broken/insecure.
    In development, log warnings and continue.
    """
    problems = validate_environment()
    if not problems:
        logger.info("Environment validation passed.")
        return
    for p in problems:
        logger.warning("Environment problem: %s", p)
    if IS_PRODUCTION:
        raise RuntimeError(
            "Refusing to start in production with configuration problems: "
            + "; ".join(problems)
        )
