"""
Araştırmacı Ajan (Research Analyst)
=====================================
Piyasa verilerini, haberleri ve teknik göstergeleri analiz eder.
LLM duyarlılık skoru üretir ve kapsamlı bir araştırma raporu hazırlar.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import TradingState
from config.settings import PROMPTS_DIR, get_trading_params
from models.sentiment_analyzer import SentimentAnalyzer, create_agent_llm
from utils.json_utils import extract_json

logger = logging.getLogger(__name__)


def research_analyst_node(state: TradingState) -> dict[str, Any]:
    """
    Araştırmacı ajan düğümü.

    Görevler:
    1. Haberlere dayalı duyarlılık analizi (SentimentAnalyzer)
    2. Teknik veriler + sentiment sentezi
    3. Kapsamlı araştırma raporu üretimi
    """
    symbol = state["symbol"]
    params = get_trading_params()

    logger.info("Araştırmacı Ajan çalışıyor: %s", symbol)

    # ── 1. Duyarlılık Analizi ──────────────────────────────
    from data.news_data import NewsItem

    news_items = []
    for nd in state.get("news_data", []):
        try:
            from datetime import datetime, timezone

            published = nd.get("published_at", "")
            if isinstance(published, str):
                try:
                    published = datetime.fromisoformat(published)
                except ValueError:
                    published = datetime.now(timezone.utc)

            news_items.append(
                NewsItem(
                    title=nd.get("title", ""),
                    summary=nd.get("summary", ""),
                    source=nd.get("source", ""),
                    url=nd.get("url", ""),
                    published_at=published,
                    symbols=nd.get("symbols", []),
                    category=nd.get("category", "general"),
                    raw_sentiment=nd.get("raw_sentiment"),
                )
            )
        except Exception:
            continue

    # Duyarlılık analizi
    provider = state.get("provider") or None
    analyzer = SentimentAnalyzer(provider=provider)
    sentiment_record = analyzer.analyze(
        symbol=symbol,
        news=news_items,
        technical_data=state.get("technical_signals"),
    )

    sentiment_data = {
        "sentiment_score": sentiment_record.sentiment_score,
        "confidence": sentiment_record.confidence,
        "risk_score": sentiment_record.risk_score,
        "signal": sentiment_record.signal,
        "reasoning": sentiment_record.reasoning,
        "key_factors": sentiment_record.key_factors,
        "news_count": sentiment_record.news_count,
    }

    # ── 2. Kapsamlı Araştırma Raporu ──────────────────────
    research_prompt_path = PROMPTS_DIR / "research_analyst.txt"
    system_prompt = ""
    if research_prompt_path.exists():
        system_prompt = research_prompt_path.read_text(encoding="utf-8")

    tech = state.get("technical_signals", {})
    market = state.get("market_data", {})

    user_msg = f"""## Varlık: {symbol}

## Duyarlılık Analizi Sonuçları
- Skor: {sentiment_data["sentiment_score"]:.2f}
- Sinyal: {sentiment_data["signal"]}
- Güven: {sentiment_data["confidence"]:.2f}
- Risk: {sentiment_data["risk_score"]:.2f}
- Anahtar faktörler: {", ".join(sentiment_data.get("key_factors", []))}
- Gerekçe: {sentiment_data.get("reasoning", "N/A")}

## Teknik Göstergeler
{json.dumps(tech, indent=2, ensure_ascii=False) if tech else "Mevcut değil"}

## Piyasa Verisi Özeti
{json.dumps(market, indent=2, ensure_ascii=False) if market else "Mevcut değil"}

Lütfen tüm verileri sentezleyerek kapsamlı bir araştırma raporu hazırla."""

    llm = create_agent_llm(provider=provider, model=params.agents.analyst_model)
    try:
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ],
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        research_result = extract_json(response.content)
    except Exception as e:
        logger.error("Araştırma raporu hatası: %s", e)
        research_result = {
            "recommendation": "hold",
            "confidence": 0.3,
            "reasoning": f"Araştırma raporu oluşturulamadı: {e}",
        }

    analyst_msg = (
        f"[Araştırmacı] {symbol} analizi tamamlandı:\n"
        f"  Duyarlılık: {sentiment_data['signal']} ({sentiment_data['sentiment_score']:.2f})\n"
        f"  Öneri: {research_result.get('recommendation', 'hold')}\n"
        f"  Güven: {research_result.get('confidence', 0):.2f}"
    )

    logger.info(analyst_msg)

    return {
        "messages": [{"role": "research_analyst", "content": analyst_msg}],
        "sentiment": sentiment_data,
        "research_report": research_result,
        "phase": "debate",
    }
