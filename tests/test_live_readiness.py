import pytest
from unittest.mock import MagicMock, patch
from risk.portfolio import PortfolioState, Position

@pytest.fixture
def mock_portfolio():
    return PortfolioState(cash=1000.0, positions=[])

@pytest.fixture
def mock_exchange_client():
    client = MagicMock()
    client.get_balance.return_value = {"USDT": 1000.0}
    return client

@patch("risk.portfolio.get_trading_params")
def test_portfolio_sync_with_exchange(mock_params, mock_portfolio, mock_exchange_client):
    """Borsa bakiyesi ile yerel durumun senkronizasyonunu test et."""
    # Trading mode'u 'live' olarak simüle et
    mock_params.return_value.execution.mode.value = "live"
    
    # Başlangıçta 1000 USDT var, borsada 1200 USDT olduğunu simüle et
    mock_exchange_client.get_balance.return_value = {"USDT": 1200.0}
    
    mock_portfolio.sync_with_exchange(mock_exchange_client)
    
    assert mock_portfolio.cash == 1200.0

@patch("risk.portfolio.get_trading_params")
def test_portfolio_sync_removes_missing_positions(mock_params, mock_portfolio, mock_exchange_client):
    """Borsada olmayan pozisyonların yerel state'den silinmesini test et."""
    # Trading mode'u 'live' olarak simüle et
    mock_params.return_value.execution.mode.value = "live"
    
    mock_portfolio.positions.append(
        Position(symbol="BTC/USDT", entry_price=50000, amount=0.1, entry_time="now")
    )
    # Borsada BTC bakiyesi olmadığını simüle et
    mock_exchange_client.get_balance.return_value = {"USDT": 1000.0} # BTC yok
    
    mock_portfolio.sync_with_exchange(mock_exchange_client)
    
    assert len(mock_portfolio.positions) == 0

@patch("httpx.Client")
def test_circuit_breaker_notification(mock_httpx_client, mock_portfolio):
    """Circuit breaker tetiklendiğinde bildirim gönderilmesini test et."""
    mock_post = MagicMock()
    mock_post.status_code = 200
    mock_httpx_client.return_value.__enter__.return_value.post = mock_post
    
    with patch("risk.circuit_breaker.get_settings") as mock_settings:
        mock_settings.return_value.telegram_bot_token = "test_token"
        mock_settings.return_value.telegram_chat_id = "test_chat"
        
        # Yeniden yükle (import fix sonrası)
        import risk.circuit_breaker
        cb = risk.circuit_breaker.CircuitBreaker()
        # Kayıp limiti aşımını simüle et
        cb.consecutive_losses = 10 
        
        # should_halt çağrıldığında bildirim gitmeli
        cb.should_halt(equity=1000, daily_pnl=-500)
        
        assert mock_post.called
        # URL'i kontrol et
        args, kwargs = mock_post.call_args
        assert "test_token" in args[0]
        assert kwargs["json"]["chat_id"] == "test_chat"

def test_emergency_halt_via_stop_file(tmp_path):
    """data/STOP dosyası varken emirlerin reddedildiğini test et."""
    from execution.exchange_client import ExchangeClient
    from execution.order_manager import TradeOrder
    from risk.system_status import SystemStatus
    
    SystemStatus.reset_instance()
    system_status = SystemStatus.get_instance()
    stop_file = system_status._stop_file
    
    # Gerçek STOP dosyası oluştur
    stop_file.touch()
    try:
        # SystemStatus'un STOP dosyasını fark etmesini sağla
        system_status._check_stop_file()
        
        client = ExchangeClient()
        order = TradeOrder(symbol="BTC/USDT", action="buy", amount=0.1, order_type="market")
        
        result = client.execute_order(order, current_price=50000)
        
        assert result["status"] == "rejected"
        assert "STOP file" in result["message"] or "System halted" in result["message"]
    finally:
        if stop_file.exists():
            stop_file.unlink()
        SystemStatus.reset_instance()
