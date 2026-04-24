"""
LLM Duyarlılık Analizi Modülü
===============================
Çoklu LLM sağlayıcı desteği ile finansal duyarlılık analizi:
- OpenRouter (birincil) — DeepSeek, Claude, GPT modellerine erişim
- DeepSeek (doğrudan API)
- Ollama (yerel modeller)

Chain-of-Thought prompting + yapılandırılmış JSON çıktı.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any


from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.caches import InMemoryCache

from utils.llm_retry import invoke_with_retry


class TTLCache(InMemoryCache):
    """InMemoryCache with TTL and max size eviction."""

    def __init__(self, ttl_seconds: int = 1800, max_size: int = 500) -> None:
        super().__init__()
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()

    def lookup(self, prompt: Any, llm_string: str) -> Any | None:
        key = str(prompt) + llm_string
        with self._lock:
            ts = self._timestamps.get(key)
            if ts is not None and (time.time() - ts) > self._ttl:
                self._cache.pop(key, None)
                self._timestamps.pop(key, None)
                return None
            return super().lookup(prompt, llm_string)

    def update(self, prompt: Any, llm_string: str, return_val: Any) -> None:
        key = str(prompt) + llm_string
        with self._lock:
            if len(self._cache) >= self._max_size and self._timestamps:
                oldest_key = min(self._timestamps, key=self._timestamps.get)
                self._cache.pop(oldest_key, None)
                self._timestamps.pop(oldest_key, None)
            self._timestamps[key] = time.time()
            super().update(prompt, llm_string, return_val)


# Note: Global LLM cache removed to avoid side effects on other agents.
# Per-instance caching is used within SentimentAnalyzer instead.
# set_llm_cache(TTLCache(ttl_seconds=1800, max_size=500))  # REMOVED

from config.settings import (
    LLMProvider,
    PROMPTS_DIR,
    get_settings,
    get_trading_params,
)
from data.news_data import NewsItem
from data.sentiment_store import SentimentRecord, SentimentStore
from utils.json_utils import extract_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    """Prompt dosyasını yükler."""
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("Prompt dosyası bulunamadı: %s", path)
    return ""


def create_llm(
    provider: LLMProvider | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """
    Belirtilen sağlayıcı için LLM nesnesi oluşturur.
    Tüm sağlayıcılar OpenAI uyumlu API kullanır.
    """
    # String provider'ı enum'a dönüştür (graph.py'den str gelebilir)
    if isinstance(provider, str):
        try:
            provider = LLMProvider(provider.lower())
        except ValueError:
            provider = None

    settings = get_settings()
    params = get_trading_params()
    prov = provider or params.sentiment.provider
    
    # Model ismi önekini temizle (ör. 'deepseek/deepseek-chat' -> 'deepseek-chat')
    # Sadece OpenRouter tam yolu ("provider/model") bekler.
    clean_model = model or params.sentiment.model
    if prov != LLMProvider.OPENROUTER and "/" in clean_model:
        # Eğer önek sağlayıcı ile eşleşiyorsa veya genel bir önekse temizle
        # (Ör: 'openai/gpt-4o' -> 'gpt-4o', 'deepseek/chat' -> 'chat')
        parts = clean_model.split("/", 1)
        if len(parts) > 1:
            clean_model = parts[1]

    model_kwargs = {
        "extra_headers": {
            "HTTP-Referer": "https://llmtrading.local",
            "X-Title": "LLM Trading System",
        }
    }
    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    if prov == LLMProvider.OPENROUTER:
        return ChatOpenAI(
            model=model or params.sentiment.model, # OpenRouter için tam yol kalsın
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=temperature,
            max_retries=2,
            model_kwargs=model_kwargs,
        )
    elif prov == LLMProvider.DEEPSEEK:
        return ChatOpenAI(
            model=clean_model or "deepseek-chat",
            openai_api_key=settings.deepseek_api_key,
            openai_api_base=settings.deepseek_base_url,
            temperature=temperature,
            max_retries=2,
            model_kwargs=model_kwargs,
        )
    elif prov == LLMProvider.OLLAMA:
        return ChatOpenAI(
            model=clean_model or settings.ollama_default_model,
            openai_api_key="ollama",
            openai_api_base=f"{settings.ollama_base_url}/v1",
            temperature=temperature,
            max_retries=2,
            model_kwargs=model_kwargs,
        )
    else:
        raise ValueError(f"Bilinmeyen LLM sağlayıcı: {prov}")


class SentimentAnalyzer:
    """LLM tabanlı duyarlılık analizi motoru."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._params = get_trading_params()
        self._llm = create_llm(provider, model, temperature=0.1)
        self._system_prompt = _load_prompt("sentiment_system.txt")
        self._store = SentimentStore()

    def analyze(
        self,
        symbol: str,
        news: list[NewsItem],
        technical_data: dict[str, Any] | None = None,
        save: bool = True,
    ) -> SentimentRecord:
        """
        Haberleri ve teknik verileri analiz ederek duyarlılık skoru üretir.

        Args:
            symbol: Varlık sembolü
            news: Haber listesi
            technical_data: Teknik gösterge verileri (opsiyonel)
            save: Sonucu depoya kaydet

        Returns:
            SentimentRecord: Duyarlılık kaydı
        """
        # Check cache BEFORE calling LLM
        cached = self._store.get_latest(symbol)
        if cached:
            last_time = datetime.fromisoformat(cached.timestamp)
            # Ensure timezone-aware comparison
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            min_interval = self._params.limits.sentiment_cache_minutes
            if (now - last_time).total_seconds() < min_interval * 60:
                logger.debug(
                    "Sentiment cache hit for %s (%.0f min old)",
                    symbol,
                    (now - last_time).total_seconds() / 60,
                )
                return cached

        # ── Kullanıcı mesajını hazırla ─────────────────────
        news_text = self._format_news(news)
        tech_text = self._format_technical(technical_data) if technical_data else ""

        user_message = f"""## Analiz Edilen Varlık: {symbol}

## Haberler ({len(news)} adet)
{news_text}

## Teknik Göstergeler
{tech_text if tech_text else "Teknik veri mevcut değil."}

Lütfen yukarıdaki verileri analiz et ve JSON formatında duyarlılık raporu üret.
Adım adım düşünerek (Chain-of-Thought) analizini açıkla."""

        # ── LLM'e gönder ──────────────────────────────────
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=user_message),
        ]

        try:
            response = invoke_with_retry(
                self._llm.invoke,
                messages,
                max_tokens=self._params.limits.max_tokens_sentiment,
                response_format={"type": "json_object"},
                max_retries=2,
                base_delay=2.0,
                request_timeout=None,
                fallback_on_error=True,
                fallback_value=json.dumps({
                    "sentiment_score": 0.0,
                    "signal": "neutral",
                    "confidence": 0.5,
                    "risk_score": 0.5,
                    "reasoning": "LLM API error - nötr duyarlılık (fallback)",
                    "key_factors": ["API fallback - analiz yapılamadı"]
                }),
            )
            raw_text = response.content
        except Exception as e:
            logger.error("LLM sentiment hatası (%s): %s", symbol, e)
            # Fallback zaten döndü
            return self._fallback_record(symbol, str(e))

        # ── JSON çıkar ────────────────────────────────────
        result = extract_json(raw_text)
        if not result:
            return self._fallback_record(symbol, "JSON parse hatası")

        # ── Record oluştur ─────────────────────────────────
        current_price = 0.0
        if technical_data and "current_price" in technical_data:
            current_price = float(technical_data["current_price"])

        record = SentimentRecord(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sentiment_score=float(result.get("sentiment_score", 0.0)),
            confidence=float(result.get("confidence", 0.3)),
            risk_score=float(result.get("risk_score", 0.5)),
            signal=result.get("signal", "neutral"),
            reasoning=result.get("reasoning", ""),
            key_factors=result.get("key_factors", []),
            news_count=len(news),
            model_used=self._llm.model_name,
            provider=self._params.sentiment.provider.value,
            price=current_price,
        )

        # Skor sınırlandırma
        record.sentiment_score = max(-1.0, min(1.0, record.sentiment_score))
        record.confidence = max(0.0, min(1.0, record.confidence))
        record.risk_score = max(0.0, min(1.0, record.risk_score))

        if save:
            self._store.save(record)

        logger.info(
            "Sentiment: %s → %.2f (%s, güven: %.2f)",
            symbol,
            record.sentiment_score,
            record.signal,
            record.confidence,
        )
        return record

    def _format_news(self, news: list[NewsItem]) -> str:
        """Haberleri okunabilir metin formatına dönüştürür."""
        if not news:
            return "Haber bulunamadı."

        lines: list[str] = []
        for i, item in enumerate(news[: self._params.limits.max_news_items], 1):
            lines.append(
                f"{i}. [{item.published_at.strftime('%Y-%m-%d %H:%M')}] "
                f"**{item.title}**\n"
                f"   Kaynak: {item.source}\n"
                f"   Özet: {item.summary[:300]}"
            )
        return "\n\n".join(lines)

    def _format_technical(self, data: dict[str, Any]) -> str:
        """Teknik göstergeleri metin formatına dönüştürür."""
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, float):
                lines.append(f"- {key}: {value:.4f}")
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines) if lines else "Teknik veri yok."

    def _fallback_record(self, symbol: str, error: str) -> SentimentRecord:
        """Hata durumunda nötr kayıt döndürür."""
        return SentimentRecord(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sentiment_score=0.0,
            confidence=0.1,
            risk_score=0.5,
            signal="neutral",
            reasoning=f"Analiz başarısız: {error}",
            key_factors=["error"],
            news_count=0,
            model_used=self._llm.model_name,
            provider=self._params.sentiment.provider.value,
        )


# ── Yardımcı fonksiyon — farklı sağlayıcıda LLM oluştur ──
def create_agent_llm(
    provider: LLMProvider | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """Ajan düğümleri için LLM nesnesi oluşturur (dışa açık)."""
    return create_llm(provider, model, temperature, max_tokens)


def create_ensemble_llm(
    model_specs: list[str] | None = None,
    temperature: float = 0.1,
) -> list[ChatOpenAI]:
    """
    Birden fazla LLM sağlayıcısı için LLM nesneleri oluşturur.

    Args:
        model_specs: Model liste, ör. ["deepseek/deepseek-chat", "ollama/llama3:8b"]
        temperature: Tüm modeller için sıcaklık

    Returns:
        ChatOpenAI instance listesi
    """
    from config.settings import get_trading_params

    params = get_trading_params()
    specs = model_specs or params.agents.ensemble_models

    llm_instances: list[ChatOpenAI] = []
    for spec in specs:
        if "/" in spec:
            provider_str, model_name = spec.split("/", 1)
        else:
            provider_str = "openrouter"
            model_name = spec

        provider_map = {
            "openrouter": LLMProvider.OPENROUTER,
            "deepseek": LLMProvider.DEEPSEEK,
            "ollama": LLMProvider.OLLAMA,
        }
        provider = provider_map.get(provider_str.lower(), LLMProvider.OPENROUTER)

        try:
            llm = create_llm(
                provider=provider, model=model_name, temperature=temperature
            )
            llm_instances.append(llm)
            logger.info("Ensemble LLM oluşturuldu: %s", spec)
        except Exception as e:
            logger.warning("Ensemble LLM oluşturulamadı (%s): %s", spec, e)

    if not llm_instances:
        raise ValueError("Hiçbir ensemble LLM oluşturulamadı")

    return llm_instances
