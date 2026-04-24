"""
Haber Verisi Modülü
====================
Finansal haberleri çeker ve standart formata dönüştürür:
- Finnhub API (hisse seneti & genel piyasa haberleri)
- Doğrudan web kazıma yedek (fallback RSS)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import feedparser

from config.settings import get_settings, get_trading_params

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Standartlaştırılmış haber öğesi."""

    title: str
    summary: str
    source: str
    url: str
    published_at: datetime
    symbols: list[str] = field(default_factory=list)
    category: str = "general"  # general, crypto, earnings, macro
    raw_sentiment: str | None = None  # Kaynağın kendi sentiment'i (varsa)


class NewsClient:
    """Çoklu kaynaklı haber istemcisi."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._params = get_trading_params()
        self._http = httpx.Client(timeout=15.0)
        self._last_request_time: float = 0
        self._rate_limit_delay: float = self._params.limits.news_rate_limit_delay

    def _rate_limit(self) -> None:
        """Basit rate limiting — istekler arası bekleme."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    # ── Finnhub ────────────────────────────────────────────
    def fetch_finnhub_company_news(
        self,
        symbol: str,
        days: int | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[NewsItem]:
        """
        Finnhub'dan şirkete özel haberleri çeker.

        Args:
            symbol: Hisse sembolü (ör. AAPL) — BIST için .IS olmadan
            days: Geriye dönük gün sayısı
            from_date: Başlangıç tarihi
            to_date: Bitiş tarihi
        """
        api_key = self._settings.finnhub_api_key
        if not api_key:
            logger.warning("Finnhub API anahtarı tanımlı değil — atlanıyor")
            return []

        if from_date is None or to_date is None:
            d = days or (self._params.data.news_lookback_hours // 24) or 1
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=d)

        # .IS uzantısını kaldır
        clean_symbol = symbol.replace(".IS", "").upper()

        self._rate_limit()
        try:
            resp = self._http.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": clean_symbol,
                    "from": from_date.strftime("%Y-%m-%d"),
                    "to": to_date.strftime("%Y-%m-%d"),
                    "token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Finnhub şirket haberi hatası (%s): %s", clean_symbol, e)
            return []

        items: list[NewsItem] = []
        for item in data[:50]:  # Max 50 haber
            try:
                items.append(
                    NewsItem(
                        title=item.get("headline", ""),
                        summary=item.get("summary", ""),
                        source=item.get("source", "finnhub"),
                        url=item.get("url", ""),
                        published_at=datetime.fromtimestamp(
                            item.get("datetime", 0), tz=timezone.utc
                        ),
                        symbols=[clean_symbol],
                        category=item.get("category", "general"),
                    )
                )
            except (ValueError, TypeError):
                continue

        logger.info("Finnhub: %s → %d haber", clean_symbol, len(items))
        return items

    def fetch_finnhub_general_news(self, category: str = "general") -> list[NewsItem]:
        """Finnhub'dan genel piyasa haberlerini çeker."""
        api_key = self._settings.finnhub_api_key
        if not api_key:
            return []

        self._rate_limit()
        try:
            resp = self._http.get(
                "https://finnhub.io/api/v1/news",
                params={"category": category, "token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Finnhub genel haber hatası: %s", e)
            return []

        items: list[NewsItem] = []
        for item in data[:30]:
            try:
                items.append(
                    NewsItem(
                        title=item.get("headline", ""),
                        summary=item.get("summary", ""),
                        source=item.get("source", "finnhub"),
                        url=item.get("url", ""),
                        published_at=datetime.fromtimestamp(
                            item.get("datetime", 0), tz=timezone.utc
                        ),
                        category="macro",
                    )
                )
            except (ValueError, TypeError):
                continue

        logger.info("Finnhub genel: %d haber", len(items))
        return items

    # ── RSS Fallback ────────────────────────────────────────
    def fetch_rss_news(self, rss_urls: list[str] | None = None) -> list[NewsItem]:
        """
        RSS feed'lerinden haberleri çeker (fallback mekanizması).

        Args:
            rss_urls: RSS URL listesi. None ise varsayılan kaynaklar kullanılır.
        """
        if rss_urls is None:
            rss_urls = [
                "https://feeds.feedburner.com/coinDesk",  # CoinDesk
                "https://feeds.feedburner.com/Cointelegraph",  # Cointelegraph
                "https://rss.cnn.com/rss/money_news_international.rss",  # CNN Money
                "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^IXIC,^DJI",  # Yahoo Finance
            ]

        all_items: list[NewsItem] = []

        for rss_url in rss_urls:
            try:
                self._rate_limit()
                
                # Fetch with timeout to prevent thread hangs
                with httpx.Client(timeout=15.0) as client:
                    resp = client.get(rss_url)
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.text)

                if feed.bozo:  # Parse hatası varsa atla
                    logger.warning(
                        "RSS parse hatası (%s): %s", rss_url, feed.bozo_exception
                    )
                    continue

                for entry in feed.entries[:10]:  # Her RSS'den max 10 haber
                    try:
                        # Yayın tarihi
                        published = None
                        if (
                            hasattr(entry, "published_parsed")
                            and entry.published_parsed
                        ):
                            published = datetime(
                                *entry.published_parsed[:6], tzinfo=timezone.utc
                            )
                        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                            published = datetime(
                                *entry.updated_parsed[:6], tzinfo=timezone.utc
                            )
                        else:
                            published = datetime.now(timezone.utc)

                        # Özet (description varsa al, yoksa title'dan kısalt)
                        summary = ""
                        if hasattr(entry, "description"):
                            summary = entry.description
                        elif hasattr(entry, "summary"):
                            summary = entry.summary
                        else:
                            summary = (
                                entry.title[:200] + "..."
                                if len(entry.title) > 200
                                else entry.title
                            )

                        # Kaynak adı
                        source = (
                            feed.feed.get("title", "RSS")
                            if hasattr(feed, "feed")
                            else "RSS"
                        )

                        all_items.append(
                            NewsItem(
                                title=entry.title,
                                summary=summary,
                                source=source,
                                url=entry.link,
                                published_at=published,
                                category="general",
                            )
                        )
                    except (AttributeError, ValueError, TypeError) as e:
                        logger.debug("RSS entry parse hatası: %s", e)
                        continue

                logger.info("RSS (%s): %d haber", rss_url, len(feed.entries[:10]))

            except Exception as e:
                logger.warning("RSS fetch hatası (%s): %s", rss_url, e)
                continue

        # Tarihe göre sırala (en yeni önce)
        all_items.sort(key=lambda x: x.published_at, reverse=True)

        logger.info("RSS toplam: %d haber", len(all_items))
        return all_items

    # ── Birleşik Haber Çekme ──────────────────────────────
    def fetch_all_news(
        self,
        symbol: str | None = None,
        include_general: bool = True,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[NewsItem]:
        """
        Tüm kaynaklardan haberleri çeker ve birleştirir.
        Finnhub başarısız olursa RSS fallback kullanılır.

        Args:
            symbol: Belirli bir sembol (ör. BTC, AAPL)
            include_general: Genel piyasa haberleri dahil edilsin mi
            from_date: Başlangıç tarihi
            to_date: Bitiş tarihi
        """
        all_news: list[NewsItem] = []

        # Sembol bazlı haberler
        if symbol:
            from data.symbol_resolver import resolve_symbol, AssetClass

            resolved = resolve_symbol(symbol)
            if resolved.asset_class != AssetClass.CRYPTO:
                finnhub_news = self.fetch_finnhub_company_news(
                    resolved.base, from_date=from_date, to_date=to_date
                )
                if finnhub_news:
                    all_news.extend(finnhub_news)
                else:
                    logger.warning(
                        "Finnhub şirket haberi başarısız, RSS fallback kullanılacak"
                    )

        # Genel piyasa haberleri
        if include_general:
            finnhub_general = self.fetch_finnhub_general_news()
            if finnhub_general:
                all_news.extend(finnhub_general)
            else:
                logger.warning(
                    "Finnhub genel haber başarısız, RSS fallback kullanılıyor"
                )
                # RSS fallback for general news
                rss_news = self.fetch_rss_news()
                all_news.extend(rss_news)

        # Tarihe göre sırala (en yeni önce)
        all_news.sort(key=lambda x: x.published_at, reverse=True)

        # Tekrarları kaldır (başlık bazlı)
        seen_titles: set[str] = set()
        unique: list[NewsItem] = []
        for item in all_news:
            title_key = item.title.lower().strip()[:80]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(item)

        logger.info("Toplam benzersiz haber: %d", len(unique))
        return unique

    def close(self) -> None:
        """HTTP istemcisini kapatır."""
        if self._http:
            try:
                self._http.close()
            except Exception:
                pass
            self._http = None

    def __enter__(self) -> "NewsClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
