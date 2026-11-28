"""Privacy-safe counters for one synchronous case research run."""

import logging
import time
from collections import Counter
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

logger = logging.getLogger(__name__)
_current: ContextVar[Counter[str] | None] = ContextVar("rag_metrics", default=None)
_fallbacks: ContextVar[set[str] | None] = ContextVar("rag_fallbacks", default=None)


def count(name: str, amount: int = 1) -> None:
    metrics = _current.get()
    if metrics is not None:
        metrics[name] += amount


def record_fallback(reason: str) -> None:
    reasons = _fallbacks.get()
    if reasons is not None:
        reasons.add(reason)


def track_rag(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        metrics: Counter[str] = Counter()
        reasons: set[str] = set()
        token = _current.set(metrics)
        fallback_token = _fallbacks.set(reasons)
        start = time.monotonic()
        try:
            return function(*args, **kwargs)
        finally:
            count("analysis_ms", int((time.monotonic() - start) * 1000))
            logger.info(
                "rag_run id=%s stage=%s counters=%s fallback_reasons=%s",
                uuid4().hex, function.__name__, metrics, sorted(reasons),
            )
            _current.reset(token)
            _fallbacks.reset(fallback_token)

    return wrapped
