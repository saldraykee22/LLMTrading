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

# US Market Holidays (approximate — varies by year)
US_MARKET_HOLIDAYS = {
    "new_years",  # Jan 1
    "mlk_day",  # 3rd Monday of January
    "presidents_day",  # 3rd Monday of February
    "good_friday",  # Varies
    "memorial_day",  # Last Monday of May
    "juneteenth",  # Jun 19
    "independence_day",  # Jul 4
    "labor_day",  # 1st Monday of September
    "thanksgiving",  # 4th Thursday of November
    "christmas",  # Dec 25
}

# BIST Holidays
BIST_HOLIDAYS = {
    "new_years",  # 1 Ocak
    "national_sov",  # 23 Nisan
    "labor_day",  # 1 Mayıs
    "commemoration",  # 19 Mayıs
    "democracy_day",  # 15 Temmuz
    "victory_day",  # 30 Ağustos
    "republic_day",  # 29 Ekim
    # Religious holidays vary — add as needed
}


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
        # Check holidays
        if asset == AssetClass.BIST:
            if cls._is_bist_holiday(now):
                return False
        elif asset == AssetClass.US_STOCK:
            if cls._is_us_holiday(now):
                return False
        open_h, open_m = BIST_OPEN_TRT if asset == AssetClass.BIST else US_OPEN_ET
        close_h, close_m = BIST_CLOSE_TRT if asset == AssetClass.BIST else US_CLOSE_ET
        open_time = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        close_time = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
        return open_time <= now < close_time

    @classmethod
    def _is_us_holiday(cls, now: datetime) -> bool:
        """Check if today is a US market holiday."""
        month, day = now.month, now.day
        # Fixed holidays
        if (month, day) in [(1, 1), (6, 19), (7, 4), (12, 25)]:
            return True
        # MLK Day (3rd Monday of January)
        if month == 1 and now.weekday() == 0 and 15 <= day <= 21:
            return True
        # Presidents Day (3rd Monday of February)
        if month == 2 and now.weekday() == 0 and 15 <= day <= 21:
            return True
        # Memorial Day (last Monday of May)
        if month == 5 and now.weekday() == 0 and day >= 25:
            return True
        # Labor Day (1st Monday of September)
        if month == 9 and now.weekday() == 0 and day <= 7:
            return True
        # Thanksgiving (4th Thursday of November)
        if month == 11 and now.weekday() == 3 and 22 <= day <= 28:
            return True
        return False

    @classmethod
    def _is_bist_holiday(cls, now: datetime) -> bool:
        """Check if today is a BIST holiday."""
        month, day = now.month, now.day
        # Fixed holidays
        if (month, day) in [
            (1, 1),  # Yılbaşı
            (4, 23),  # Ulusal Egemenlik
            (5, 1),  # İşçi Bayramı
            (5, 19),  # Atatürk'ü Anma
            (7, 15),  # Demokrasi
            (8, 30),  # Zafer Bayramı
            (10, 29),  # Cumhuriyet Bayramı
        ]:
            return True
        return False

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
