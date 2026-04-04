"""Unit tests for Symbol Resolver."""

from data.symbol_resolver import resolve_symbol, is_crypto, is_bist, AssetClass


class TestSymbolResolver:
    def test_crypto_pair(self):
        r = resolve_symbol("BTC/USDT")
        assert r.asset_class == AssetClass.CRYPTO
        assert r.symbol == "BTC/USDT"
        assert r.exchange == "binance"
        assert r.base == "BTC"
        assert r.quote == "USDT"

    def test_crypto_merged(self):
        r = resolve_symbol("BTCUSDT")
        assert r.asset_class == AssetClass.CRYPTO
        assert r.symbol == "BTC/USDT"

    def test_crypto_base_only(self):
        r = resolve_symbol("ETH")
        assert r.asset_class == AssetClass.CRYPTO
        assert r.symbol == "ETH/USDT"

    def test_bist_with_is_suffix(self):
        r = resolve_symbol("THYAO.IS")
        assert r.asset_class == AssetClass.BIST
        assert r.symbol == "THYAO.IS"
        assert r.quote == "TRY"

    def test_bist_known_symbol(self):
        r = resolve_symbol("BIMAS")
        assert r.asset_class == AssetClass.BIST
        assert r.symbol == "BIMAS.IS"

    def test_us_stock(self):
        r = resolve_symbol("AAPL")
        assert r.asset_class == AssetClass.US_STOCK
        assert r.symbol == "AAPL"
        assert r.quote == "USD"

    def test_is_crypto(self):
        assert is_crypto("BTC/USDT") is True
        assert is_crypto("AAPL") is False

    def test_is_bist(self):
        assert is_bist("THYAO.IS") is True
        assert is_bist("BIMAS") is True
        assert is_bist("AAPL") is False
