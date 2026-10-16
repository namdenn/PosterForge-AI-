"""One bounded retry policy for OpenAI SDK calls.

The SDK retry loop is disabled by each adapter so application retries cannot
multiply SDK retries. Temporary failures use jittered exponential backoff and
honour a numeric Retry-After response header when OpenAI supplies one.
"""

import random

from openai import APIConnectionError, APITimeoutError, RateLimitError
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

_FALLBACK_WAIT = wait_random_exponential(multiplier=2, min=2, max=30)


def openai_retrying(*, attempts: int = 3) -> AsyncRetrying:
    """Return the single retry loop used by OpenAI adapters."""

    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=_wait_for_openai,
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError)),
        reraise=True,
    )


def _wait_for_openai(retry_state: RetryCallState) -> float:
    outcome = retry_state.outcome
    exception = outcome.exception() if outcome is not None else None
    if isinstance(exception, RateLimitError):
        retry_after = exception.response.headers.get("retry-after")
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                pass
            else:
                if seconds >= 0:
                    return seconds + random.uniform(0.25, 1.0)
    return float(_FALLBACK_WAIT(retry_state=retry_state))
