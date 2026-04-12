"""
Haber Verisi Modülü
====================
Finansal haberleri çeker ve standart formata dönüştürür:
- Finnhub API (hisse senedi & genel piyasa haberleri)
- CryptoPanic API (kripto odaklı haberler)
- Doğrudan web kazıma yedek (fallback)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

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
    ) -> list[NewsItem]:
        """
        Finnhub'dan şirkete özel haberleri çeker.

        Args:
            symbol: Hisse sembolü (ör. AAPL) — BIST için .IS olmadan
            days: Geriye dönük gün sayısı
        """
        api_key = self._settings.finnhub_api_key
        if not api_key:
            logger.warning("Finnhub API anahtarı tanımlı değil — atlanıyor")
            return []

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

    # ── CryptoPanic ────────────────────────────────────────
    # NOTE: CryptoPanic Free API deprecated (2024) - Using Finnhub only
    # def fetch_crypto_news(
    #     self,
    #     currencies: list[str] | None = None,
    #     kind: str = "news",
    # ) -> list[NewsItem]:
    #     """
    #     CryptoPanic'ten kripto haberlerini çeker.
    #
    #     Args:
    #         currencies: Filtre (ör. ["BTC", "ETH"])
    #         kind: "news" | "media" | "all"
    #     """
    #     api_key = self._settings.cryptopanic_api_key
    #
    #     params: dict[str, Any] = {"auth_token": api_key, "kind": kind, "public": "true"}
    #     if currencies:
    #         params["currencies"] = ",".join(currencies)
    #
    #     self._rate_limit()
    #     try:
    #         url = "https://cryptopanic.com/api/free/v1/posts/"
    #         resp = self._http.get(url, params=params)
    #         resp.raise_for_status()
    #         data = resp.json()
    #     except Exception as e:
    #         logger.error("CryptoPanic hatası: %s", e)
    #         return []
    #
    #     items: list[NewsItem] = []
    #     for post in data.get("results", [])[:50]:
    #         try:
    #             votes = post.get("votes", {})
    #             raw_sent = None
    #             if votes:
    #                 pos = votes.get("positive", 0)
    #                 neg = votes.get("negative", 0)
    #                 if pos > neg:
    #                     raw_sent = "positive"
    #                 elif neg > pos:
    #                     raw_sent = "negative"
    #                 else:
    #                     raw_sent = "neutral"
    #
    #             syms = [
    #                 c.get("code", "")
    #                 for c in post.get("currencies", [])
    #                 if c.get("code")
    #             ]
    #
    #             items.append(
    #                 NewsItem(
    #                     title=post.get("title", ""),
    #                     summary=post.get("title", ""),
    #                     source=post.get("source", {}).get("title", "cryptopanic"),
    #                     url=post.get("url", ""),
    #                     published_at=datetime.fromisoformat(
    #                         post.get("published_at", "").replace("Z", "+00:00")
    #                     ),
    #                     symbols=syms,
    #                     category="crypto",
    #                     raw_sentiment=raw_sent,
    #                 )
    #             )
    #         except (ValueError, TypeError, KeyError):
    #             continue
    #
    #     logger.info("CryptoPanic: %d haber", len(items))
    #     return items

    # ── Birleşik Haber Çekme ──────────────────────────────
    def fetch_all_news(
        self,
        symbol: str | None = None,
        include_general: bool = True,
    ) -> list[NewsItem]:
        """
        Tüm kaynaklardan haberleri çeker ve birleştirir.

        Args:
            symbol: Belirli bir sembol (ör. BTC, AAPL)
            include_general: Genel piyasa haberleri dahil edilsin mi
        """
        all_news: list[NewsItem] = []

        # Kripto haberleri - CryptoPanic deprecated, Finnhub kullanılıyor
        if symbol:
            from data.symbol_resolver import resolve_symbol, AssetClass

            resolved = resolve_symbol(symbol)
            if resolved.asset_class == AssetClass.CRYPTO:
                pass  # CryptoPanic deprecated
            else:
                all_news.extend(self.fetch_finnhub_company_news(resolved.base))
        else:
            pass  # CryptoPanic deprecated

        # Genel piyasa haberleri
        if include_general:
            all_news.extend(self.fetch_finnhub_general_news())

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
        self._http.close()
