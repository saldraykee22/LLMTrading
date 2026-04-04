"""Unit tests for TechnicalAnalyzer."""

import numpy as np
import pandas as pd

from models.technical_analyzer import TechnicalAnalyzer, TechnicalSignals


def _make_ohlcv(n=100, trend="up"):
    """Create synthetic OHLCV data."""
    np.random.seed(42)
    if trend == "up":
        prices = 100 + np.cumsum(np.random.normal(0.1, 1, n))
    elif trend == "down":
        prices = 100 + np.cumsum(np.random.normal(-0.1, 1, n))
    else:
        prices = 100 + np.cumsum(np.random.normal(0, 1, n))

    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + np.abs(np.random.normal(0, 0.5, n)),
            "low": prices - np.abs(np.random.normal(0, 0.5, n)),
            "close": prices,
            "volume": np.random.uniform(1000, 5000, n),
        }
    )
    return df


class TestTechnicalAnalyzer:
    def test_analyze_returns_signals(self):
        df = _make_ohlcv(100)
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "TEST")
        assert isinstance(result, TechnicalSignals)
        assert result.symbol == "TEST"
        assert result.trend in ("bullish", "bearish", "neutral")
        assert result.signal in ("buy", "sell", "hold")

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "EMPTY")
        assert result.signal == "hold"
        assert result.trend == "neutral"

    def test_short_dataframe(self):
        df = _make_ohlcv(10)
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "SHORT")
        assert result.signal == "hold"

    def test_rsi_range(self):
        df = _make_ohlcv(200)
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "TEST")
        assert 0 <= result.rsi_14 <= 100

    def test_support_resistance_levels(self):
        df = _make_ohlcv(200)
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "TEST")
        assert isinstance(result.support_levels, list)
        assert isinstance(result.resistance_levels, list)

    def test_trend_strength_range(self):
        df = _make_ohlcv(200)
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "TEST")
        assert 0 <= result.trend_strength <= 1.0

    def test_to_dict(self):
        df = _make_ohlcv(200)
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "TEST")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "trend" in d
        assert "rsi_14" in d
        assert "signal" in d
