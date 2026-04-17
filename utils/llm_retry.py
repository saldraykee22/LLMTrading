"""
LLM Retry with Exponential Backoff
====================================
Reusable retry wrapper for all agent LLM calls.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


def invoke_with_retry(
    invoke_fn: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    validate_json: bool = False,
    request_timeout: int = 60,
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
        validate_json: If True, retries if response is not valid JSON
        request_timeout: Timeout for each LLM call in seconds (default: 60)
        **kwargs: Keyword args to pass to invoke_fn

    Returns:
        LLM response object or content string
    """
    import json
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            # Timeout'u kwargs'a ekle (LangChain için)
            kwargs_with_timeout = kwargs.copy()
            kwargs_with_timeout["request_timeout"] = request_timeout
            response = invoke_fn(*args, **kwargs_with_timeout)
            
            # OpenAI veya LangChain response objesi olabilir, content'i alalım
            content = getattr(response, "content", response)
            if hasattr(content, "text"): content = content.text
            if isinstance(response, dict) and "choices" in response:
                content = response["choices"][0]["message"]["content"]
            elif hasattr(response, "choices"):
                content = response.choices[0].message.content

            if not content:
                raise ValueError("LLM empty response")

            if validate_json:
                # Markdown bloklarını temizle
                clean_content = content.strip()
                if "```json" in clean_content:
                    clean_content = clean_content.split("```json")[-1].split("```")[0].strip()
                elif "```" in clean_content:
                    clean_content = clean_content.split("```")[-1].split("```")[0].strip()
                
                try:
                    json.loads(clean_content)
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid JSON response: {content[:100]}...")

            return response
            
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2**attempt), max_delay)
                delay *= random.uniform(0.5, 1.5)
                logger.warning(
                    "LLM call failed or invalid (attempt %d/%d), retrying in %.1fs: %s",
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
