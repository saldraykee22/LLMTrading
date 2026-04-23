"""
Data Validation Tests
======================
Tests for position, order, and portfolio validation.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.portfolio import Position, PortfolioState
from execution.order_manager import TradeOrder, parse_trade_decision
from config.constants import MIN_PRICE, MIN_AMOUNT, MAX_PRICE, MAX_AMOUNT


class TestPositionValidation:
    """Position validation testleri."""

    def test_valid_position_creation(self):
        """Valid position creation."""
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time="2024-01-01T00:00:00Z",
            side="long",
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        
        assert pos.symbol == "BTC/USDT"
        assert pos.entry_price == 50000.0
        assert pos.amount == 0.1
        assert pos.side == "long"

    def test_invalid_symbol_empty(self):
        """Empty symbol validation."""
        with pytest.raises(ValueError, match="Invalid symbol"):
            Position(
                symbol="",
                entry_price=50000.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_symbol_too_long(self):
        """Symbol too long validation."""
        with pytest.raises(ValueError, match="Symbol too long"):
            Position(
                symbol="A" * 51,  # 51 chars > 50 max
                entry_price=50000.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_entry_price_negative(self):
        """Negative entry price validation."""
        with pytest.raises(ValueError, match="entry_price must be positive"):
            Position(
                symbol="BTC/USDT",
                entry_price=-100.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_entry_price_zero(self):
        """Zero entry price validation."""
        with pytest.raises(ValueError, match="entry_price must be positive"):
            Position(
                symbol="BTC/USDT",
                entry_price=0.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_entry_price_too_small(self):
        """Entry price below minimum validation."""
        with pytest.raises(ValueError, match="below minimum"):
            Position(
                symbol="BTC/USDT",
                entry_price=MIN_PRICE / 2,  # Below min
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_entry_price_too_large(self):
        """Entry price above maximum validation."""
        with pytest.raises(ValueError, match="above maximum"):
            Position(
                symbol="BTC/USDT",
                entry_price=MAX_PRICE * 2,  # Above max
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_amount_negative(self):
        """Negative amount validation."""
        with pytest.raises(ValueError, match="amount must be positive"):
            Position(
                symbol="BTC/USDT",
                entry_price=50000.0,
                amount=-0.1,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_amount_zero(self):
        """Zero amount validation."""
        with pytest.raises(ValueError, match="amount must be positive"):
            Position(
                symbol="BTC/USDT",
                entry_price=50000.0,
                amount=0.0,
                entry_time="2024-01-01T00:00:00Z",
            )

    def test_invalid_side_short(self):
        """Short side validation (SPOT only supports long)."""
        with pytest.raises(ValueError, match="SPOT only supports long"):
            Position(
                symbol="BTC/USDT",
                entry_price=50000.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
                side="short",
            )

    def test_invalid_stop_loss_negative(self):
        """Negative stop-loss validation."""
        with pytest.raises(ValueError, match="stop_loss cannot be negative"):
            Position(
                symbol="BTC/USDT",
                entry_price=50000.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
                stop_loss=-100.0,
            )

    def test_invalid_take_profit_negative(self):
        """Negative take-profit validation."""
        with pytest.raises(ValueError, match="take_profit cannot be negative"):
            Position(
                symbol="BTC/USDT",
                entry_price=50000.0,
                amount=0.1,
                entry_time="2024-01-01T00:00:00Z",
                take_profit=-100.0,
            )

    def test_invalid_entry_time_empty(self):
        """Empty entry time validation."""
        with pytest.raises(ValueError, match="entry_time is required"):
            Position(
                symbol="BTC/USDT",
                entry_price=50000.0,
                amount=0.1,
                entry_time="",
            )

    def test_valid_position_zero_sl_tp(self):
        """Valid position with zero SL/TP (optional)."""
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time="2024-01-01T00:00:00Z",
            stop_loss=0.0,
            take_profit=0.0,
        )
        
        assert pos.stop_loss == 0.0
        assert pos.take_profit == 0.0


class TestTradeOrderValidation:
    """TradeOrder validation testleri."""

    def test_valid_buy_order(self):
        """Valid buy order."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="limit",
            amount=0.1,
            price=50000.0,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        
        valid, msg = order.validate()
        assert valid is True
        assert msg == "OK"

    def test_valid_market_order_with_current_price(self):
        """Valid market order with current price for SL/TP check."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            price=None,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        
        # Market order için current_price ile validate et
        valid, msg = order.validate(current_price=50000.0)
        assert valid is True

    def test_invalid_action(self):
        """Invalid action validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="hold",  # Invalid
            order_type="market",
            amount=0.1,
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "Geçersiz aksiyon" in msg

    def test_invalid_amount_negative(self):
        """Negative amount validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=-0.1,
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "Geçersiz miktar" in msg or "amount" in msg

    def test_invalid_amount_zero(self):
        """Zero amount validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.0,
        )
        
        valid, msg = order.validate()
        assert valid is False

    def test_invalid_symbol_empty(self):
        """Empty symbol validation."""
        order = TradeOrder(
            symbol="",
            action="buy",
            order_type="market",
            amount=0.1,
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "sembol" in msg.lower() or "symbol" in msg.lower()

    def test_limit_order_missing_price(self):
        """Limit order without price validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="limit",
            amount=0.1,
            price=None,
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "fiyat" in msg.lower() or "price" in msg.lower()

    def test_buy_order_sl_above_entry(self):
        """Buy order with SL above entry price validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="limit",
            amount=0.1,
            price=50000.0,
            stop_loss=51000.0,  # Above entry - invalid for buy
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "KÜÇÜK olmalı" in msg

    def test_buy_order_tp_below_entry(self):
        """Buy order with TP below entry price validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="limit",
            amount=0.1,
            price=50000.0,
            take_profit=49000.0,  # Below entry - invalid for buy
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "büyük olmalı" in msg

    def test_market_order_sl_validation_with_current_price(self):
        """Market order SL validation using current_price."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            stop_loss=51000.0,  # Above current price - invalid
        )
        
        valid, msg = order.validate(current_price=50000.0)
        assert valid is False

    def test_confidence_out_of_range(self):
        """Confidence out of 0-1 range validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            stop_loss=49000.0,
            confidence=1.5,  # > 1 - invalid
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "confidence" in msg.lower()

    def test_execution_size_pct_out_of_range(self):
        """Execution size pct out of 0-1 range validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            stop_loss=49000.0,
            execution_size_pct=1.5,  # > 1 - invalid
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "execution_size_pct" in msg.lower()

    def test_missing_stop_loss_buy_order(self):
        """Buy order without stop-loss validation."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            stop_loss=0.0,  # Missing SL
        )
        
        valid, msg = order.validate()
        assert valid is False
        assert "Stop-Loss" in msg


class TestPortfolioTypeConversion:
    """Portfolio type conversion testleri."""

    def test_portfolio_with_string_values(self):
        """Portfolio state with string values (from JSON)."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # Simulate dict from JSON (all values are strings)
        portfolio_dict = {
            "open_positions": "2",
            "current_drawdown": "0.05",
            "equity": "9500",
            "daily_pnl": "-100",
        }
        
        # Type-safe access
        open_positions = int(portfolio_dict.get("open_positions", 0) or 0)
        current_dd = float(portfolio_dict.get("current_drawdown", 0) or 0)
        equity = float(portfolio_dict.get("equity", 10000) or 10000)
        daily_pnl = float(portfolio_dict.get("daily_pnl", 0) or 0)
        
        assert open_positions == 2
        assert current_dd == 0.05
        assert equity == 9500.0
        assert daily_pnl == -100.0

    def test_portfolio_with_none_values(self):
        """Portfolio state with None values."""
        portfolio_dict = {
            "open_positions": None,
            "current_drawdown": None,
            "equity": None,
            "daily_pnl": None,
        }
        
        # Type-safe access (None → default)
        open_positions = int(portfolio_dict.get("open_positions", 0) or 0)
        current_dd = float(portfolio_dict.get("current_drawdown", 0) or 0)
        equity = float(portfolio_dict.get("equity", 10000) or 10000)
        daily_pnl = float(portfolio_dict.get("daily_pnl", 0) or 0)
        
        assert open_positions == 0
        assert current_dd == 0.0
        assert equity == 10000.0
        assert daily_pnl == 0.0

    def test_portfolio_with_empty_string(self):
        """Portfolio state with empty string values."""
        portfolio_dict = {
            "open_positions": "",
            "current_drawdown": "",
            "equity": "",
        }
        
        # Type-safe access (empty string → default)
        open_positions = int(portfolio_dict.get("open_positions", 0) or 0)
        current_dd = float(portfolio_dict.get("current_drawdown", 0) or 0)
        equity = float(portfolio_dict.get("equity", 10000) or 10000)
        
        assert open_positions == 0
        assert current_dd == 0.0
        assert equity == 10000.0


class TestParseTradeDecision:
    """parse_trade_decision function testleri."""

    def test_parse_valid_decision(self):
        """Valid trade decision parsing."""
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "amount": 0.1,
            "entry_price": 50000.0,
            "stop_loss": 49000.0,
            "take_profit": 52000.0,
            "confidence": 0.8,
        }
        
        order = parse_trade_decision(decision, current_price=50000.0, atr_value=1000.0)
        
        assert order is not None
        assert order.action == "buy"
        assert order.amount == 0.1

    def test_parse_hold_decision(self):
        """Hold decision returns None."""
        decision = {
            "action": "hold",
            "symbol": "BTC/USDT",
        }
        
        order = parse_trade_decision(decision)
        
        assert order is None

    def test_parse_invalid_amount(self):
        """Invalid amount returns None."""
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "amount": "invalid",
        }
        
        order = parse_trade_decision(decision)
        
        assert order is None

    def test_parse_with_fallback_stop_loss(self):
        """Fallback stop-loss calculation when missing."""
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "amount": 0.1,
            "stop_loss": 0.0,  # Missing SL
        }
        
        order = parse_trade_decision(
            decision,
            current_price=50000.0,
            atr_value=1000.0,
        )
        
        assert order is not None
        assert order.stop_loss > 0  # Fallback calculated


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
