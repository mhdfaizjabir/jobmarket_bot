"""
config/logging.py
------------------
Structured logging setup for the whole service. Every log line carries
timestamp, level, module, request_id, session_id, and (where applicable)
duration_ms — request_id/session_id are populated automatically for any log
call made during a request via contextvars set by the request middleware
(see server.py), so individual call sites never need to pass them explicitly.

Designed as the single seam where an observability backend plugs in later:
Langfuse/Sentry/OpenTelemetry can each attach their own logging.Handler here
(see observability.py) without touching call sites elsewhere in the codebase.
"""

import logging
import os
import sys
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_session_id_var: ContextVar[str] = ContextVar("session_id", default="-")

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "req=%(request_id)s sess=%(session_id)s%(duration_str)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def set_session_id(session_id: str) -> None:
    _session_id_var.set(session_id)


def get_request_id() -> str:
    return _request_id_var.get()


class _ContextFilter(logging.Filter):
    """Injects request_id/session_id (and duration_ms if the caller passed one via `extra=`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        record.session_id = _session_id_var.get()
        duration_ms = getattr(record, "duration_ms", None)
        record.duration_str = f" dur={duration_ms:.1f}ms" if duration_ms is not None else ""
        return True


def configure_logging(level: str | None = None) -> None:
    """
    Configure the root logger once. Safe to call multiple times (e.g. from
    both server.py and a script) — later calls are no-ops.
    """
    global _configured
    if _configured:
        return

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [handler]  # replace any default handlers to avoid duplicate lines

    # Quiet noisy third-party loggers unless explicitly debugging.
    if log_level != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper around logging.getLogger for a consistent import path."""
    configure_logging()
    return logging.getLogger(name)
