"""Small timing span used before adopting a full tracing backend."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

import structlog


@contextmanager
def log_span(name: str, **context: str) -> Iterator[None]:
    """Log duration and outcome without coupling callers to a tracing vendor."""

    logger = structlog.get_logger().bind(span=name, **context)
    started = perf_counter()
    logger.info("span_started")
    try:
        yield
    except Exception:
        logger.exception("span_failed", duration_ms=round((perf_counter() - started) * 1000, 2))
        raise
    else:
        logger.info("span_completed", duration_ms=round((perf_counter() - started) * 1000, 2))
