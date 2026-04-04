from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data.symbol_resolver import (
    BIST_SYMBOLS,
    CRYPTO_BASES,
    CRYPTO_PAIR_RE,
    AssetClass,
    resolve_symbol,
)

CRYPTO_QUOTE_SUFFIXES = {"USDT", "BTC", "ETH", "BUSD", "USDC", "USD", "TRY"}
BIST_OPEN_TRT = (10, 0)
BIST_CLOSE_TRT = (18, 0)
US_OPEN_ET = (9, 30)
US_CLOSE_ET = (16, 0)


class MarketHours:
    _tz_trt = ZoneInfo("Europe/Istanbul")
    _tz_et = ZoneInfo("America/New_York")

    @classmethod
    def _detect_asset_class(cls, symbol: str) -> AssetClass:
        raw = symbol.strip().upper()
        m = CRYPTO_PAIR_RE.match(raw)
        if m and m.group(2) in CRYPTO_QUOTE_SUFFIXES:
            return AssetClass.CRYPTO
        for base in sorted(CRYPTO_BASES, key=len, reverse=True):
            if raw.startswith(base) and len(raw) > len(base):
                suffix = raw[len(base) :]
                if suffix in CRYPTO_QUOTE_SUFFIXES or suffix.startswith("/"):
                    return AssetClass.CRYPTO
        if raw.endswith(".IS"):
            return AssetClass.BIST
        if raw in BIST_SYMBOLS:
            return AssetClass.BIST
        if raw in CRYPTO_BASES:
            return AssetClass.CRYPTO
        return AssetClass.US_STOCK

    @classmethod
    def _now_in_tz(cls, tz: ZoneInfo) -> datetime:
        return datetime.now(tz)

    @classmethod
    def is_market_open(cls, symbol: str) -> bool:
        asset = cls._detect_asset_class(symbol)
        if asset == AssetClass.CRYPTO:
            return True
        now = cls._now_in_tz(cls._tz_trt if asset == AssetClass.BIST else cls._tz_et)
        if now.weekday() >= 5:
            return False
        open_h, open_m = BIST_OPEN_TRT if asset == AssetClass.BIST else US_OPEN_ET
        close_h, close_m = BIST_CLOSE_TRT if asset == AssetClass.BIST else US_CLOSE_ET
        open_time = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        close_time = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
        return open_time <= now < close_time

    @classmethod
    def time_until_open(cls, symbol: str) -> timedelta:
        asset = cls._detect_asset_class(symbol)
        if asset == AssetClass.CRYPTO:
            return timedelta(0)
        tz = cls._tz_trt if asset == AssetClass.BIST else cls._tz_et
        now = cls._now_in_tz(tz)
        open_h, open_m = BIST_OPEN_TRT if asset == AssetClass.BIST else US_OPEN_ET
        open_time = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        if now.weekday() < 5 and now < open_time:
            return open_time - now
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_open = open_time + timedelta(days=days_until_monday)
        return next_open - now

    @classmethod
    def get_market_info(cls, symbol: str) -> dict:
        asset = cls._detect_asset_class(symbol)
        if asset == AssetClass.CRYPTO:
            return {
                "market": "Crypto",
                "timezone": "UTC",
                "open": "00:00",
                "close": "23:59",
                "schedule": "24/7",
                "is_open": True,
            }
        if asset == AssetClass.BIST:
            now = cls._now_in_tz(cls._tz_trt)
            open_h, open_m = BIST_OPEN_TRT
            close_h, close_m = BIST_CLOSE_TRT
            return {
                "market": "BIST (Istanbul Stock Exchange)",
                "timezone": "TRT (UTC+3)",
                "open": f"{open_h:02d}:{open_m:02d}",
                "close": f"{close_h:02d}:{close_m:02d}",
                "schedule": "Monday-Friday",
                "is_open": cls.is_market_open(symbol),
            }
        now = cls._now_in_tz(cls._tz_et)
        open_h, open_m = US_OPEN_ET
        close_h, close_m = US_CLOSE_ET
        dst_str = "EDT (UTC-4)" if now.dst() != timedelta(0) else "EST (UTC-5)"
        return {
            "market": "US Stocks (NYSE/NASDAQ)",
            "timezone": dst_str,
            "open": f"{open_h:02d}:{open_m:02d}",
            "close": f"{close_h:02d}:{close_m:02d}",
            "schedule": "Monday-Friday",
            "is_open": cls.is_market_open(symbol),
        }
