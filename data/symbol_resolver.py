"""
Sembol Çözümleme Modülü
========================
Farklı piyasalar için sembol formatlarını otomatik çözümler:
- Kripto: BTC/USDT, ETH/USDT (CCXT formatı)
- BIST:   BIMAS.IS, THYAO.IS (yfinance formatı)
- ABD:    AAPL, MSFT (yfinance formatı)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class AssetClass(str, Enum):
    CRYPTO = "crypto"
    BIST = "bist"
    US_STOCK = "us_stock"


@dataclass
class ResolvedSymbol:
    """Çözümlenmiş sembol bilgisi."""
    raw: str              # Kullanıcının girdiği ham sembol
    symbol: str           # Normalize edilmiş sembol
    asset_class: AssetClass
    exchange: str         # Borsa adı (binance, yahoo, vb.)
    base: str             # Temel varlık (BTC, AAPL, BIMAS)
    quote: str            # Karşılık birimi (USDT, USD, TRY)


# ── Bilinen BIST sembolleri (genişletilebilir) ─────────────
BIST_SYMBOLS = {
    "BIMAS", "THYAO", "SAHOL", "GARAN", "ASELS", "KCHOL",
    "TUPRS", "EREGL", "SISE", "AKBNK", "YKBNK", "HALKB",
    "TOASO", "FROTO", "ARCLK", "PETKM", "TAVHL", "TKFEN",
    "KOZAL", "KOZAA", "DOHOL", "ENKAI", "EKGYO", "ISCTR",
    "VAKBN", "PGSUS", "BERA", "SASA", "GUBRF", "KONTR",
}

# ── Kripto çift pattern ───────────────────────────────────
CRYPTO_PAIR_RE = re.compile(
    r"^([A-Z]{2,10})[/\-_]([A-Z]{2,10})$", re.IGNORECASE
)

CRYPTO_BASES = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE",
    "AVAX", "DOT", "MATIC", "LINK", "UNI", "ATOM", "LTC",
    "NEAR", "APT", "ARB", "OP", "SUI", "SEI", "TIA",
    "FET", "RENDER", "INJ", "PEPE", "WIF", "BONK",
}


def resolve_symbol(raw_input: str) -> ResolvedSymbol:
    """
    Ham sembol girdisini çözümler ve doğru formata dönüştürür.

    Örnekler:
        resolve_symbol("BTC/USDT")  → Crypto, binance
        resolve_symbol("BTCUSDT")   → Crypto, binance
        resolve_symbol("BIMAS")     → BIST, yahoo (.IS eklenir)
        resolve_symbol("AAPL")      → US Stock, yahoo
        resolve_symbol("THYAO.IS")  → BIST, yahoo (zaten formatlı)
    """
    raw = raw_input.strip().upper()

    # 1) Kripto çifti: BTC/USDT, ETH-USDT, SOL_USDT
    m = CRYPTO_PAIR_RE.match(raw)
    if m:
        base, quote = m.group(1), m.group(2)
        return ResolvedSymbol(
            raw=raw_input,
            symbol=f"{base}/{quote}",
            asset_class=AssetClass.CRYPTO,
            exchange="binance",
            base=base,
            quote=quote,
        )

    # 2) Kripto çifti (birleşik): BTCUSDT → BTC/USDT
    for base in sorted(CRYPTO_BASES, key=len, reverse=True):
        if raw.startswith(base) and len(raw) > len(base):
            quote = raw[len(base):]
            if quote in ("USDT", "BUSD", "USDC", "BTC", "ETH", "USD", "TRY"):
                return ResolvedSymbol(
                    raw=raw_input,
                    symbol=f"{base}/{quote}",
                    asset_class=AssetClass.CRYPTO,
                    exchange="binance",
                    base=base,
                    quote=quote,
                )

    # 3) BIST — zaten .IS eki var
    if raw.endswith(".IS"):
        base = raw[:-3]
        return ResolvedSymbol(
            raw=raw_input,
            symbol=raw,
            asset_class=AssetClass.BIST,
            exchange="yahoo",
            base=base,
            quote="TRY",
        )

    # 4) BIST — bilinen sembol, .IS ekle
    if raw in BIST_SYMBOLS:
        return ResolvedSymbol(
            raw=raw_input,
            symbol=f"{raw}.IS",
            asset_class=AssetClass.BIST,
            exchange="yahoo",
            base=raw,
            quote="TRY",
        )

    # 5) Bilinen kripto base (tek başına): BTC → BTC/USDT
    if raw in CRYPTO_BASES:
        return ResolvedSymbol(
            raw=raw_input,
            symbol=f"{raw}/USDT",
            asset_class=AssetClass.CRYPTO,
            exchange="binance",
            base=raw,
            quote="USDT",
        )

    # 6) Varsayılan: ABD hisse senedi
    return ResolvedSymbol(
        raw=raw_input,
        symbol=raw,
        asset_class=AssetClass.US_STOCK,
        exchange="yahoo",
        base=raw,
        quote="USD",
    )


def is_crypto(symbol: str) -> bool:
    """Sembolün kripto olup olmadığını kontrol eder."""
    return resolve_symbol(symbol).asset_class == AssetClass.CRYPTO


def is_bist(symbol: str) -> bool:
    """Sembolün BIST hissesi olup olmadığını kontrol eder."""
    return resolve_symbol(symbol).asset_class == AssetClass.BIST
