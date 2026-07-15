"""
config package
---------------
Centralized configuration, split by concern:

  config/settings.py — paths, environment, CORS, retrieval tuning, static data constants
  config/llm.py       — model/client config + system-prompt construction
  config/logging.py   — structured logging setup (see get_logger/configure_logging)

Every name below is re-exported at the package level so existing call sites
(`from config import DATA_DIR, make_client`, etc.) keep working unchanged —
this package replaces the old single-file config.py without touching any of
its consumers.
"""

from .settings import (
    ALLOWED_ORIGINS,
    APP_VERSION,
    BASE_DIR,
    CHROMA_COLLECTION,
    CHROMA_DIR,
    COLUMN_ALIASES,
    COUNTRY_COLORS,
    COUNTRY_FLAGS,
    DATA_DIR,
    DESCRIPTION_TRUNCATE,
    ENVIRONMENT,
    IS_PRODUCTION,
    TOP_K,
)
from .llm import (
    AVAILABLE_MODELS,
    CHAT_MODEL,
    EMBEDDING_MODEL,
    FANAR_API_KEY,
    FANAR_BASE_URL,
    INTERNAL_MODEL,
    OPENAI_API_KEY,
    SYSTEM_PROMPT,
    build_system_prompt,
    make_client,
)
from .logging import configure_logging, get_logger, set_request_id, set_session_id

__all__ = [
    "ALLOWED_ORIGINS", "APP_VERSION", "BASE_DIR", "CHROMA_COLLECTION", "CHROMA_DIR",
    "COLUMN_ALIASES", "COUNTRY_COLORS", "COUNTRY_FLAGS", "DATA_DIR", "DESCRIPTION_TRUNCATE",
    "ENVIRONMENT", "IS_PRODUCTION", "TOP_K",
    "AVAILABLE_MODELS", "CHAT_MODEL", "EMBEDDING_MODEL", "FANAR_API_KEY", "FANAR_BASE_URL",
    "INTERNAL_MODEL", "OPENAI_API_KEY", "SYSTEM_PROMPT", "build_system_prompt", "make_client",
    "configure_logging", "get_logger", "set_request_id", "set_session_id",
]
