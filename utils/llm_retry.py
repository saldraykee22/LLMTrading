"""
LLM Retry with Exponential Backoff
====================================
Reusable retry wrapper for all agent LLM calls.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


def invoke_with_retry(
    invoke_fn: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    **kwargs: Any,
) -> Any:
    """
    Retry an LLM invoke call with exponential backoff.

    Args:
        invoke_fn: The LLM.invoke method (or any callable)
        *args: Positional args to pass to invoke_fn
        max_retries: Maximum retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay cap (seconds)
        **kwargs: Keyword args to pass to invoke_fn

    Returns:
        LLM response object

    Raises:
        Last exception if all retries fail
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return invoke_fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    e,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "LLM call FAILED after %d attempts: %s",
                    max_retries,
                    e,
                )

    raise last_error  # type: ignore[misc]
