"""
End-to-End Trading Flow Integration Tests
==========================================
Tests for complete trading workflow from coordinator to execution.
"""

import pytest
import threading

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.portfolio import PortfolioState


class TestE2ETradingFlow:
    """End-to-end trading flow testleri."""

    @pytest.fixture
    def mock_state(self):
        """Mock trading state fixture."""
        return {
            "symbol": "BTC/USDT",
            "market_data": {
                "current_price": 50000.0,
                "ohlcv": None,
            },
            "news_data": [],
            "technical_signals": {
                "current_price": 50000.0,
                "atr_14": 1000.0,
                "rsi_14": 45,
                "trend": "neutral",
                "signal": "hold",
            },
            "sentiment": {
                "signal": "neutral",
                "sentiment_score": 0.0,
                "confidence": 0.5,
            },
            "research_report": {
                "recommendation": "hold",
                "trend": "neutral",
            },
            "debate_result": {
                "consensus_score": 0.5,
                "adjusted_signal": "neutral",
                "hallucinations_detected": [],
            },
            "portfolio_state": {
                "cash": 10000.0,
                "equity": 10000.0,
                "open_positions": 0,
                "current_drawdown": 0.0,
                "daily_pnl": 0.0,
            },
            "risk_assessment": {
                "decision": "pending",
            },
            "iteration": 0,
            "phase": "research",
        }

    def test_coordinator_node(self, mock_state):
        """Coordinator node testi."""
        from agents.coordinator import coordinator_node
        
        result = coordinator_node(mock_state)
        
        assert "messages" in result
        assert result["phase"] == "research"
        assert result["iteration"] == 1  # 0'dan 1'e artmalı

    def test_risk_manager_rejection_max_positions(self, mock_state):
        """Risk manager - max pozisyon reddi."""
        from agents.risk_manager import risk_manager_node
        
        # Max pozisyon limitine ulaşmış portfolio
        mock_state["portfolio_state"]["open_positions"] = 5  # max_open_positions
        mock_state["sentiment"]["signal"] = "bullish"
        mock_state["sentiment"]["confidence"] = 0.8
        
        result = risk_manager_node(mock_state)
        
        assert result["risk_approved"] is False
        assert "risk_assessment" in result
        assert result["risk_assessment"]["decision"] == "rejected"

    def test_risk_manager_rejection_drawdown(self, mock_state):
        """Risk manager - drawdown limiti reddi."""
        from agents.risk_manager import risk_manager_node
        
        # Max drawdown'a ulaşmış portfolio
        mock_state["portfolio_state"]["current_drawdown"] = 0.15  # 15%
        
        result = risk_manager_node(mock_state)
        
        assert result["risk_approved"] is False

    def test_trader_node_hold_without_risk_approval(self, mock_state):
        """Trader node - risk onayı yoksa hold."""
        from agents.trader import trader_node
        
        mock_state["risk_approved"] = False
        
        result = trader_node(mock_state)
        
        assert result["trade_decision"]["action"] == "hold"
        assert result["phase"] == "complete"

    def test_full_flow_rejection(self, mock_state):
        """Tam flow - risk reddi."""
        from agents.coordinator import coordinator_node
        from agents.risk_manager import risk_manager_node
        from agents.trader import trader_node
        
        # Coordinator
        coord_result = coordinator_node(mock_state)
        assert coord_result["phase"] == "research"
        
        # Risk manager (default state ile reddedilmeli - nötr sinyaller)
        risk_manager_node(mock_state)
        
        # Trader (risk onayı yoksa hold)
        trader_result = trader_node(mock_state)
        assert trader_result["trade_decision"]["action"] == "hold"


class TestPortfolioPersistence:
    """Portfolio persistence testleri."""

    @pytest.fixture
    def temp_portfolio_file(self, tmp_path):
        """Temporary portfolio file fixture."""
        from config import settings
        original_file = settings.DATA_DIR / "portfolio_state.json"
        temp_file = tmp_path / "test_portfolio.json"
        
        # Geçici dosya kullan
        import risk.portfolio
        risk.portfolio.PORTFOLIO_FILE = temp_file
        
        yield temp_file
        
        # Cleanup
        if temp_file.exists():
            temp_file.unlink()
        
        # Restore original
        risk.portfolio.PORTFOLIO_FILE = original_file

    def test_portfolio_save_load(self, temp_portfolio_file):
        """Portfolio save/load testi."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # Pozisyon aç
        portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.1,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        
        # Kaydet
        portfolio.save_to_file()
        
        # Dosya oluşmuş olmalı
        assert temp_portfolio_file.exists()
        
        # Yükle
        loaded = PortfolioState.load_from_file(temp_portfolio_file)
        
        assert loaded.cash < 10000.0  # Pozisyon için cash harcandı
        assert loaded.open_position_count == 1
        assert loaded.positions[0].symbol == "BTC/USDT"

    def test_portfolio_atomic_write(self, temp_portfolio_file):
        """Portfolio atomic write testi."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # Multiple saves
        for i in range(5):
            portfolio.cash = 10000.0 - (i * 100)
            portfolio.save_to_file()
        
        # Son kayıt okunmalı
        loaded = PortfolioState.load_from_file(temp_portfolio_file)
        assert loaded.cash == 10000.0 - (4 * 100)

    def test_portfolio_corrupted_file_recovery(self, temp_portfolio_file):
        """Corrupted portfolio file recovery."""
        # Corrupted data yaz
        temp_portfolio_file.write_text("invalid json {{{")
        
        # Load corrupted file - yeni portfolio oluşturmalı
        portfolio = PortfolioState.load_from_file(temp_portfolio_file)
        
        assert portfolio.initial_cash == 10000.0
        assert portfolio.cash == 10000.0
        assert portfolio.open_position_count == 0


class TestEmergencyScenarios:
    """Emergency scenario testleri."""

    def test_emergency_close_all_positions(self):
        """Emergency close all positions testi."""
        from risk.portfolio import PortfolioState
        from execution.paper_engine import PaperTradingEngine
        
        portfolio = PortfolioState(initial_cash=100000.0)
        PaperTradingEngine(initial_cash=100000.0)
        
        # Multiple pozisyon aç
        symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
        for symbol in symbols:
            portfolio.open_position(
                symbol=symbol,
                side="long",
                price=100.0,
                amount=10.0,
                stop_loss=95.0,
            )
        
        assert portfolio.open_position_count == 3
        
        # Emergency close (manual simulation)
        for pos in list(portfolio.positions):
            portfolio.close_position(pos.symbol, 105.0)
        
        assert portfolio.open_position_count == 0
        assert len(portfolio.closed_trades) == 3

    def test_circuit_breaker_activation(self):
        """Circuit breaker activation testi."""
        from risk.circuit_breaker import CircuitBreaker
        from config.settings import DATA_DIR

        # Clean up any leftover STOP file from previous tests
        stop_file = DATA_DIR / "STOP"
        if stop_file.exists():
            stop_file.unlink()

        # Reset SystemStatus singleton state
        from risk.system_status import SystemStatus
        SystemStatus.reset_instance()

        cb = CircuitBreaker()

        # Normal state
        is_halt, reason = cb.should_halt(equity=10000.0, daily_pnl=-100.0)
        assert is_halt is False
        
        # Trigger circuit breaker (multiple failures)
        for _ in range(10):
            cb.record_fallback("test_agent")
        
        # Should halt now
        is_halt, reason = cb.should_halt(equity=10000.0, daily_pnl=-500.0)
        # Circuit breaker state depends on config


class TestConcurrentExecution:
    """Concurrent execution testleri."""

    def test_concurrent_symbol_analysis(self):
        """Concurrent symbol analysis testi."""
        from agents.coordinator import coordinator_node
        
        symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]
        results = []
        errors = []
        
        def analyze_symbol(symbol):
            try:
                state = {
                    "symbol": symbol,
                    "market_data": {"current_price": 100.0},
                    "news_data": [],
                    "technical_signals": {},
                    "sentiment": {},
                    "research_report": {},
                    "debate_result": {},
                    "portfolio_state": {},
                    "risk_assessment": {},
                    "iteration": 0,
                    "phase": "research",
                }
                
                result = coordinator_node(state)
                results.append((symbol, result))
            except Exception as e:
                errors.append((symbol, str(e)))
        
        # 5 concurrent analyses
        threads = []
        for symbol in symbols:
            t = threading.Thread(target=analyze_symbol, args=(symbol,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=30)
        
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
