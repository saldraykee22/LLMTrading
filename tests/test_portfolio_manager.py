"""Unit tests for Portfolio Manager."""


from agents.portfolio_manager import SymbolAnalysis


class TestSymbolAnalysis:
    def test_composite_score_bullish(self):
        ana = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.6,
            sentiment_confidence=0.8,
            debate_consensus=0.7,
            debate_winner="bull",
            hallucinations=0,
            risk_approved=True,
            trend="bullish",
            trend_strength=0.6,
            rsi=55.0,
        )
        score = ana.calculate_composite_score()
        assert score > 0
        assert score <= 1.0

    def test_composite_score_bearish(self):
        ana = SymbolAnalysis(
            symbol="XYZ/USDT",
            sentiment_score=-0.5,
            sentiment_confidence=0.7,
            debate_consensus=-0.6,
            debate_winner="bear",
            hallucinations=3,
            risk_approved=False,
            trend="bearish",
            trend_strength=-0.5,
            rsi=75.0,
        )
        score = ana.calculate_composite_score()
        assert score < 0
        assert score >= -1.0

    def test_composite_score_neutral(self):
        ana = SymbolAnalysis(
            symbol="ETH/USDT",
            sentiment_score=0.0,
            sentiment_confidence=0.5,
            debate_consensus=0.0,
            debate_winner="draw",
            hallucinations=0,
            risk_approved=True,
            trend="neutral",
            trend_strength=0.0,
            rsi=50.0,
        )
        score = ana.calculate_composite_score()
        assert -0.1 <= score <= 0.1

    def test_low_confidence_reduces_score(self):
        high_conf = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.5,
            sentiment_confidence=0.9,
            debate_consensus=0.5,
            debate_winner="bull",
            risk_approved=True,
            trend="bullish",
            trend_strength=0.5,
            rsi=55.0,
        )
        low_conf = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.5,
            sentiment_confidence=0.2,
            debate_consensus=0.5,
            debate_winner="bull",
            risk_approved=True,
            trend="bullish",
            trend_strength=0.5,
            rsi=55.0,
        )
        high_score = high_conf.calculate_composite_score()
        low_score = low_conf.calculate_composite_score()
        assert high_score > low_score

    def test_rsi_overbought_reduces_score(self):
        normal = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.5,
            sentiment_confidence=0.7,
            debate_consensus=0.5,
            debate_winner="bull",
            risk_approved=True,
            trend="bullish",
            trend_strength=0.5,
            rsi=55.0,
        )
        overbought = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.5,
            sentiment_confidence=0.7,
            debate_consensus=0.5,
            debate_winner="bull",
            risk_approved=True,
            trend="bullish",
            trend_strength=0.5,
            rsi=80.0,
        )
        normal_score = normal.calculate_composite_score()
        overbought_score = overbought.calculate_composite_score()
        assert normal_score > overbought_score

    def test_rsi_oversold_increases_score(self):
        normal = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.5,
            sentiment_confidence=0.7,
            debate_consensus=0.5,
            debate_winner="bull",
            risk_approved=True,
            trend="bullish",
            trend_strength=0.5,
            rsi=55.0,
        )
        oversold = SymbolAnalysis(
            symbol="BTC/USDT",
            sentiment_score=0.5,
            sentiment_confidence=0.7,
            debate_consensus=0.5,
            debate_winner="bull",
            risk_approved=True,
            trend="bullish",
            trend_strength=0.5,
            rsi=20.0,
        )
        normal_score = normal.calculate_composite_score()
        oversold_score = oversold.calculate_composite_score()
        assert oversold_score > normal_score
