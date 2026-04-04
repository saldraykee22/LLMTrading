"""
LLM Fallback Chain
====================
Provider başarısız olduğunda otomatik fallback zinciri:
  OpenRouter → DeepSeek → Ollama

Her invoke çağrısı fallback ile korunur.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from config.settings import LLMProvider, get_settings, get_trading_params
from models.sentiment_analyzer import _create_llm

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_ORDER = [
    LLMProvider.OPENROUTER,
    LLMProvider.DEEPSEEK,
    LLMProvider.OLLAMA,
]


def invoke_with_fallback(
    messages: list[BaseMessage],
    providers: list[LLMProvider] | None = None,
    model: str | None = None,
    temperature: float = 0.1,
) -> tuple[str, str]:
    """
    LLM çağrısını fallback zinciri ile yapar.

    Args:
        messages: Mesaj listesi
        providers: Denenecek sağlayıcı sırası
        model: Model ismi (None = varsayılan)
        temperature: Sıcaklık

    Returns:
        (yanıt_metni, kullanılan_provider)

    Raises:
        RuntimeError: Tüm sağlayıcılar başarısız olursa
    """
    if providers is None:
        providers = DEFAULT_FALLBACK_ORDER

    last_error: Exception | None = None

    for provider in providers:
        try:
            llm = _create_llm(provider, model, temperature)
            response = llm.invoke(messages)
            content = response.content
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)

            logger.info("LLM provider başarılı: %s", provider.value)
            return str(content), provider.value

        except Exception as e:
            logger.warning(
                "LLM provider başarısız: %s — %s",
                provider.value,
                e,
            )
            last_error = e
            continue

    raise RuntimeError(f"Tüm LLM provider'lar başarısız: {last_error}")


def invoke_with_retry(
    llm: ChatOpenAI,
    messages: list[BaseMessage],
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> Any:
    """
    Tek bir LLM çağrısını exponential backoff ile tekrar dener.

    Args:
        llm: LLM nesnesi
        messages: Mesaj listesi
        max_retries: Maksimum deneme sayısı
        base_delay: İlk bekleme süresi (saniye)

    Returns:
        LLM yanıtı

    Raises:
        Son denemedeki exception (tüm denemeler başarısız olursa)
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return llm.invoke(messages)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "LLM call başarısız (deneme %d/%d), %.1fs bekleniyor: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    e,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "LLM call tamamen başarısız (%d deneme): %s",
                    max_retries,
                    e,
                )

    raise last_error  # type: ignore[misc]
