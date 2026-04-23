"""
Tests for execution/exchange_client.py
"""
import time
from unittest.mock import MagicMock, Mock, ANY, patch

import ccxt
import pytest

from config.settings import TradingMode
from execution.exchange_client import ExchangeClient
from execution.order_manager import TradeOrder


class TestExchangeClient:
    """Test ExchangeClient functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        settings = Mock()
        settings.binance_api_key = "test_key"
        settings.binance_api_secret = "test_secret"
        settings.binance_testnet = True
        settings.confirm_live_trade = True
        return settings

    @pytest.fixture
    def mock_params(self):
        """Mock trading parameters for testing."""
        params = Mock()
        params.execution.mode = TradingMode.PAPER
        params.execution.exchange = "binance"
        params.execution.rate_limit_ms = 100
        params.execution.retry_count = 3
        params.execution.retry_delay_ms = 1000
        params.backtest.initial_cash = 10000.0
        return params

    @pytest.fixture
    def client(self, mock_settings, mock_params):
        """Create ExchangeClient with mocked dependencies."""
        from risk.system_status import SystemStatus
        from config.settings import DATA_DIR
        
        stop_file = DATA_DIR / "STOP"
        if stop_file.exists():
            try:
                stop_file.unlink()
            except OSError:
                pass
                
        SystemStatus.reset_instance()
        with patch('execution.exchange_client.get_settings', return_value=mock_settings), \
             patch('execution.exchange_client.get_trading_params', return_value=mock_params):
            client = ExchangeClient()
            from risk.portfolio import PortfolioState
            client.set_portfolio(PortfolioState())
            yield client
            SystemStatus.reset_instance()
            if stop_file.exists():
                try:
                    stop_file.unlink()
                except OSError:
                    pass

    def test_init(self, client):
        """Test client initialization."""
        assert client._exchange is None
        assert client._paper_engine is None
        assert client._portfolio_ref is not None
        assert client._last_request_time == 0
        assert client._connection_timeout == 300
        assert client._system_status.is_running()

    def test_set_portfolio(self, client):
        """Test setting portfolio reference."""
        portfolio = Mock()
        client.set_portfolio(portfolio)
        assert client._portfolio_ref is portfolio

    def test_check_connection_normal(self, client):
        """Test connection check when within timeout."""
        client._last_successful_call = time.time()
        assert client._check_connection()
        assert client._system_status.is_running()

    def test_check_connection_timeout(self, client):
        """Test connection check when timeout exceeded."""
        client._last_successful_call = time.time() - 400  # Exceed 300s timeout
        with patch.object(client, '_emergency_close_all') as mock_emergency:
            result = client._check_connection()
            assert not result
            assert client._system_status.is_reconnecting()
            mock_emergency.assert_called_once()

    def test_get_paper_engine_lazy_init(self, client):
        """Test lazy initialization of paper engine."""
        engine = client._get_paper_engine()
        assert engine is not None
        assert client._paper_engine is engine

        # Second call should return same instance
        engine2 = client._get_paper_engine()
        assert engine2 is engine

    @patch('ccxt.binance')
    def test_get_exchange_lazy_init_testnet(self, mock_exchange_class, client, mock_settings):
        """Test lazy initialization of exchange in testnet mode."""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange

        exchange = client._get_exchange()

        assert exchange is mock_exchange
        assert client._exchange is mock_exchange
        mock_exchange_class.assert_called_once_with({
            'apiKey': 'test_key',
            'secret': 'test_secret',
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
            'maxConcurrentRequests': 5,
            'sandbox': True,
        })

    @patch('ccxt.binance')
    def test_get_exchange_lazy_init_mainnet(self, mock_exchange_class, client, mock_settings):
        """Test lazy initialization of exchange in mainnet mode."""
        mock_settings.binance_testnet = False
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange

        exchange = client._get_exchange()

        call_args = mock_exchange_class.call_args[0][0]
        assert 'sandbox' not in call_args

    def test_rate_limit(self, client):
        """Test rate limiting."""
        client._last_request_time = 0
        client._rate_limit()
        assert client._last_request_time > 0

    @patch('time.sleep')
    def test_rate_limit_with_delay(self, mock_sleep, client):
        """Test rate limiting with required delay."""
        client._last_request_time = time.time()
        client._rate_limit()
        mock_sleep.assert_called_once()

    def test_execute_order_paper_mode(self, client):
        """Test order execution in paper mode."""
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=0.001,
            order_type="market"
        )

        client.set_portfolio(None)

        with patch.object(client, '_get_paper_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_engine.execute_order.return_value = {"status": "filled"}
            mock_get_engine.return_value = mock_engine

            result = client.execute_order(order, current_price=50000.0)

            assert result["status"] == "filled"
            mock_engine.execute_order.assert_called_once_with(order, 50000.0)

    def test_execute_order_live_rejected_without_confirmation(self, client, mock_params):
        """Test live order rejection without confirmation."""
        mock_params.execution.mode = TradingMode.LIVE
        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=0.001,
            order_type="market"
        )

        client._settings.confirm_live_trade = False
        result = client.execute_order(order)

        assert result["status"] == "rejected"
        assert "confirmation not enabled" in result["message"]

    @patch('ccxt.binance')
    def test_execute_order_live_market(self, mock_exchange_class, client, mock_params):
        """Test live market order execution."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.amount_to_precision.return_value = 0.001
        mock_exchange.create_order.return_value = {
            "id": "12345",
            "status": "closed",
            "symbol": "BTC/USDT",
            "side": "buy",
            "type": "market",
            "amount": 0.001,
            "price": 50000.0,
            "cost": 50.0,
            "fee": {},
            "datetime": "2024-01-01T00:00:00Z"
        }
        mock_exchange_class.return_value = mock_exchange

        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=0.001,
            order_type="market"
        )

        result = client.execute_order(order)

        assert result["status"] == "filled"
        assert result["order_id"] == "12345"
        mock_exchange.create_order.assert_called_once_with(
            symbol="BTC/USDT",
            type="market",
            side="buy",
            amount=0.001,
            params=ANY
        )

    @patch('ccxt.binance')
    def test_execute_order_live_limit(self, mock_exchange_class, client, mock_params):
        """Test live limit order execution."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.amount_to_precision.return_value = 0.001
        mock_exchange.price_to_precision.return_value = 51000.0
        mock_exchange.create_order.return_value = {
            "id": "12346",
            "status": "open",
            "symbol": "BTC/USDT",
            "side": "sell",
            "type": "limit",
            "amount": 0.001,
            "price": 51000.0,
        }
        mock_exchange_class.return_value = mock_exchange

        order = TradeOrder(
            symbol="BTC/USDT",
            action="sell",
            amount=0.001,
            order_type="limit",
            price=51000.0
        )

        result = client.execute_order(order)

        assert result["status"] == "open"
        assert result["order_id"] == "12346"
        mock_exchange.create_order.assert_called_once_with(
            symbol="BTC/USDT",
            type="limit",
            side="sell",
            amount=0.001,
            price=51000.0,
            params=ANY
        )

    @patch('ccxt.binance')
    def test_execute_order_unknown_type(self, mock_exchange_class, client, mock_params):
        """Test order execution with unknown order type."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange_class.return_value = Mock()

        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=0.001,
            order_type="unknown"
        )

        result = client.execute_order(order)

        assert result["status"] == "error"
        assert "Unknown order type" in result["message"]

    @patch('ccxt.binance')
    def test_execute_order_insufficient_funds(self, mock_exchange_class, client, mock_params):
        """Test order execution with insufficient funds error."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.create_order.side_effect = ccxt.InsufficientFunds("Not enough balance")
        mock_exchange_class.return_value = mock_exchange

        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=1000,
            order_type="market"
        )

        result = client.execute_order(order)

        assert result["status"] == "error"
        assert "Insufficient funds" in result["message"]

    @patch('ccxt.binance')
    def test_execute_order_invalid_order(self, mock_exchange_class, client, mock_params):
        """Test order execution with invalid order error."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.create_order.side_effect = ccxt.InvalidOrder("Invalid amount")
        mock_exchange_class.return_value = mock_exchange

        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=0,
            order_type="market"
        )

        result = client.execute_order(order)

        assert result["status"] == "error"
        assert "Invalid order" in result["message"]

    @patch('ccxt.binance')
    @patch('time.sleep')
    def test_execute_order_network_error_retry(self, mock_sleep, mock_exchange_class, client, mock_params):
        """Test order execution with network error and retry."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.create_order.side_effect = [
            ccxt.NetworkError("Connection failed"),
            ccxt.NetworkError("Connection failed"),
            {
                "id": "12347",
                "status": "closed",
                "symbol": "BTC/USDT",
                "side": "buy",
                "type": "market",
                "amount": 0.001,
                "price": 50000.0,
            }
        ]
        mock_exchange_class.return_value = mock_exchange

        order = TradeOrder(
            symbol="BTC/USDT",
            action="buy",
            amount=0.001,
            order_type="market"
        )

        result = client.execute_order(order)

        assert result["status"] == "filled"
        assert mock_exchange.create_order.call_count == 3
        assert mock_sleep.call_count == 2

    def test_get_paper_status_paper_mode(self, client, mock_params):
        """Test getting paper status in paper mode."""
        with patch.object(client, '_get_paper_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_engine.get_status.return_value = {"cash": 9500.0}
            mock_get_engine.return_value = mock_engine

            result = client.get_paper_status()

            assert result["cash"] == 9500.0
            mock_engine.get_status.assert_called_once()

    def test_get_paper_status_live_mode(self, client, mock_params):
        """Test getting paper status in live mode."""
        mock_params.execution.mode = TradingMode.LIVE

        result = client.get_paper_status()

        assert result["error"] == "Not in paper trading mode"

    @patch('ccxt.binance')
    def test_cancel_order_success(self, mock_exchange_class, client, mock_params):
        """Test successful order cancellation."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.cancel_order.return_value = {"id": "12345", "status": "cancelled"}
        mock_exchange_class.return_value = mock_exchange

        result = client.cancel_order("12345", "BTC/USDT")

        assert result["status"] == "cancelled"
        assert result["order_id"] == "12345"
        mock_exchange.cancel_order.assert_called_once_with("12345", "BTC/USDT")

    @patch('ccxt.binance')
    def test_cancel_order_error(self, mock_exchange_class, client, mock_params):
        """Test order cancellation with error."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.cancel_order.side_effect = ccxt.BaseError("Order not found")
        mock_exchange_class.return_value = mock_exchange

        result = client.cancel_order("12345", "BTC/USDT")

        assert result["status"] == "error"
        assert "Order not found" in result["message"]

    @patch('ccxt.binance')
    def test_get_open_orders_success(self, mock_exchange_class, client, mock_params):
        """Test getting open orders successfully."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.fetch_open_orders.return_value = [
            {
                "id": "12345",
                "symbol": "BTC/USDT",
                "side": "buy",
                "amount": 0.001,
                "price": 50000.0,
                "status": "open",
            }
        ]
        mock_exchange_class.return_value = mock_exchange

        result = client.get_open_orders("BTC/USDT")

        assert len(result) == 1
        assert result[0]["id"] == "12345"
        assert result[0]["status"] == "open"
        mock_exchange.fetch_open_orders.assert_called_once_with("BTC/USDT")

    @patch('ccxt.binance')
    def test_get_open_orders_error(self, mock_exchange_class, client, mock_params):
        """Test getting open orders with error."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.fetch_open_orders.side_effect = ccxt.BaseError("API error")
        mock_exchange_class.return_value = mock_exchange

        result = client.get_open_orders()

        assert len(result) == 1
        assert "API error" in result[0]["error"]

    @patch('ccxt.binance')
    def test_get_balance_success(self, mock_exchange_class, client, mock_params):
        """Test getting balance successfully."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.fetch_balance.return_value = {
            "total": {
                "BTC": "0.5",
                "USDT": "1000.0",
                "ETH": "0",
            }
        }
        mock_exchange_class.return_value = mock_exchange

        result = client.get_balance()

        assert result["BTC"] == 0.5
        assert result["USDT"] == 1000.0
        assert "ETH" not in result  # Zero balance excluded
        mock_exchange.fetch_balance.assert_called_once()

    @patch('ccxt.binance')
    def test_get_balance_error(self, mock_exchange_class, client, mock_params):
        """Test getting balance with error."""
        mock_params.execution.mode = TradingMode.LIVE
        mock_exchange = Mock()
        mock_exchange.fetch_balance.side_effect = ccxt.BaseError("error")
        mock_exchange_class.return_value = mock_exchange

        result = client.get_balance()

        assert result["error"] == "error"
