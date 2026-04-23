"""
Sembol Çözümleme Modülü
========================
Farklı piyasalar için sembol formatlarını otomatik çözümler:
- Kripto: BTC/USDT, ETH/USDT (CCXT formatı)
- BIST:   BIMAS.IS, THYAO.IS (yfinance formatı)
- ABD:    AAPL, MSFT (yfinance formatı)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AssetClass(str, Enum):
    CRYPTO = "crypto"
    BIST = "bist"
    US_STOCK = "us_stock"


@dataclass
class ResolvedSymbol:
    """Çözümlenmiş sembol bilgisi."""

    raw: str  # Kullanıcının girdiği ham sembol
    symbol: str  # Normalize edilmiş sembol
    asset_class: AssetClass
    exchange: str  # Borsa adı (binance, yahoo, vb.)
    base: str  # Temel varlık (BTC, AAPL, BIMAS)
    quote: str  # Karşılık birimi (USDT, USD, TRY)


# ── Bilinen BIST sembolleri (genişletilebilir) ─────────────
BIST_SYMBOLS = {
    "BIMAS",
    "THYAO",
    "SAHOL",
    "GARAN",
    "ASELS",
    "KCHOL",
    "TUPRS",
    "EREGL",
    "SISE",
    "AKBNK",
    "YKBNK",
    "HALKB",
    "TOASO",
    "FROTO",
    "ARCLK",
    "PETKM",
    "TAVHL",
    "TKFEN",
    "KOZAL",
    "KOZAA",
    "DOHOL",
    "ENKAI",
    "EKGYO",
    "ISCTR",
    "VAKBN",
    "PGSUS",
    "BERA",
    "SASA",
    "GUBRF",
    "KONTR",
    "HEKTS",
    "ENJSA",
    "OYAKC",
    "TTKOM",
    "TCELL",
    "SOKM",
    "MAVI",
    "ALARK",
    "BAGFS",
    "CANTE",
    "DOAS",
    "EGEEN",
    "GENIL",
    "HEKTS",
    "IPEKE",
    "KORDS",
    "MGROS",
}

# ── Kripto çift pattern ───────────────────────────────────
CRYPTO_PAIR_RE = re.compile(r"^([A-Z]{2,10})[/\-_]([A-Z]{2,10})$", re.IGNORECASE)

CRYPTO_BASES = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "DOT",
    "MATIC",
    "LINK",
    "UNI",
    "ATOM",
    "LTC",
    "NEAR",
    "APT",
    "ARB",
    "OP",
    "SUI",
    "SEI",
    "TIA",
    "FET",
    "RENDER",
    "INJ",
    "PEPE",
    "WIF",
    "BONK",
}


def validate_symbol(raw_input: str) -> bool:
    """
    Sembol formatını doğrula - güvenlik ve enjeksiyon koruması.
    
    Kurallar:
    - Maksimum 50 karakter
    - Sadece harf (A-Z), rakam (0-9), ve özel karakterler: / - _ .
    - Tehlikeli pattern'leri engelle (path traversal, command injection)
    """
    if not raw_input:
        return False
    
    if len(raw_input) > 50:
        return False
    
    # Tehlikeli pattern'leri engelle
    dangerous_patterns = [
        r'\.\.',  # Path traversal
        r'[;&|`$]',  # Command injection
        r'[<>]',  # HTML/XML injection
        r'[\x00-\x1f]',  # Control characters
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, raw_input):
            return False
    
    # İzin verilen karakterler: harf, rakam, /, -, _, ., boşluk
    allowed_pattern = r'^[A-Za-z0-9/\-_\.\s]+$'
    return bool(re.match(allowed_pattern, raw_input))


def resolve_symbol(raw_input: str) -> ResolvedSymbol:
    """
    Ham sembol girdisini çözümler ve doğru formata dönüştürür.

    Örnekler:
        resolve_symbol("BTC/USDT")  → Crypto, binance
        resolve_symbol("BTCUSDT")   → Crypto, binance
        resolve_symbol("BIMAS")     → BIST, yahoo (.IS eklenir)
        resolve_symbol("AAPL")      → US Stock, yahoo
        resolve_symbol("THYAO.IS")  → BIST, yahoo (zaten formatlı)
    
    Raises:
        ValueError: Geçersiz sembol formatı
    """
    # Güvenlik doğrulaması
    if not validate_symbol(raw_input):
        raise ValueError(f"Geçersiz sembol formatı: {raw_input}")
    
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
            quote = raw[len(base) :]
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


def refresh_crypto_bases(exchange_name: str = "binance") -> set[str]:
    """
    Fetch current trading pairs from exchange and update CRYPTO_BASES.
    Returns the set of base currencies found.
    """
    try:
        import ccxt

        exchange_class = getattr(ccxt, exchange_name, None)
        if exchange_class is None:
            return CRYPTO_BASES

        exchange = exchange_class({"enableRateLimit": True})
        markets = exchange.load_markets()

        bases: set[str] = set()
        for symbol in markets:
            market = markets[symbol]
            if market.get("base") and market.get("quote") in (
                "USDT",
                "BTC",
                "ETH",
                "USDC",
            ):
                bases.add(market["base"])

        CRYPTO_BASES.clear()
        CRYPTO_BASES.update(bases)
        logger.info("Crypto bases refreshed: %d bases found", len(bases))
        return bases
    except Exception as e:
        logger.warning("Failed to refresh crypto bases: %s", e)
        return CRYPTO_BASES
