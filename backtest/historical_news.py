"""
Historical News Management for Backtest
========================================
Manages news data for historical bars.
Uses SentimentStore cache to avoid repeated LLM calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from data.news_data import NewsClient, NewsItem
from data.sentiment_store import SentimentStore, SentimentRecord
from models.sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


class HistoricalNewsManager:
    """
    Manages historical news for backtest.
    
    Strategy:
    - First call: Fetch news + LLM sentiment analysis → cache
    - Subsequent calls: Load from SentimentStore cache
    """
    
    def __init__(self):
        self.news_client = NewsClient()
        self.sentiment_store = SentimentStore()
        self.sentiment_analyzer = SentimentAnalyzer()
    
    async def get_news_for_bar(
        self,
        symbol: str,
        bar_datetime: datetime,
        lookback_hours: int = 24,
        current_price: float = 0.0,
    ) -> tuple[list[dict], dict | None]:
        """
        Get news and sentiment for a specific bar.
        
        Args:
            symbol: Trading symbol
            bar_datetime: Bar timestamp
            lookback_hours: Hours of news to look back
            current_price: Current price for sentiment analysis
        
        Returns:
            Tuple of (news_data list, sentiment dict)
        """
        # Check sentiment cache first
        cached_sentiment = self.sentiment_store.get_latest(symbol)
        
        if cached_sentiment:
            last_time = datetime.fromisoformat(cached_sentiment.timestamp)
            time_diff = abs((bar_datetime.replace(tzinfo=timezone.utc) - last_time).total_seconds())
            
            # Use cache if within lookback window
            if time_diff < lookback_hours * 3600:
                logger.debug(f"Using cached sentiment for {symbol} @ {bar_datetime}")
                news_data = self._sentiment_to_news(cached_sentiment)
                return news_data, {
                    "sentiment_score": cached_sentiment.sentiment_score,
                    "confidence": cached_sentiment.confidence,
                    "signal": cached_sentiment.signal,
                    "reasoning": cached_sentiment.reasoning,
                    "risk_score": cached_sentiment.risk_score,
                    "key_factors": cached_sentiment.key_factors,
                }
        
        # Fetch historical news
        from_date = bar_datetime - timedelta(hours=lookback_hours)
        to_date = bar_datetime
        
        logger.info(f"Fetching news for {symbol}: {from_date} to {to_date}")
        news_items = await self._fetch_historical_news(symbol, from_date, to_date)
        
        if not news_items:
            logger.warning(f"No news found for {symbol} @ {bar_datetime}")
            return [], None
        
        # Analyze sentiment with LLM
        try:
            sentiment_record = self.sentiment_analyzer.analyze(
                symbol=symbol,
                news=news_items,
                technical_data={"current_price": current_price},
            )
            
            # Save to cache
            self.sentiment_store.save(sentiment_record)
            
            # Convert to news_data format
            news_data = [
                {
                    "title": item.title,
                    "summary": item.summary[:300],
                    "source": item.source,
                    "url": item.url,
                    "published_at": item.published_at.isoformat(),
                    "symbols": item.symbols,
                    "category": item.category,
                    "raw_sentiment": item.raw_sentiment,
                }
                for item in news_items[:20]  # Limit to 20 news items
            ]
            
            sentiment_dict = {
                "sentiment_score": sentiment_record.sentiment_score,
                "confidence": sentiment_record.confidence,
                "signal": sentiment_record.signal,
                "reasoning": sentiment_record.reasoning,
                "risk_score": sentiment_record.risk_score,
                "key_factors": sentiment_record.key_factors,
            }
            
            return news_data, sentiment_dict
            
        except Exception as e:
            logger.error(f"Sentiment analysis failed for {symbol}: {e}")
            return [], None
    
    async def _fetch_historical_news(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[NewsItem]:
        """
        Fetch historical news for symbol.
        
        Args:
            symbol: Trading symbol
            from_date: Start date
            to_date: End date
        
        Returns:
            List of NewsItem
        """
        all_news: list[NewsItem] = []
        
        # Try Finnhub for stock/crypto news
        if ".IS" in symbol or symbol.replace("/", "").replace("-", "").isalpha():
            # Stock symbol
            try:
                stock_news = self.news_client.fetch_finnhub_company_news(
                    symbol,
                    from_date=from_date,
                    to_date=to_date,
                )
                all_news.extend(stock_news)
            except Exception as e:
                logger.debug("Finnhub stock news failed: %s", e)
        
        # Fallback: General financial news
        if not all_news:
            try:
                general_news = self.news_client.fetch_finnhub_general_news("general")
                # Filter by date
                for item in general_news:
                    if from_date <= item.published_at <= to_date:
                        all_news.append(item)
            except Exception as e:
                logger.debug(f"General news failed: {e}")
        
        logger.info(f"Fetched {len(all_news)} news items for {symbol}")
        return all_news
    
    def _sentiment_to_news(self, sentiment: SentimentRecord) -> list[dict]:
        """Convert SentimentRecord to news_data format."""
        return [{
            "title": f"Sentiment Analysis: {sentiment.signal.upper()}",
            "summary": sentiment.reasoning[:300],
            "source": "cached_sentiment",
            "url": "",
            "published_at": sentiment.timestamp,
            "symbols": [sentiment.symbol],
            "category": "sentiment",
            "raw_sentiment": str(sentiment.sentiment_score),
        }]
    
    def close(self):
        """Close HTTP clients."""
        if hasattr(self.news_client, 'close'):
            self.news_client.close()
