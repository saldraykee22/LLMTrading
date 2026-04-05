"""Unit tests for Stop-Loss, Order Manager, Circuit Breaker, and JSON Utils."""

import pytest

from risk.stop_loss import DynamicStopLoss
from execution.order_manager import TradeOrder, parse_trade_decision
from risk.circuit_breaker import CircuitBreaker
from utils.json_utils import extract_json


class TestDynamicStopLoss:
    def test_calculate_initial_stop_long(self):
        sl = DynamicStopLoss()
        stop = sl.calculate_initial_stop(100.0, 5.0, multiplier=2.0)
        assert stop == 90.0

    def test_trailing_stop_only_moves_favorable(self):
        sl = DynamicStopLoss()
        current_stop = 90.0
        new_stop = sl.update_trailing_stop(current_stop, 105.0, 5.0, multiplier=2.0)
        assert new_stop >= current_stop

    def test_should_exit_long(self):
        sl = DynamicStopLoss()
        assert sl.should_exit(89.0, 90.0) is True
        assert sl.should_exit(91.0, 90.0) is False


class TestTradeOrder:
    def test_valid_order(self):
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            stop_loss=48000,
            take_profit=55000,
        )
        valid, msg = order.validate()
        assert valid is True

    def test_invalid_action(self):
        order = TradeOrder(
            symbol="BTC/USDT",
            action="invalid",
            order_type="market",
            amount=0.1,
            stop_loss=48000,
        )
        valid, msg = order.validate()
        assert valid is False

    def test_zero_amount(self):
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0,
            stop_loss=48000,
        )
        valid, _ = order.validate()
        assert valid is False

    def test_no_stop_loss(self):
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            order_type="market",
            amount=0.1,
            stop_loss=0,
        )
        valid, _ = order.validate()
        assert valid is False


class TestParseTradeDecision:
    def test_hold_returns_none(self):
        result = parse_trade_decision({"action": "hold"})
        assert result is None

    def test_valid_buy_decision(self):
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "order_type": "market",
            "amount": 0.1,
            "stop_loss": 48000,
            "take_profit": 55000,
            "confidence": 0.8,
        }
        order = parse_trade_decision(decision)
        assert order is not None
        assert order.action == "buy"
        assert order.amount == 0.1

    def test_fallback_stop_loss(self):
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "order_type": "market",
            "amount": 0.1,
            "stop_loss": 0,
            "take_profit": 55000,
        }
        order = parse_trade_decision(decision, current_price=50000, atr_value=1000)
        assert order is not None
        assert order.stop_loss > 0

    def test_invalid_amount_returns_none(self):
        decision = {
            "action": "buy",
            "symbol": "BTC/USDT",
            "order_type": "market",
            "amount": "invalid",
            "stop_loss": 48000,
        }
        order = parse_trade_decision(decision)
        assert order is None


class TestCircuitBreaker:
    def test_initial_state_not_halted(self):
        cb = CircuitBreaker()
        halted, _ = cb.should_halt(equity=10000, daily_pnl=0)
        assert halted is False

    def test_consecutive_losses_trigger_halt(self, monkeypatch):
        from config.settings import get_trading_params

        params = get_trading_params()
        orig = params.risk.max_consecutive_losses
        params.risk.max_consecutive_losses = 3
        try:
            cb = CircuitBreaker()
            cb.record_trade_result(-100)
            cb.record_trade_result(-100)
            halted, _ = cb.should_halt(equity=10000, daily_pnl=0)
            assert halted is False
            cb.record_trade_result(-100)
            halted, reason = cb.should_halt(equity=10000, daily_pnl=0)
            assert halted is True
            assert "kay" in reason.lower() or "loss" in reason.lower()
        finally:
            params.risk.max_consecutive_losses = orig

    def test_profit_resets_consecutive_losses(self):
        cb = CircuitBreaker()
        cb.record_trade_result(-100)
        cb.record_trade_result(-100)
        cb.record_trade_result(50)
        assert cb.consecutive_losses == 0

    def test_llm_error_tracking(self, monkeypatch):
        from config.settings import get_trading_params

        params = get_trading_params()
        orig = params.risk.max_consecutive_llm_errors
        params.risk.max_consecutive_llm_errors = 2
        try:
            cb = CircuitBreaker()
            cb.record_llm_error()
            cb.record_llm_error()
            halted, _ = cb.should_halt(equity=10000, daily_pnl=0)
            assert halted is True
        finally:
            params.risk.max_consecutive_llm_errors = orig

    def test_reset_llm_errors(self):
        cb = CircuitBreaker()
        cb.record_llm_error()
        cb.record_llm_error()
        cb.reset_llm_errors()
        assert cb.consecutive_llm_errors == 0


class TestExtractJson:
    def test_code_block_json(self):
        text = '```json\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_plain_json(self):
        text = '{"a": 1, "b": 2}'
        result = extract_json(text)
        assert result == {"a": 1, "b": 2}

    def test_json_in_text(self):
        text = 'Here is the result: {"signal": "bullish"} done.'
        result = extract_json(text)
        assert result == {"signal": "bullish"}

    def test_invalid_returns_error_flag(self):
        text = "not json at all"
        result = extract_json(text)
        assert "__parse_error__" in result
        assert result["__parse_error__"] is True
        assert "__raw_text__" in result

    def test_markdown_code_block(self):
        text = '```json\n{"sentiment_score": 0.5, "signal": "bullish"}\n```'
        result = extract_json(text)
        assert result["sentiment_score"] == 0.5
        assert result["signal"] == "bullish"
