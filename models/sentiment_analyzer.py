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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

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


def _create_llm(
    provider: LLMProvider | None = None,
    model: str | None = None,
    temperature: float = 0.1,
) -> ChatOpenAI:
    """
    Belirtilen sağlayıcı için LLM nesnesi oluşturur.
    Tüm sağlayıcılar OpenAI uyumlu API kullanır.
    """
    settings = get_settings()
    params = get_trading_params()
    prov = provider or params.sentiment.provider

    if prov == LLMProvider.OPENROUTER:
        return ChatOpenAI(
            model=model or params.sentiment.model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=temperature,
            request_timeout=60,
            max_retries=2,
            model_kwargs={
                "extra_headers": {
                    "HTTP-Referer": "https://llmtrading.local",
                    "X-Title": "LLM Trading System",
                }
            },
        )
    elif prov == LLMProvider.DEEPSEEK:
        return ChatOpenAI(
            model=model or "deepseek-chat",
            openai_api_key=settings.deepseek_api_key,
            openai_api_base=settings.deepseek_base_url,
            temperature=temperature,
            request_timeout=60,
            max_retries=2,
        )
    elif prov == LLMProvider.OLLAMA:
        return ChatOpenAI(
            model=model or settings.ollama_default_model,
            openai_api_key="ollama",
            openai_api_base=f"{settings.ollama_base_url}/v1",
            temperature=temperature,
            request_timeout=120,
            max_retries=2,
        )
    else:
        raise ValueError(f"Bilinmeyen LLM sağlayıcı: {prov}")


def _extract_json(text: str) -> dict[str, Any]:
    """Geriye uyumlu alias — utils.json_utils.extract_json kullanır."""
    from utils.json_utils import extract_json as _ej

    return _ej(text)


class SentimentAnalyzer:
    """LLM tabanlı duyarlılık analizi motoru."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._params = get_trading_params()
        self._llm = _create_llm(provider, model, temperature=0.1)
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
            response = self._llm.invoke(messages)
            raw_text = response.content
        except Exception as e:
            logger.error("LLM sentiment hatası (%s): %s", symbol, e)
            return self._fallback_record(symbol, str(e))

        # ── JSON çıkar ────────────────────────────────────
        result = _extract_json(raw_text)
        if not result:
            return self._fallback_record(symbol, "JSON parse hatası")

        # ── Record oluştur ─────────────────────────────────
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
        for i, item in enumerate(news[:15], 1):  # Max 15 haber
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
) -> ChatOpenAI:
    """Ajan düğümleri için LLM nesnesi oluşturur (dışa açık)."""
    return _create_llm(provider, model, temperature)
