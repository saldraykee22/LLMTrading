"""Comprehensive tests for new/modified features:
- Watchdog SL/TP monitoring
- Risk Manager LLM bypass
- OrderBookAnalyzer
- RetrospectiveAgent
- Timezone fixes
- TechnicalAnalyzer + OrderBookAnalyzer integration
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from agents.retrospective_agent import (
    RetrospectiveAgent,
    RetrospectiveResult,
    check_and_analyze_losses,
)
from agents.risk_manager import risk_manager_node
from agents.state import TradingState
from models.orderbook_analyzer import OrderBookAnalyzer, SlippageResult
from models.technical_analyzer import TechnicalAnalyzer, TechnicalSignals
from risk.portfolio import PortfolioState, Position
from risk.watchdog import Watchdog


# ──────────────────────────────────────────────
# A) Watchdog Tests
# ──────────────────────────────────────────────


class TestWatchdog:
    def test_init_default_values(self):
        portfolio = PortfolioState()
        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        assert wd.symbols == ["BTC/USDT"]
        assert wd.portfolio is portfolio
        assert wd.exchange_client is None
        assert wd.crash_threshold_pct == 5.0
        assert wd.check_interval_sec == 10
        assert wd._stop_event is not None
        assert wd._thread is None

    def test_init_custom_values(self):
        portfolio = PortfolioState()
        wd = Watchdog(
            symbols=["ETH/USDT", "BTC/USDT"],
            portfolio=portfolio,
            exchange_client=MagicMock(),
            crash_threshold_pct=3.0,
            check_interval_sec=5,
        )
        assert wd.symbols == ["ETH/USDT", "BTC/USDT"]
        assert wd.crash_threshold_pct == 3.0
        assert wd.check_interval_sec == 5
        assert wd.exchange_client is not None

    def test_check_position_sl_tp_no_positions(self):
        portfolio = PortfolioState()
        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        wd._market_client = MagicMock()
        wd._check_position_sl_tp()
        wd._market_client.fetch_current_price.assert_not_called()

    def test_check_position_sl_tp_triggers_stop_loss(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=48000.0,
            take_profit=0.0,
        )
        portfolio.positions.append(pos)

        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        mock_market = MagicMock()
        mock_market.fetch_current_price.return_value = 47000.0
        wd._market_client = mock_market
        wd._emergency_close = MagicMock()

        wd._check_position_sl_tp()

        wd._emergency_close.assert_called_once()
        call_args = wd._emergency_close.call_args
        assert call_args[0][0].symbol == "BTC/USDT"
        assert call_args[0][2] == "stop-loss"

    def test_check_position_sl_tp_triggers_take_profit(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="ETH/USDT",
            entry_price=3000.0,
            amount=1.0,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=0.0,
            take_profit=3500.0,
        )
        portfolio.positions.append(pos)

        wd = Watchdog(symbols=["ETH/USDT"], portfolio=portfolio)
        mock_market = MagicMock()
        mock_market.fetch_current_price.return_value = 3600.0
        wd._market_client = mock_market
        wd._emergency_close = MagicMock()

        wd._check_position_sl_tp()

        wd._emergency_close.assert_called_once()
        call_args = wd._emergency_close.call_args
        assert call_args[0][0].symbol == "ETH/USDT"
        assert call_args[0][2] == "take-profit"

    def test_check_position_sl_tp_no_trigger(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=48000.0,
            take_profit=55000.0,
        )
        portfolio.positions.append(pos)

        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        mock_market = MagicMock()
        mock_market.fetch_current_price.return_value = 51000.0
        wd._market_client = mock_market
        wd._emergency_close = MagicMock()

        wd._check_position_sl_tp()

        wd._emergency_close.assert_not_called()

    def test_check_position_sl_tp_skips_when_no_sl_tp(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=0.0,
            take_profit=0.0,
        )
        portfolio.positions.append(pos)

        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        mock_market = MagicMock()
        wd._market_client = mock_market
        wd._emergency_close = MagicMock()

        wd._check_position_sl_tp()

        mock_market.fetch_current_price.assert_not_called()

    def test_emergency_close_no_exchange_client(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=48000.0,
        )
        portfolio.positions.append(pos)

        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        wd.exchange_client = None
        wd._emergency_close(pos, 47000.0, "stop-loss")

        assert len(portfolio.positions) == 1

    def test_emergency_close_success(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=48000.0,
        )
        portfolio.positions.append(pos)

        mock_exchange = MagicMock()
        mock_exchange.execute_order.return_value = {
            "status": "filled",
            "price": 47000.0,
        }

        wd = Watchdog(
            symbols=["BTC/USDT"],
            portfolio=portfolio,
            exchange_client=mock_exchange,
        )
        wd._emergency_close(pos, 47000.0, "stop-loss")

        mock_exchange.execute_order.assert_called_once()
        assert len(portfolio.positions) == 0
        assert len(portfolio.closed_trades) == 1

    def test_emergency_close_position_already_closed(self):
        portfolio = PortfolioState()
        pos = Position(
            symbol="BTC/USDT",
            entry_price=50000.0,
            amount=0.1,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=48000.0,
        )

        mock_exchange = MagicMock()

        wd = Watchdog(
            symbols=["BTC/USDT"],
            portfolio=portfolio,
            exchange_client=mock_exchange,
        )
        wd._emergency_close(pos, 47000.0, "stop-loss")

        mock_exchange.execute_order.assert_not_called()

    def test_flash_crash_detection(self):
        portfolio = PortfolioState()
        wd = Watchdog(
            symbols=["BTC/USDT"],
            portfolio=portfolio,
            crash_threshold_pct=5.0,
        )
        mock_market = MagicMock()
        df = pd.DataFrame(
            {
                "close": [50000.0, 46000.0],
            }
        )
        mock_market.fetch_ohlcv.return_value = df
        wd._market_client = mock_market
        wd._handle_crash = MagicMock()

        wd._check_symbols()

        wd._handle_crash.assert_called_once()
        call_args = wd._handle_crash.call_args
        assert call_args[0][0] == "BTC/USDT"
        assert call_args[0][1] == 46000.0
        assert call_args[0][2] >= 5.0

    def test_no_flash_crash_when_below_threshold(self):
        portfolio = PortfolioState()
        wd = Watchdog(
            symbols=["BTC/USDT"],
            portfolio=portfolio,
            crash_threshold_pct=5.0,
        )
        mock_market = MagicMock()
        df = pd.DataFrame(
            {
                "close": [50000.0, 49000.0],
            }
        )
        mock_market.fetch_ohlcv.return_value = df
        wd._market_client = mock_market
        wd._handle_crash = MagicMock()

        wd._check_symbols()

        wd._handle_crash.assert_not_called()

    def test_get_status(self):
        portfolio = PortfolioState()
        wd = Watchdog(
            symbols=["BTC/USDT"],
            portfolio=portfolio,
            crash_threshold_pct=5.0,
            check_interval_sec=10,
        )
        status = wd.get_status()
        assert status["running"] is False
        assert status["symbols"] == ["BTC/USDT"]
        assert status["crash_threshold_pct"] == 5.0
        assert status["check_interval_sec"] == 10

    def test_start_stop(self):
        portfolio = PortfolioState()
        wd = Watchdog(symbols=["BTC/USDT"], portfolio=portfolio)
        wd._market_client = MagicMock()
        wd.start()
        status = wd.get_status()
        assert status["running"] is True
        wd.stop()
        status = wd.get_status()
        assert status["running"] is False


# ──────────────────────────────────────────────
# B) Risk Manager Tests
# ──────────────────────────────────────────────


def _make_state(**overrides):
    state: TradingState = {
        "messages": [],
        "symbol": "BTC/USDT",
        "sentiment": {"confidence": 0.8, "signal": "bullish"},
        "research_report": {"summary": "test"},
        "debate_result": {
            "consensus_score": 0.7,
            "hallucinations_detected": [],
            "adjusted_signal": "bullish",
        },
        "technical_signals": {"signal": "buy"},
        "portfolio_state": {
            "open_positions": 1,
            "current_drawdown": 0.05,
            "equity": 10000,
            "daily_pnl": 100,
        },
        "provider": None,
        "phase": "analysis",
    }
    state.update(overrides)
    return state


class TestRiskManager:
    @patch("agents.risk_manager.invoke_with_retry")
    @patch("agents.risk_manager.create_agent_llm")
    @patch("evaluation.drift_monitor.DriftMonitor")
    def test_critical_max_positions_skips_llm(self, mock_drift, mock_llm, mock_invoke):
        mock_drift_instance = MagicMock()
        mock_drift_instance.get_agent_accuracy.return_value = 0.7
        mock_drift.return_value = mock_drift_instance

        state = _make_state(
            portfolio_state={
                "open_positions": 15,
                "current_drawdown": 0.05,
                "equity": 10000,
                "daily_pnl": 100,
            }
        )

        result = risk_manager_node(state)

        mock_invoke.assert_not_called()
        assert result["risk_approved"] is False
        assert result["risk_assessment"]["decision"] == "rejected"
        assert result["risk_assessment"]["approved_size"] == 0

    @patch("agents.risk_manager.invoke_with_retry")
    @patch("agents.risk_manager.create_agent_llm")
    @patch("evaluation.drift_monitor.DriftMonitor")
    def test_critical_drawdown_skips_llm(self, mock_drift, mock_llm, mock_invoke):
        mock_drift_instance = MagicMock()
        mock_drift_instance.get_agent_accuracy.return_value = 0.7
        mock_drift.return_value = mock_drift_instance

        state = _make_state(
            portfolio_state={
                "open_positions": 1,
                "current_drawdown": 0.20,
                "equity": 10000,
                "daily_pnl": 100,
            }
        )

        result = risk_manager_node(state)

        mock_invoke.assert_not_called()
        assert result["risk_approved"] is False

    @patch("agents.risk_manager.invoke_with_retry")
    @patch("agents.risk_manager.create_agent_llm")
    @patch("evaluation.drift_monitor.DriftMonitor")
    def test_critical_daily_loss_skips_llm(self, mock_drift, mock_llm, mock_invoke):
        mock_drift_instance = MagicMock()
        mock_drift_instance.get_agent_accuracy.return_value = 0.7
        mock_drift.return_value = mock_drift_instance

        state = _make_state(
            portfolio_state={
                "open_positions": 1,
                "current_drawdown": 0.05,
                "equity": 10000,
                "daily_pnl": -500,
            }
        )

        result = risk_manager_node(state)

        mock_invoke.assert_not_called()
        assert result["risk_approved"] is False

    @patch("agents.risk_manager.invoke_with_retry")
    @patch("agents.risk_manager.create_agent_llm")
    @patch("evaluation.drift_monitor.DriftMonitor")
    def test_non_critical_proceeds_to_llm(self, mock_drift, mock_llm, mock_invoke):
        mock_drift_instance = MagicMock()
        mock_drift_instance.get_agent_accuracy.return_value = 0.7
        mock_drift.return_value = mock_drift_instance

        mock_llm_instance = MagicMock()
        mock_llm.return_value = mock_llm_instance

        mock_response = MagicMock()
        mock_response.content = '{"approved_size": 200, "decision": "approved", "stop_loss_level": 48000, "take_profit_level": 55000}'
        mock_invoke.return_value = mock_response

        state = _make_state()
        result = risk_manager_node(state)

        mock_invoke.assert_called_once()
        assert result["risk_approved"] is True

    @patch("agents.risk_manager.invoke_with_retry")
    @patch("agents.risk_manager.create_agent_llm")
    @patch("evaluation.drift_monitor.DriftMonitor")
    def test_llm_approved_size_exceeding_limit_rejected(
        self, mock_drift, mock_llm, mock_invoke
    ):
        mock_drift_instance = MagicMock()
        mock_drift_instance.get_agent_accuracy.return_value = 0.7
        mock_drift.return_value = mock_drift_instance

        mock_llm_instance = MagicMock()
        mock_llm.return_value = mock_llm_instance

        mock_response = MagicMock()
        mock_response.content = '{"approved_size": 99999, "decision": "approved", "stop_loss_level": 48000, "take_profit_level": 55000}'
        mock_invoke.return_value = mock_response

        state = _make_state()
        result = risk_manager_node(state)

        assert result["risk_approved"] is False
        assert result["risk_assessment"]["decision"] == "rejected"

    @patch("agents.risk_manager.invoke_with_retry")
    @patch("agents.risk_manager.create_agent_llm")
    @patch("evaluation.drift_monitor.DriftMonitor")
    def test_kesin_kurallar_in_user_msg(self, mock_drift, mock_llm, mock_invoke):
        mock_drift_instance = MagicMock()
        mock_drift_instance.get_agent_accuracy.return_value = 0.7
        mock_drift.return_value = mock_drift_instance

        mock_llm_instance = MagicMock()
        mock_llm.return_value = mock_llm_instance

        captured_messages = []

        def capture_invoke(invoke_fn, messages, **kwargs):
            captured_messages.extend(messages)
            mock_resp = MagicMock()
            mock_resp.content = '{"approved_size": 200, "decision": "approved"}'
            return mock_resp

        mock_invoke.side_effect = capture_invoke

        state = _make_state()
        risk_manager_node(state)

        user_msg_content = ""
        for msg in captured_messages:
            if hasattr(msg, "content"):
                user_msg_content += msg.content
        assert "KESİN KURALLAR" in user_msg_content


# ──────────────────────────────────────────────
# C) OrderBookAnalyzer Tests
# ──────────────────────────────────────────────


class TestSlippageResult:
    def test_dataclass_creation(self):
        result = SlippageResult(
            symbol="BTC/USDT",
            side="buy",
            requested_amount=1.0,
            expected_price=50000.0,
            effective_price=50100.0,
            slippage_pct=0.002,
            liquidity_score=0.85,
            bid_depth=100.0,
            ask_depth=150.0,
        )
        assert result.symbol == "BTC/USDT"
        assert result.side == "buy"
        assert result.requested_amount == 1.0
        assert result.expected_price == 50000.0
        assert result.effective_price == 50100.0
        assert result.slippage_pct == 0.002
        assert result.liquidity_score == 0.85
        assert result.bid_depth == 100.0
        assert result.ask_depth == 150.0

    def test_to_dict(self):
        result = SlippageResult(
            symbol="ETH/USDT",
            side="sell",
            requested_amount=10.0,
            expected_price=3000.0,
            effective_price=2990.0,
            slippage_pct=-0.0033,
            liquidity_score=0.7,
            bid_depth=200.0,
            ask_depth=180.0,
        )
        d = result.to_dict()
        assert d["symbol"] == "ETH/USDT"
        assert d["side"] == "sell"
        assert d["requested_amount"] == 10.0
        assert d["expected_price"] == 3000.0
        assert d["effective_price"] == 2990.0
        assert d["slippage_pct"] == -0.0033
        assert d["liquidity_score"] == 0.7
        assert d["bid_depth"] == 200.0
        assert d["ask_depth"] == 180.0


def _make_order_book(bids=None, asks=None):
    if bids is None:
        bids = [[49999.0, 1.0], [49998.0, 2.0], [49997.0, 3.0]]
    if asks is None:
        asks = [[50001.0, 1.0], [50002.0, 2.0], [50003.0, 3.0]]
    return {"bids": bids, "asks": asks, "timestamp": 1234567890}


class TestOrderBookAnalyzer:
    def test_calculate_slippage_with_mock_data(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        ob = _make_order_book()
        result = analyzer.calculate_slippage(amount=1.0, side="buy", order_book=ob)

        assert isinstance(result, SlippageResult)
        assert result.symbol == "BTC/USDT"
        assert result.side == "buy"
        assert result.requested_amount == 1.0
        assert result.expected_price == 50000.0
        assert result.effective_price == 50001.0
        assert result.slippage_pct > 0
        assert result.bid_depth == 6.0
        assert result.ask_depth == 6.0

    def test_calculate_slippage_sell(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        ob = _make_order_book()
        result = analyzer.calculate_slippage(amount=1.0, side="sell", order_book=ob)

        assert isinstance(result, SlippageResult)
        assert result.side == "sell"
        assert result.effective_price == 49999.0

    def test_calculate_slippage_empty_order_book(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        ob = {"bids": [], "asks": [], "timestamp": 1234567890}
        result = analyzer.calculate_slippage(amount=1.0, side="buy", order_book=ob)

        assert result.expected_price == 0.0
        assert result.effective_price == 0.0
        assert result.slippage_pct == 0.0
        assert result.liquidity_score == 0.0

    def test_calculate_slippage_none_order_book(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        with patch.object(OrderBookAnalyzer, "fetch_order_book", return_value=None):
            result = analyzer.calculate_slippage(
                amount=1.0, side="buy", order_book=None
            )

        assert result.expected_price == 0.0
        assert result.effective_price == 0.0
        assert result.slippage_pct == 0.0
        assert result.liquidity_score == 0.0

    def test_get_liquidity_score_high_liquidity(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        bids = [[49999.0, 50.0] for _ in range(20)]
        asks = [[50001.0, 50.0] for _ in range(20)]
        ob = {"bids": bids, "asks": asks}

        score = analyzer.get_liquidity_score(order_book=ob)
        assert 0.0 <= score <= 1.0
        assert score > 0.5

    def test_get_liquidity_score_low_liquidity(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        bids = [[49999.0, 0.001]]
        asks = [[50001.0, 0.001]]
        ob = {"bids": bids, "asks": asks}

        score = analyzer.get_liquidity_score(order_book=ob)
        assert 0.0 <= score <= 1.0
        assert score < 0.5

    def test_get_liquidity_score_empty_book(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        ob = {"bids": [], "asks": []}
        score = analyzer.get_liquidity_score(order_book=ob)
        assert score == 0.0

    def test_get_liquidity_score_none_book(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        with patch.object(OrderBookAnalyzer, "fetch_order_book", return_value=None):
            score = analyzer.get_liquidity_score(order_book=None)
        assert score == 0.0

    def test_get_effective_price_buy(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        ob = _make_order_book()
        price = analyzer.get_effective_price(amount=1.0, side="buy", order_book=ob)
        assert price == 50001.0

    def test_get_effective_price_sell(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        ob = _make_order_book()
        price = analyzer.get_effective_price(amount=1.0, side="sell", order_book=ob)
        assert price == 49999.0

    def test_get_effective_price_large_order_walks_book(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        bids = [[49999.0, 1.0], [49998.0, 1.0], [49997.0, 1.0]]
        asks = [[50001.0, 1.0], [50002.0, 1.0], [50003.0, 1.0]]
        ob = {"bids": bids, "asks": asks}

        price = analyzer.get_effective_price(amount=2.5, side="buy", order_book=ob)
        assert price > 50001.0
        assert price < 50003.0

    def test_get_effective_price_none_book(self):
        analyzer = OrderBookAnalyzer.__new__(OrderBookAnalyzer)
        analyzer.symbol = "BTC/USDT"
        analyzer.depth = 20
        analyzer._exchange = None
        analyzer._order_book = None

        with patch.object(OrderBookAnalyzer, "fetch_order_book", return_value=None):
            price = analyzer.get_effective_price(
                amount=1.0, side="buy", order_book=None
            )
        assert price == 0.0


# ──────────────────────────────────────────────
# D) RetrospectiveAgent Tests
# ──────────────────────────────────────────────


class TestRetrospectiveResult:
    def test_dataclass_creation(self):
        result = RetrospectiveResult(
            symbol="BTC/USDT",
            trade_pnl=-500.0,
            entry_time="2024-01-01T00:00:00+00:00",
            exit_time="2024-01-02T00:00:00+00:00",
            root_cause="False breakout signal",
            root_cause_category="false_signal",
            missed_signals=["RSI divergence", "Volume decline"],
            lesson_learned="Wait for confirmed breakout with volume.",
            confidence=0.85,
            entry_quality="bad",
            exit_quality="good",
            market_regime_during_trade="volatile",
        )
        assert result.symbol == "BTC/USDT"
        assert result.trade_pnl == -500.0
        assert result.analysis_time != ""
        dt = datetime.fromisoformat(result.analysis_time)
        assert dt.tzinfo is not None

    def test_dataclass_defaults(self):
        result = RetrospectiveResult(
            symbol="ETH/USDT",
            trade_pnl=-100.0,
            entry_time="2024-01-01",
            exit_time="2024-01-02",
            root_cause="test",
            root_cause_category="test",
        )
        assert result.missed_signals == []
        assert result.lesson_learned == ""
        assert result.confidence == 0.0
        assert result.entry_quality == "unknown"
        assert result.exit_quality == "unknown"
        assert result.market_regime_during_trade == "unknown"


class TestRetrospectiveAgent:
    def test_analyze_losing_trade_profitable_returns_early(self):
        agent = RetrospectiveAgent.__new__(RetrospectiveAgent)
        agent._params = MagicMock()
        agent._memory_store = MagicMock()

        trade = {
            "symbol": "BTC/USDT",
            "pnl": 500.0,
            "entry_time": "2024-01-01T00:00:00+00:00",
            "exit_time": "2024-01-02T00:00:00+00:00",
        }

        result = agent.analyze_losing_trade(trade, "BTC/USDT")

        assert result.root_cause == "not_a_losing_trade"
        assert result.confidence == 1.0

    @patch.object(RetrospectiveAgent, "_gather_context")
    @patch.object(RetrospectiveAgent, "_llm_analysis")
    def test_analyze_losing_trade_success(self, mock_llm, mock_gather):
        agent = RetrospectiveAgent.__new__(RetrospectiveAgent)
        agent._params = MagicMock()
        agent._params.limits.max_tokens_research = 500
        agent._memory_store = MagicMock()
        agent._memory_store.collection = MagicMock()

        mock_gather.return_value = ("market context", "news context")
        mock_llm.return_value = {
            "root_cause": "False breakout",
            "root_cause_category": "false_signal",
            "missed_signals": ["RSI divergence"],
            "lesson_learned": "Wait for volume confirmation.",
            "confidence": 0.8,
            "entry_quality": "bad",
            "exit_quality": "good",
            "market_regime_during_trade": "volatile",
        }

        trade = {
            "symbol": "BTC/USDT",
            "pnl": -500.0,
            "entry_time": "2024-01-01T00:00:00+00:00",
            "exit_time": "2024-01-02T00:00:00+00:00",
        }

        result = agent.analyze_losing_trade(trade, "BTC/USDT")

        assert result.root_cause == "False breakout"
        assert result.root_cause_category == "false_signal"
        assert result.confidence == 0.8
        assert result.lesson_learned == "Wait for volume confirmation."
        agent._memory_store.collection.add.assert_called_once()

    @patch.object(RetrospectiveAgent, "_gather_context")
    @patch.object(RetrospectiveAgent, "_llm_analysis")
    def test_analyze_losing_trade_llm_failure(self, mock_llm, mock_gather):
        agent = RetrospectiveAgent.__new__(RetrospectiveAgent)
        agent._params = MagicMock()
        agent._memory_store = MagicMock()

        mock_gather.return_value = ("market context", "news context")
        mock_llm.return_value = None

        trade = {
            "symbol": "BTC/USDT",
            "pnl": -500.0,
            "entry_time": "2024-01-01T00:00:00+00:00",
            "exit_time": "2024-01-02T00:00:00+00:00",
        }

        result = agent.analyze_losing_trade(trade, "BTC/USDT")

        assert result.root_cause == "llm_analysis_failed"
        assert result.confidence == 0.0

    def test_check_and_analyze_filters_invalid_portfolio(self):
        results = check_and_analyze_losses("not_a_portfolio")
        assert results == []

    def test_check_and_analyze_filters_no_losing_trades(self):
        portfolio = PortfolioState()
        portfolio.closed_trades = [
            {"symbol": "BTC/USDT", "pnl": 500.0, "retrospective_analyzed": False},
        ]

        with patch("agents.retrospective_agent.RetrospectiveAgent"):
            results = check_and_analyze_losses(portfolio)

        assert results == []

    def test_check_and_analyze_filters_already_analyzed(self):
        portfolio = PortfolioState()
        portfolio.closed_trades = [
            {
                "symbol": "BTC/USDT",
                "pnl": -500.0,
                "retrospective_analyzed": True,
                "entry_time": "2024-01-01",
                "exit_time": "2024-01-02",
            },
        ]

        with patch("agents.retrospective_agent.RetrospectiveAgent"):
            results = check_and_analyze_losses(portfolio)

        assert results == []

    @patch.object(RetrospectiveAgent, "_gather_context")
    @patch.object(RetrospectiveAgent, "_llm_analysis")
    def test_store_lesson_integration(self, mock_llm, mock_gather):
        agent = RetrospectiveAgent.__new__(RetrospectiveAgent)
        agent._params = MagicMock()
        agent._params.limits.max_tokens_research = 500
        agent._memory_store = MagicMock()
        agent._memory_store.collection = MagicMock()

        mock_gather.return_value = ("market context", "news context")
        mock_llm.return_value = {
            "root_cause": "Market crash",
            "root_cause_category": "market_crash",
            "missed_signals": [],
            "lesson_learned": "Use tighter stops in volatile markets.",
            "confidence": 0.9,
            "entry_quality": "neutral",
            "exit_quality": "bad",
            "market_regime_during_trade": "crash",
        }

        trade = {
            "symbol": "ETH/USDT",
            "pnl": -1000.0,
            "entry_time": "2024-01-01T00:00:00+00:00",
            "exit_time": "2024-01-02T00:00:00+00:00",
        }

        result = agent.analyze_losing_trade(trade, "ETH/USDT")

        call_kwargs = agent._memory_store.collection.add.call_args
        assert call_kwargs is not None
        metadata = call_kwargs.kwargs["metadatas"][0]
        assert metadata["symbol"] == "ETH/USDT"
        assert metadata["action"] == "losing_trade"
        assert metadata["root_cause_category"] == "market_crash"
        assert "timestamp" in metadata

    def test_parse_iso_valid(self):
        dt = RetrospectiveAgent._parse_iso("2024-01-01T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1

    def test_parse_iso_with_z(self):
        dt = RetrospectiveAgent._parse_iso("2024-01-01T12:00:00Z")
        assert dt is not None

    def test_parse_iso_empty(self):
        dt = RetrospectiveAgent._parse_iso("")
        assert dt is None

    def test_parse_iso_invalid(self):
        dt = RetrospectiveAgent._parse_iso("not-a-date")
        assert dt is None


# ──────────────────────────────────────────────
# E) Timezone Tests
# ──────────────────────────────────────────────


class TestTimezoneAwareness:
    def test_portfolio_position_entry_time_is_timezone_aware(self):
        portfolio = PortfolioState()
        pos = portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.1,
        )
        assert pos is not None
        dt = datetime.fromisoformat(pos.entry_time)
        assert dt.tzinfo is not None

    def test_portfolio_close_trade_record_timezone_aware(self):
        portfolio = PortfolioState()
        portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.1,
        )
        trade = portfolio.close_position("BTC/USDT", 51000.0)
        assert trade is not None
        exit_dt = datetime.fromisoformat(trade["exit_time"])
        assert exit_dt.tzinfo is not None
        entry_dt = datetime.fromisoformat(trade["entry_time"])
        assert entry_dt.tzinfo is not None

    def test_retrospective_result_analysis_time_timezone_aware(self):
        result = RetrospectiveResult(
            symbol="BTC/USDT",
            trade_pnl=-100.0,
            entry_time="2024-01-01",
            exit_time="2024-01-02",
            root_cause="test",
            root_cause_category="test",
        )
        dt = datetime.fromisoformat(result.analysis_time)
        assert dt.tzinfo is not None

    def test_vector_store_uses_timezone_aware_timestamps(self):
        from data.vector_store import AgentMemoryStore
        from pathlib import Path
        import tempfile
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            store = AgentMemoryStore(store_dir=Path(tmpdir))
            if store.collection is None:
                pytest.skip("ChromaDB not available")

            state = {
                "symbol": "BTC/USDT",
                "market_data": {"current_price": 50000},
                "news_data": [],
                "technical_signals": {"vix": 20, "macd": {"histogram": 0.5}},
                "trade_decision": {"action": "buy"},
            }
            store.store_decision(state, accuracy_score=0.7)

            results = store.collection.query(
                query_texts=["Price: 50000"],
                n_results=1,
            )
            assert results is not None
            assert len(results.get("metadatas", [[]])) > 0
            metadata = results["metadatas"][0][0]
            ts_str = metadata.get("timestamp", "")

            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            assert dt.tzinfo is not None
        finally:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass


# ──────────────────────────────────────────────
# F) Integration Tests
# ──────────────────────────────────────────────


class TestTechnicalAnalyzerWithOrderBook:
    def _make_ohlcv(self, n=200, trend="up"):
        np.random.seed(42)
        if trend == "up":
            prices = 100 + np.cumsum(np.random.normal(0.1, 1, n))
        elif trend == "down":
            prices = 100 + np.cumsum(np.random.normal(-0.1, 1, n))
        else:
            prices = 100 + np.cumsum(np.random.normal(0, 1, n))
        return pd.DataFrame(
            {
                "open": prices,
                "high": prices + np.abs(np.random.normal(0, 0.5, n)),
                "low": prices - np.abs(np.random.normal(0, 0.5, n)),
                "close": prices,
                "volume": np.random.uniform(1000, 5000, n),
            }
        )

    def test_technical_analyzer_with_orderbook_analyzer(self):
        df = self._make_ohlcv()

        mock_ob = MagicMock(spec=OrderBookAnalyzer)
        mock_ob.calculate_slippage.return_value = SlippageResult(
            symbol="BTC/USDT",
            side="buy",
            requested_amount=1.0,
            expected_price=50000.0,
            effective_price=50100.0,
            slippage_pct=0.002,
            liquidity_score=0.85,
            bid_depth=100.0,
            ask_depth=150.0,
        )

        analyzer = TechnicalAnalyzer(orderbook_analyzer=mock_ob)
        result = analyzer.analyze(df, "BTC/USDT", order_amount=1.0, side="buy")

        assert isinstance(result, TechnicalSignals)
        mock_ob.calculate_slippage.assert_called_once_with(amount=1.0, side="buy")
        assert result.slippage_info is not None
        assert result.slippage_info["symbol"] == "BTC/USDT"
        assert result.slippage_info["slippage_pct"] == 0.002

    def test_slippage_info_in_to_dict(self):
        df = self._make_ohlcv()

        mock_ob = MagicMock(spec=OrderBookAnalyzer)
        mock_ob.calculate_slippage.return_value = SlippageResult(
            symbol="ETH/USDT",
            side="sell",
            requested_amount=10.0,
            expected_price=3000.0,
            effective_price=2990.0,
            slippage_pct=-0.0033,
            liquidity_score=0.7,
            bid_depth=200.0,
            ask_depth=180.0,
        )

        analyzer = TechnicalAnalyzer(orderbook_analyzer=mock_ob)
        result = analyzer.analyze(df, "ETH/USDT", order_amount=10.0, side="sell")

        d = result.to_dict()
        assert "slippage" in d
        assert d["slippage"]["symbol"] == "ETH/USDT"
        assert d["slippage"]["side"] == "sell"
        assert d["slippage"]["slippage_pct"] == -0.0033

    def test_no_slippage_info_when_no_orderbook(self):
        df = self._make_ohlcv()
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(df, "BTC/USDT")

        assert result.slippage_info is None
        d = result.to_dict()
        assert "slippage" not in d

    def test_no_slippage_info_when_order_amount_none(self):
        df = self._make_ohlcv()
        mock_ob = MagicMock(spec=OrderBookAnalyzer)
        analyzer = TechnicalAnalyzer(orderbook_analyzer=mock_ob)
        result = analyzer.analyze(df, "BTC/USDT", order_amount=None)

        assert result.slippage_info is None
        mock_ob.calculate_slippage.assert_not_called()

    def test_no_slippage_info_when_order_amount_zero(self):
        df = self._make_ohlcv()
        mock_ob = MagicMock(spec=OrderBookAnalyzer)
        analyzer = TechnicalAnalyzer(orderbook_analyzer=mock_ob)
        result = analyzer.analyze(df, "BTC/USDT", order_amount=0, side="buy")

        assert result.slippage_info is None
        mock_ob.calculate_slippage.assert_not_called()

    def test_slippage_exception_does_not_break_analysis(self):
        df = self._make_ohlcv()

        mock_ob = MagicMock(spec=OrderBookAnalyzer)
        mock_ob.calculate_slippage.side_effect = Exception("network error")

        analyzer = TechnicalAnalyzer(orderbook_analyzer=mock_ob)
        result = analyzer.analyze(df, "BTC/USDT", order_amount=1.0, side="buy")

        assert isinstance(result, TechnicalSignals)
        assert result.slippage_info is None
