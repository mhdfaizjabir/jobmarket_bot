"""
observability.py
-----------------
Live observability layer (Sprint 6). Three tiers, one interface:

  1. Prometheus (ACTIVE, no credentials needed)
     - record_metric(name, value, **tags)   -> Histogram observation (durations/values)
     - increment_counter(name, **tags)      -> Counter increment (events: cache hits, errors)
     - render_prometheus()                  -> text exposition for GET /metrics

  2. Sentry (PREPARED — activates automatically when SENTRY_DSN is set in .env;
     sentry-sdk is already in the environment)
     - init_observability() wires it at startup
     - capture_exception(exc, **ctx) forwards to Sentry when enabled, logs otherwise

  3. Langfuse (PREPARED — activates when LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY
     are set AND the `langfuse` package is installed; no-op logger otherwise)
     - trace_llm_call(name, **metadata) wraps every chat completion already

Call sites elsewhere in the codebase never check whether a backend is enabled —
they call these functions unconditionally and the routing happens here. Adding
credentials later requires zero changes outside this file and .env.
"""

import os
import time
from contextlib import contextmanager
from threading import Lock

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from config import APP_VERSION, ENVIRONMENT, get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus — ACTIVE
# ---------------------------------------------------------------------------
# Dedicated registry (not the global default) so repeated imports in tests or
# reloads never trip "duplicated timeseries" errors, and /metrics exposes only
# what this app deliberately records.
REGISTRY = CollectorRegistry()

# Millisecond buckets sized for this app's reality: dashboard aggregations run
# 10–300 ms, vector search 50–500 ms, full LLM streams 5–60 s.
_MS_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, float("inf"))

_metrics_lock = Lock()
_histograms: dict[tuple, Histogram] = {}
_counters: dict[tuple, Counter] = {}

# Gauges refreshed at scrape time by render_prometheus() via the callables
# registered in set_gauge_sources() — server.py hands us closures over its
# app state so this module never imports server internals.
_g_app_info = Gauge("app_info", "Static app metadata (value is always 1)",
                    ["version", "environment"], registry=REGISTRY)
_g_app_info.labels(version=APP_VERSION, environment=ENVIRONMENT).set(1)

_g_memory   = Gauge("process_memory_mb", "Resident memory of the API process in MB", registry=REGISTRY)
_g_sessions = Gauge("active_sessions", "Chat sessions currently held in memory", registry=REGISTRY)

_gauge_sources: dict[str, object] = {}


def set_gauge_sources(memory_mb=None, active_sessions=None) -> None:
    """Register zero-arg callables used to refresh gauges at scrape time."""
    if memory_mb is not None:
        _gauge_sources["memory_mb"] = memory_mb
    if active_sessions is not None:
        _gauge_sources["active_sessions"] = active_sessions


def _get_histogram(name: str, label_names: tuple[str, ...]) -> Histogram:
    key = (name, label_names)
    with _metrics_lock:
        h = _histograms.get(key)
        if h is None:
            h = Histogram(name, f"{name} (auto-registered)", list(label_names),
                          buckets=_MS_BUCKETS, registry=REGISTRY)
            _histograms[key] = h
        return h


def _get_counter(name: str, label_names: tuple[str, ...]) -> Counter:
    key = (name, label_names)
    with _metrics_lock:
        c = _counters.get(key)
        if c is None:
            c = Counter(name, f"{name} (auto-registered)", list(label_names),
                        registry=REGISTRY)
            _counters[key] = c
        return c


def record_metric(metric_name: str, value: float, **tags) -> None:
    """
    Observe a value (typically a duration in ms) into a Prometheus histogram.
    First parameter is deliberately named `metric_name` (not `name`) so a tag
    literally called name= can never collide with it — that exact collision
    silently ate the llm_call_duration metric until caught in testing.
    """
    try:
        label_names = tuple(sorted(tags))
        h = _get_histogram(metric_name, label_names)
        if label_names:
            h.labels(**{k: str(tags[k]) for k in label_names}).observe(value)
        else:
            h.observe(value)
    except Exception:
        # Metrics must never take down a request path.
        logger.warning("record_metric failed for %s", metric_name, exc_info=True)


def increment_counter(metric_name: str, **tags) -> None:
    """Increment a Prometheus counter (cache hits, error events, ...)."""
    try:
        label_names = tuple(sorted(tags))
        c = _get_counter(metric_name, label_names)
        if label_names:
            c.labels(**{k: str(tags[k]) for k in label_names}).inc()
        else:
            c.inc()
    except Exception:
        logger.warning("increment_counter failed for %s", metric_name, exc_info=True)


def render_prometheus() -> bytes:
    """Refresh scrape-time gauges and return the Prometheus text exposition."""
    try:
        fn = _gauge_sources.get("memory_mb")
        if fn:
            val = fn()
            if val is not None:
                _g_memory.set(val)
        fn = _gauge_sources.get("active_sessions")
        if fn:
            _g_sessions.set(fn())
    except Exception:
        logger.debug("gauge refresh failed", exc_info=True)
    return generate_latest(REGISTRY)


# ---------------------------------------------------------------------------
# Sentry — PREPARED (activates when SENTRY_DSN is set)
# ---------------------------------------------------------------------------
_sentry_active = False


def init_observability() -> None:
    """
    Called once from server lifespan. Activates whichever external backends
    have credentials configured; logs what's active so a deploy's log line
    makes the observability posture explicit.
    """
    global _sentry_active

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=dsn,
                environment=ENVIRONMENT,
                release=APP_VERSION,
                # Error tracking only for now — perf tracing stays with
                # Prometheus/Langfuse to avoid double-instrumenting.
                traces_sample_rate=0.0,
                send_default_pii=False,
            )
            _sentry_active = True
            logger.info("Sentry error tracking ACTIVE (environment=%s)", ENVIRONMENT)
        except Exception:
            logger.exception("SENTRY_DSN is set but Sentry init failed — continuing without it")
    else:
        logger.info("Sentry not configured (set SENTRY_DSN to enable).")

    if _langfuse_configured():
        if _langfuse_client() is not None:
            logger.info("Langfuse LLM tracing ACTIVE.")
        else:
            logger.warning(
                "LANGFUSE_PUBLIC_KEY/SECRET_KEY are set but the `langfuse` package "
                "is not installed — run `pip install langfuse` to enable tracing."
            )
    else:
        logger.info("Langfuse not configured (set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY to enable).")

    logger.info("Prometheus metrics ACTIVE at /metrics.")


def capture_exception(exc: BaseException, **context) -> None:
    """Route an exception to Sentry when enabled; always log + count it."""
    increment_counter("exceptions_captured", type=type(exc).__name__)
    if _sentry_active:
        try:
            import sentry_sdk
            with sentry_sdk.new_scope() as scope:
                for k, v in context.items():
                    scope.set_tag(k, str(v))
                sentry_sdk.capture_exception(exc)
        except Exception:
            logger.debug("Sentry capture failed", exc_info=True)
    logger.error("capture_exception: %s | context=%s", exc, context, exc_info=exc)


# ---------------------------------------------------------------------------
# Langfuse — PREPARED (activates when keys are set and package installed)
# ---------------------------------------------------------------------------
_langfuse_instance = None
_langfuse_checked = False


def _langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _langfuse_client():
    """Lazily construct the Langfuse client once; None if unavailable."""
    global _langfuse_instance, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_instance
    _langfuse_checked = True
    if not _langfuse_configured():
        return None
    try:
        from langfuse import Langfuse
        _langfuse_instance = Langfuse()  # reads LANGFUSE_* env vars itself
    except ImportError:
        _langfuse_instance = None
    except Exception:
        logger.exception("Langfuse client construction failed")
        _langfuse_instance = None
    return _langfuse_instance


@contextmanager
def trace_llm_call(name: str, **metadata):
    """
    Wraps every chat-completion call (already applied in rag_engine.answer).
    Always records duration to Prometheus; additionally emits a Langfuse trace
    when configured. Errors inside the traced block still propagate — tracing
    must never swallow application exceptions.
    """
    start = time.perf_counter()
    lf = _langfuse_client()
    span = None
    if lf is not None:
        try:
            # Langfuse SDK v3+ renamed span creation to start_observation();
            # start_span() no longer exists (found and fixed during Sprint 10
            # activation — the old call silently no-op'd via the except below,
            # so tracing looked "active" in the startup log but never actually
            # sent anything). as_type="generation" gives proper token/cost
            # fields in the Langfuse UI for what's always an LLM completion.
            span = lf.start_observation(name=name, as_type="generation", metadata=metadata)
        except Exception:
            logger.debug("Langfuse span start failed", exc_info=True)
            span = None
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        record_metric("llm_call_duration_ms", duration_ms, call=name,
                      model=str(metadata.get("model", "unknown")))
        if span is not None:
            try:
                span.end()
            except Exception:
                logger.debug("Langfuse span end failed", exc_info=True)
        logger.debug("trace_llm_call end: %s (%.1f ms)", name, duration_ms)
