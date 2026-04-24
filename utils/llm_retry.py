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


import threading

_fallback_counter = 0
_counter_lock = threading.Lock()


class _MockResponse:
    """Mock LLM response wrapper for fallback values."""
    def __init__(self, content: str):
        self.content = content


def get_fallback_metrics() -> dict[str, int]:
    """Get fallback usage metrics."""
    with _counter_lock:
        return {"fallback_count": _fallback_counter}


def reset_fallback_metrics() -> None:
    """Reset fallback metrics."""
    global _fallback_counter
    with _counter_lock:
        _fallback_counter = 0


def invoke_with_retry(
    invoke_fn: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    validate_json: bool = False,
    response_schema: Any = None,
    request_timeout: int = 60,
    fallback_on_error: bool = False,
    fallback_value: Any = None,
    **kwargs: Any,
) -> Any:
    """
    Retry an LLM invoke call with exponential backoff and optional fallback.

    Args:
        invoke_fn: The LLM.invoke method (or any callable)
        *args: Positional args to pass to invoke_fn
        max_retries: Maximum retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay cap (seconds)
        validate_json: If True, retries if response is not valid JSON
        response_schema: Optional Pydantic model or type to validate the JSON response
        request_timeout: Timeout for each LLM call in seconds (default: 60)
        fallback_on_error: If True, return fallback_value instead of raising exception on final failure
        fallback_value: Value to return on failure when fallback_on_error is True (JSON string or dict)
        **kwargs: Keyword args to pass to invoke_fn

    Returns:
        LLM response object or content string, or fallback value if enabled
    """
    import json
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            # Timeout'u kwargs'a ekle (sadece None değilse)
            kwargs_with_timeout = kwargs.copy()
            if request_timeout is not None:
                # NOT: LangChain ChatOpenAI 'timeout' parametresi kullanır
                # 'request_timeout' değil - bu uyumluluk için dönüştürüyoruz
                kwargs_with_timeout["timeout"] = request_timeout
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

            if validate_json or response_schema is not None:
                # Markdown bloklarını temizle
                clean_content = content.strip()
                if "```json" in clean_content:
                    clean_content = clean_content.split("```json")[-1].split("```")[0].strip()
                elif "```" in clean_content:
                    clean_content = clean_content.split("```")[-1].split("```")[0].strip()
                
                try:
                    parsed_json = json.loads(clean_content)
                    
                    # Pydantic şema doğrulaması
                    if response_schema is not None:
                        try:
                            from pydantic import TypeAdapter, ValidationError
                            adapter = TypeAdapter(response_schema)
                            adapter.validate_python(parsed_json)
                        except ImportError:
                            logger.warning("Pydantic is not installed. Skipping schema validation.")
                        except Exception as e:
                            # Catch ValidationError
                            raise ValueError(f"Schema validation failed: {e}")
                            
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid JSON response: {content[:100]}...")

            return response
            
        except (KeyboardInterrupt, SystemExit):
            raise
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

    # Fallback mekanizması
    if fallback_on_error:
        logger.warning(
            "LLM call failed after %d attempts, using FALLBACK value",
            max_retries,
        )
        
        # Call stack'ten ajan adını bul
        import traceback
        stack = traceback.extract_stack()
        agent_name = "unknown"
        for frame in stack[-6:-1]:  # Skip current and immediate callers
            if "agents" in frame.filename or "models" in frame.filename:
                # Cross-platform path parsing
                parts = frame.filename.replace("\\", "/").split("/")
                for part in reversed(parts):
                    if part.endswith(".py"):
                        agent_name = part[:-3]  # .py uzantısını kaldır
                        break
                break
        
        # Dynamic fallback config'den yükle (eğer fallback_value belirtilmemişse)
        if fallback_value is None:
            try:
                from config.settings import get_fallback_config
                fallback_value = get_fallback_config(agent_name)
                if fallback_value is None:
                    # Config yoksa varsayılan kullan
                    fallback_value = {"status": "error", "reason": "LLM API error"}
            except Exception:
                fallback_value = {"status": "error", "reason": "LLM API error"}
        
        # Audit log
        try:
            from data.fallback_store import get_fallback_store
            store = get_fallback_store()
            
            # Fallback value'u dict'e çevir
            fallback_dict = fallback_value
            if isinstance(fallback_value, str):
                import json
                try:
                    fallback_dict = json.loads(fallback_value)
                except:
                    fallback_dict = {"raw": fallback_value[:200]}
            
            store.log_fallback(
                agent=agent_name,
                reason=f"LLM API error after {max_retries} retries",
                fallback_value=fallback_dict,
                extra_data={
                    "max_retries": max_retries,
                    "base_delay": base_delay,
                    "error": str(last_error)[:200] if last_error else None,
                }
            )
        except Exception as e:
            # Audit log hatası kritik değil, devam et
            logger.debug("Fallback audit log hatası: %s", e)
        
        # Circuit breaker fallback sayacını artır
        try:
            from risk.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker()
            cb.record_fallback(agent_name=agent_name)
        except Exception as e:
            logger.debug("Circuit breaker fallback record hatası: %s", e)
        
        # Fallback value bir string ise (JSON) mock response objesi oluştur
        if isinstance(fallback_value, str):
            return _MockResponse(fallback_value)
        # Dict ise JSON'a dönüştür ve mock response wrapper ile döndür
        return _MockResponse(json.dumps(fallback_value))

    raise last_error  # type: ignore[misc]
