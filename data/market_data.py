"""
Piyasa Verisi Modülü
=====================
OHLCV verisi çekme:
- Kripto: CCXT (Binance) üzerinden
- Hisse Senedi: yfinance üzerinden (BIST + ABD)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd
import threading
import time
import yfinance as yf

from config.settings import get_settings, get_trading_params
from data.symbol_resolver import AssetClass, resolve_symbol

logger = logging.getLogger(__name__)


class MarketDataClient:
    """Birleşik piyasa verisi istemcisi (thread-safe)."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._params = get_trading_params()
        self._exchange_private: ccxt.Exchange | None = None
        self._exchange_public: ccxt.Exchange | None = None
        # Thread-safety için lock'lar
        self._exchange_private_lock = threading.RLock()
        self._exchange_public_lock = threading.RLock()
        # Ticker cache
        self._tickers_cache: dict | None = None
        self._tickers_cache_time: float = 0.0
        self._tickers_cache_ttl: float = 30.0

    # ── Binance CCXT Bağlantısı ────────────────────────────
    def _get_private_exchange(self) -> ccxt.Exchange:
        """Binance private exchange (Emirler/Bakiye - Testnet'e saygı duyar). Thread-safe."""
        with self._exchange_private_lock:
            if self._exchange_private is None:
                config: dict = {
                    "apiKey": self._settings.binance_api_key,
                    "secret": self._settings.binance_api_secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "spot"},
                }
                if self._settings.binance_testnet:
                    config["sandbox"] = True
                safe_config = {
                    **config,
                    "apiKey": "***" if config.get("apiKey") else "",
                    "secret": "***" if config.get("secret") else "",
                }

                try:
                    self._exchange_private = ccxt.binance(config)
                except Exception as e:
                    logger.error(
                        "Binance private connection failed: %s (config=%s)",
                        str(e),
                        safe_config,
                    )
                    raise
                logger.info(
                    "Binance private connection established (testnet=%s)",
                    self._settings.binance_testnet,
                )
            return self._exchange_private

    def _get_public_exchange(self) -> ccxt.Exchange:
        """Binance public exchange (Piyasa Verisi - HER ZAMAN Mainnet). Thread-safe."""
        with self._exchange_public_lock:
            if self._exchange_public is None:
                config: dict = {
                    "enableRateLimit": True,
                    "options": {"defaultType": "spot"},
                }
                # Public data için API key gerekmez, sandbox zorunluluğu yok
                self._exchange_public = ccxt.binance(config)
                logger.info("Binance public connection established (Mainnet)")
            return self._exchange_public

    # ── Kripto OHLCV ───────────────────────────────────────
    def fetch_crypto_ohlcv(
        self,
        symbol: str,
        timeframe: str | None = None,
        days: int | None = None,
    ) -> pd.DataFrame:
        """
        Binance'den OHLCV verisi çeker.

        Args:
            symbol: Kripto çifti (ör. BTC/USDT)
            timeframe: Mum periyodu (1m, 5m, 15m, 1h, 4h, 1d)
            days: Geçmiş gün sayısı

        Returns:
            DataFrame: datetime, open, high, low, close, volume sütunları
        """
        resolved = resolve_symbol(symbol)
        tf = timeframe or self._params.data.default_timeframe
        d = days or self._params.data.history_days

        exchange = self._get_public_exchange()
        since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=d)).timestamp() * 1000
        )

        all_ohlcv: list = []
        fetch_since = since_ms

        while True:
            try:
                batch = exchange.fetch_ohlcv(
                    resolved.symbol,
                    timeframe=tf,
                    since=fetch_since,
                    limit=1000,
                )
            except ccxt.BaseError as e:
                logger.error("CCXT hatası (%s): %s", resolved.symbol, e)
                break

            if not batch:
                break

            all_ohlcv.extend(batch)
            fetch_since = batch[-1][0] + 1

            if len(batch) < 1000:
                break

        if not all_ohlcv:
            logger.warning("Veri bulunamadı: %s", resolved.symbol)
            return pd.DataFrame(
                columns=["datetime", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(
            all_ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop(columns=["timestamp"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df = df.drop_duplicates(subset=["datetime"])

        # Empty DataFrame check before accessing .iloc[]
        if not df.empty:
            logger.info(
                "Kripto OHLCV: %s - %d mum (%s -> %s)",
                resolved.symbol,
                len(df),
                df["datetime"].iloc[0].strftime("%Y-%m-%d"),
                df["datetime"].iloc[-1].strftime("%Y-%m-%d"),
            )
        else:
            logger.warning("Kripto OHLCV: %s - Veri bulunamadı", resolved.symbol)
        
        return df

    # ── Hisse Senedi OHLCV (yfinance) ─────────────────────
    def fetch_stock_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        days: int | None = None,
    ) -> pd.DataFrame:
        """
        yfinance ile hisse senedi OHLCV verisi çeker.

        Args:
            symbol: Hisse sembolü (ör. AAPL, BIMAS)
            interval: Periyot (1d, 1h, 5m) — yfinance limitleri geçerli
            days: Geçmiş gün sayısı

        Returns:
            DataFrame: datetime, open, high, low, close, volume
        """
        resolved = resolve_symbol(symbol)
        d = days or self._params.data.history_days

        # yfinance period mapping
        if d <= 7:
            period = "5d"
        elif d <= 30:
            period = "1mo"
        elif d <= 90:
            period = "3mo"
        elif d <= 180:
            period = "6mo"
        elif d <= 365:
            period = "1y"
        elif d <= 730:
            period = "2y"
        else:
            period = "max"

        try:
            import requests
            session = requests.Session()
            session.request = lambda method, url, **kwargs: requests.Session.request(session, method, url, timeout=15.0, **kwargs)
            ticker = yf.Ticker(resolved.symbol, session=session)
            df = ticker.history(period=period, interval=interval)
        except Exception as e:
            logger.error("yfinance hatası (%s): %s", resolved.symbol, e)
            return pd.DataFrame(
                columns=["datetime", "open", "high", "low", "close", "volume"]
            )

        if df.empty:
            logger.warning("Veri bulunamadı: %s", resolved.symbol)
            return pd.DataFrame(
                columns=["datetime", "open", "high", "low", "close", "volume"]
            )

        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # yfinance 'date' veya 'datetime' olabiliyor
        dt_col = "datetime" if "datetime" in df.columns else "date"
        df = df.rename(columns={dt_col: "datetime"})

        # Sadece standart sütunları tut
        keep = ["datetime", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.sort_values("datetime").reset_index(drop=True)

        # Double-check empty before logging
        if not df.empty:
            logger.info(
                "Hisse OHLCV: %s - %d mum (%s -> %s)",
                resolved.symbol,
                len(df),
                str(df["datetime"].iloc[0])[:10],
                str(df["datetime"].iloc[-1])[:10],
            )
        else:
            logger.warning("Hisse OHLCV: %s - Veri bulunamadı (after processing)", resolved.symbol)
        
        return df

    # ── Birleşik Arayüz ───────────────────────────────────
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str | None = None,
        days: int | None = None,
    ) -> pd.DataFrame:
        """
        Sembol türüne göre otomatik olarak doğru kaynaktan veri çeker.
        """
        resolved = resolve_symbol(symbol)

        if resolved.asset_class == AssetClass.CRYPTO:
            return self.fetch_crypto_ohlcv(symbol, timeframe, days)
        else:
            # yfinance interval mapping
            tf_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "4h": "1h",
                "1d": "1d",
                "1w": "1wk",
            }
            interval = tf_map.get(timeframe or "1d", "1d")
            return self.fetch_stock_ohlcv(symbol, interval, days)

    def fetch_tickers(self) -> dict:
        """Binance'deki tüm ticker verilerini (fiyat, hacim, değişim) çeker. Thread-safe."""
        exchange = self._get_public_exchange()
        with self._exchange_public_lock:
            # Cache kontrolü (30s TTL)
            if self._tickers_cache is not None and (time.time() - self._tickers_cache_time) < self._tickers_cache_ttl:
                return self._tickers_cache
            try:
                tickers = exchange.fetch_tickers()
                self._tickers_cache = tickers
                self._tickers_cache_time = time.time()
                return tickers
            except ccxt.BaseError as e:
                logger.error("Ticker verisi çekme hatası: %s", e)
                return {}

    # ── VIX Verisi ─────────────────────────────────────────
    def fetch_vix(self, days: int = 90) -> pd.DataFrame:
        """VIX (CBOE Volatilite İndeksi) verisini çeker."""
        return self.fetch_stock_ohlcv("^VIX", interval="1d", days=days)

    # ── Binance Hesap Bakiyesi ─────────────────────────────
    def fetch_balance(self) -> dict:
        """Binance hesap bakiyesini çeker."""
        exchange = self._get_private_exchange()
        try:
            balance = exchange.fetch_balance()
            # Sadece sıfırdan büyük bakiyeleri filtrele
            non_zero = {
                k: v for k, v in balance.get("total", {}).items() if v and float(v) > 0
            }
            return {"total": non_zero, "free": balance.get("free", {})}
        except ccxt.BaseError as e:
            logger.error("Bakiye cekme hatasi: %s", e)
            return {"total": {}, "free": {}}

    # ── Güncel Fiyat ───────────────────────────────────────
    def fetch_current_price(self, symbol: str) -> float | None:
        """Sembolün güncel fiyatını döndürür."""
        resolved = resolve_symbol(symbol)

        if resolved.asset_class == AssetClass.CRYPTO:
            try:
                exchange = self._get_public_exchange()
                ticker = exchange.fetch_ticker(resolved.symbol)
                return float(ticker.get("last", 0))
            except ccxt.BaseError as e:
                logger.error("Fiyat hatasi (%s): %s", resolved.symbol, e)
                return None
        else:
            try:
                t = yf.Ticker(resolved.symbol)
                info = t.info
                return float(info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose", 0))
            except Exception as e:
                logger.error("Fiyat hatası (%s): %s", resolved.symbol, e)
                return None
    async def fetch_ohlcv_async(
        self,
        symbol: str,
        timeframe: str | None = None,
        days: int | None = None,
    ) -> pd.DataFrame:
        """
        Async versiyon - thread-safe exchange instance kullanır.
        
        Her async call için yeni exchange instance oluşturur,
        böylece concurrent call'larda thread-safety sağlanır.
        """
        import asyncio
        import ccxt
        
        # Thread-safe: Her async call için yeni public exchange instance
        def _fetch_with_new_exchange():
            temp_exchange = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            try:
                temp_exchange.load_markets()
                resolved = resolve_symbol(symbol)
                tf = timeframe or self._params.data.default_timeframe
                d = days or self._params.data.history_days
                since_ms = int(
                    (datetime.now(timezone.utc) - timedelta(days=d)).timestamp() * 1000
                )
                
                all_ohlcv = []
                fetch_since = since_ms
                
                while True:
                    batch = temp_exchange.fetch_ohlcv(
                        resolved.symbol,
                        timeframe=tf,
                        since=fetch_since,
                        limit=1000,
                    )
                    if not batch:
                        break
                    all_ohlcv.extend(batch)
                    fetch_since = batch[-1][0] + 1
                    if len(batch) < 1000:
                        break
                
                if not all_ohlcv:
                    return pd.DataFrame(
                        columns=["datetime", "open", "high", "low", "close", "volume"]
                    )
                
                df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.drop(columns=["timestamp"]).sort_values("datetime").reset_index(drop=True)
                return df
            finally:
                try:
                    temp_exchange.close()
                except Exception as close_err:
                    logger.debug("Exchange close error (async): %s", close_err)
        
        return await asyncio.to_thread(_fetch_with_new_exchange)

    async def fetch_balance_async(self) -> dict:
        """
        Async versiyon - thread-safe exchange instance kullanır.
        
        Her async call için yeni private exchange instance oluşturur.
        """
        import asyncio
        import ccxt
        
        def _fetch_with_new_exchange():
            config = {
                "apiKey": self._settings.binance_api_key,
                "secret": self._settings.binance_api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
            if self._settings.binance_testnet:
                config["sandbox"] = True
            
            temp_exchange = ccxt.binance(config)
            try:
                temp_exchange.load_markets()
                balance = temp_exchange.fetch_balance()
                return {
                    "total": {
                        k: v for k, v in balance.get("total", {}).items() 
                        if v and float(v) > 0
                    },
                    "free": balance.get("free", {}),
                }
            finally:
                try:
                    temp_exchange.close()
                except Exception as close_err:
                    logger.debug("Exchange close error (async balance): %s", close_err)
        
        return await asyncio.to_thread(_fetch_with_new_exchange)

    async def fetch_current_price_async(self, symbol: str) -> float | None:
        """
        Async versiyon - thread-safe exchange instance kullanır.
        
        Her async call için yeni public exchange instance oluşturur.
        """
        import asyncio
        import ccxt
        
        def _fetch_with_new_exchange():
            resolved = resolve_symbol(symbol)
            temp_exchange = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            try:
                temp_exchange.load_markets()
                ticker = temp_exchange.fetch_ticker(resolved.symbol)
                return float(ticker.get("last", 0))
            except ccxt.BaseError as e:
                logger.error("Fiyat hatasi (%s): %s", resolved.symbol, e)
                return None
            finally:
                try:
                    temp_exchange.close()
                except Exception as close_err:
                    logger.debug("Exchange close error (async price): %s", close_err)
        
        return await asyncio.to_thread(_fetch_with_new_exchange)
