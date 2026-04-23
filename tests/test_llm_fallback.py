"""
LLM Fallback Mekanizması Testleri
==================================
Graceful degradation fallback değerlerini test eder.
"""

import json
import pytest
from unittest.mock import Mock, patch

from utils.llm_retry import invoke_with_retry


class TestInvokeWithRetryFallback:
    """invoke_with_retry fallback mekanizması testleri."""

    def test_fallback_on_error_string_value(self):
        """Fallback on error - string JSON value."""
        def failing_fn(*args, **kwargs):
            raise Exception("API Error")
        
        fallback_json = json.dumps({
            "test": "fallback",
            "value": 123
        })
        
        result = invoke_with_retry(
            failing_fn,
            fallback_on_error=True,
            fallback_value=fallback_json,
            max_retries=1,
        )
        
        # Mock response objesi dönmeli
        assert hasattr(result, "content")
        assert result.content == fallback_json
        
        # JSON parse edilebilir olmalı
        parsed = json.loads(result.content)
        assert parsed["test"] == "fallback"
        assert parsed["value"] == 123

    def test_fallback_on_error_dict_value(self):
        """Fallback on error - dict value."""
        def failing_fn(*args, **kwargs):
            raise Exception("API Error")
        
        fallback_dict = {
            "decision": "rejected",
            "reason": "API error"
        }
        
        result = invoke_with_retry(
            failing_fn,
            fallback_on_error=True,
            fallback_value=fallback_dict,
            max_retries=1,
        )

        # Dict fallback -> _MockResponse with .content as JSON string
        assert hasattr(result, 'content')
        import json
        content = json.loads(result.content)
        assert content["decision"] == "rejected"
        assert content["reason"] == "API error"

    def test_fallback_disabled_raises_exception(self):
        """Fallback kapalıysa exception fırlatılmalı."""
        def failing_fn(*args, **kwargs):
            raise Exception("API Error")
        
        with pytest.raises(Exception) as exc_info:
            invoke_with_retry(
                failing_fn,
                fallback_on_error=False,
                max_retries=1,
            )
        
        assert "API Error" in str(exc_info.value)

    def test_fallback_default_disabled(self):
        """Fallback varsayılan olarak kapalı olmalı."""
        def failing_fn(*args, **kwargs):
            raise Exception("API Error")
        
        with pytest.raises(Exception):
            invoke_with_retry(
                failing_fn,
                max_retries=1,
                # fallback_on_error belirtilmemiş
            )

    def test_success_no_fallback_needed(self):
        """Başarılı çağrıda fallback kullanılmaz."""
        from unittest.mock import MagicMock
        
        def success_fn(*args, **kwargs):
            # LangChain AIMessage formatını simüle et
            mock_response = MagicMock()
            mock_response.content = '{"status": "success"}'
            return mock_response
        
        result = invoke_with_retry(
            success_fn,
            fallback_on_error=True,
            fallback_value='{"fallback": "value"}',
            max_retries=1,
        )
        
        # Başarılı çağrıda response dönmeli (fallback değil)
        assert hasattr(result, "content")
        assert result.content == '{"status": "success"}'


class TestAgentFallbacks:
    """Ajan bazlı fallback testleri."""

    def test_sentiment_analyzer_fallback(self):
        """SentimentAnalyzer fallback ile nötr dönüş."""
        from models.sentiment_analyzer import SentimentAnalyzer
        from data.news_data import NewsItem
        from datetime import datetime, timezone
        
        # Mock LLM ile test
        with patch('models.sentiment_analyzer.create_llm') as mock_create:
            mock_llm = Mock()
            mock_llm.invoke.side_effect = Exception("API Error")
            mock_create.return_value = mock_llm
            
            analyzer = SentimentAnalyzer(provider="openrouter")
            news_item = NewsItem(
                title="Test News",
                summary="Test summary",
                source="Test",
                url="http://test.com",
                published_at=datetime.now(timezone.utc),
                symbols=["BTC"],
                category="general"
            )
            
            result = analyzer.analyze(
                symbol="ERROR_TEST_SYMBOL",
                news=[news_item],
                technical_data=None,
                save=False
            )
            
            # Fallback değerleri
            assert result.signal == "neutral"
            assert result.sentiment_score == 0.0
            assert result.confidence == 0.5

    def test_risk_manager_fallback_reject(self):
        """RiskManager fallback ile reject kararı."""
        from agents.risk_manager import risk_manager_node
        
        # Mock state
        state = {
            "symbol": "ERROR_TEST_SYMBOL",
            "sentiment": {"confidence": 0.8, "signal": "bullish"},
            "research_report": {"recommendation": "buy"},
            "debate_result": {"consensus_score": 0.5},
            "technical_signals": {"current_price": 50000},
            "portfolio_state": {
                "equity": 10000,
                "open_positions": 0,
                "current_drawdown": 0.0
            },
            "market_data": {"current_price": 50000}
        }
        
        # Mock LLM
        with patch('agents.risk_manager.create_agent_llm') as mock_create:
            mock_llm = Mock()
            mock_llm.invoke.side_effect = Exception("API Error")
            mock_create.return_value = mock_llm
            
            result = risk_manager_node(state)
            
            # Fallback: reject (güvenlik)
            assert result["risk_approved"] == False
            assert result["risk_assessment"]["decision"] == "rejected"
            assert result["risk_assessment"]["approved_size"] == 0

    def test_trader_fallback_hold(self):
        """Trader fallback ile hold kararı."""
        from agents.trader import trader_node
        
        # Mock state
        state = {
            "symbol": "ERROR_TEST_SYMBOL",
            "sentiment": {"sentiment_score": 0.5, "signal": "bullish"},
            "research_report": {"recommendation": "buy"},
            "debate_result": {"adjusted_signal": "bullish", "consensus_score": 0.6},
            "risk_assessment": {
                "decision": "approved",
                "approved_size": 1000,
                "stop_loss_level": 49000,
                "take_profit_level": 52000
            },
            "technical_signals": {"current_price": 50000},
            "market_data": {"current_price": 50000}
        }
        
        # Mock LLM
        with patch('agents.trader.create_agent_llm') as mock_create:
            mock_llm = Mock()
            mock_llm.invoke.side_effect = Exception("API Error")
            mock_create.return_value = mock_llm
            
            result = trader_node(state)
            
            # Fallback: hold (işlem yapma)
            assert result["trade_decision"]["action"] == "hold"
            assert result["trade_decision"]["amount"] == 0
            assert result["trade_decision"]["confidence"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
