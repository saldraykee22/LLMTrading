"""
Dust Management Testleri (Faz 4)
==================================
Küçük bakiye temizleme ve Binance API entegrasyonu testleri.
"""

import pytest
from unittest.mock import Mock, patch
from risk.portfolio import PortfolioState
from config.settings import TradingMode


class TestDustDetection:
    """Dust tespiti testleri."""
    
    def test_get_dust_balances(self):
        """$1 altı bakiyeleri dust olarak tespit et."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        # Mock balance data
        balance_data = {
            "USDT": 500.0,      # Dust değil
            "BNB": 0.5,         # Dust değil (BNB korunur)
            "BTC": 0.00001,     # ~$0.50 (dust)
            "ETH": 0.001,       # ~$3 (dust değil)
            "PEPE": 1000000,    # ~$0.10 (dust)
        }
        
        # Mock tickers
        mock_tickers = {
            "BTC/USDT": {'last': 50000.0},
            "ETH/USDT": {'last': 3000.0},
            "PEPE/USDT": {'last': 0.0000001},
        }
        
        with patch('data.market_data.MarketDataClient') as mock_market:
            mock_market.return_value.fetch_tickers.return_value = mock_tickers
            
            dust = portfolio.get_dust_balances(balance_data)
        
        # BTC ve PEPE dust olmalı
        assert "BTC" in dust
        assert "PEPE" in dust
        assert "USDT" not in dust  # USDT korunur
        assert "BNB" not in dust   # BNB korunur
        assert "ETH" not in dust   # $3 > $1
    
    def test_filter_dust_from_balance(self):
        """Bakiyeden dust'ları çıkar."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        balance_data = {
            "USDT": 500.0,
            "BTC": 0.00001,  # Dust
            "ETH": 0.1,      # Dust değil
        }
        
        mock_tickers = {
            "BTC/USDT": {'last': 50000.0},
            "ETH/USDT": {'last': 3000.0},
        }
        
        with patch('data.market_data.MarketDataClient') as mock_market:
            mock_market.return_value.fetch_tickers.return_value = mock_tickers
            
            filtered = portfolio.filter_dust_from_balance(balance_data)
        
        # BTC (dust) çıkarıldı, diğerleri kaldı
        assert "BTC" not in filtered
        assert "USDT" in filtered
        assert "ETH" in filtered


class TestExchangeDustSweep:
    """Exchange dust sweep testleri."""
    
    def test_sweep_dust_paper_mode(self):
        """Paper mode'da dust sweep simüle edilir."""
        from execution.exchange_client import ExchangeClient
        from config.settings import TradingMode
        
        mock_client = ExchangeClient()
        mock_client._params = Mock()
        mock_client._params.execution.mode = TradingMode.PAPER
        
        result = mock_client.sweep_dust(target_asset="BNB")
        
        assert result["status"] == "paper_mode"
        assert result["swept"] == []
        assert result["received"] == 0.0
    
    def test_sweep_dust_no_dust(self):
        """Dust yoksa sweep yapma."""
        from execution.exchange_client import ExchangeClient
        
        mock_client = ExchangeClient()
        mock_client._params = Mock()
        mock_client._params.execution = Mock()
        mock_client._params.execution.mode = TradingMode.LIVE
        mock_client._params.execution.rate_limit_ms = 1200
        
        # Mock _get_dust_assets
        mock_client._get_dust_assets = Mock(return_value=[])
        
        # Mock exchange
        mock_exchange = Mock()
        mock_client._get_exchange = Mock(return_value=mock_exchange)
        
        result = mock_client.sweep_dust(target_asset="BNB")
        
        assert result["status"] == "no_dust"
        assert result["swept"] == []
    
    def test_sweep_dust_success(self):
        """Dust sweep başarılı."""
        from execution.exchange_client import ExchangeClient
        
        mock_client = ExchangeClient()
        mock_client._params = Mock()
        mock_client._params.execution = Mock()
        mock_client._params.execution.mode = TradingMode.LIVE
        mock_client._params.execution.rate_limit_ms = 1200
        
        # Mock dust assets
        mock_client._get_dust_assets = Mock(return_value=["BTC", "ETH"])
        
        # Mock exchange response
        mock_exchange = Mock()
        mock_exchange.sapi_post_asset_dust.return_value = {
            'totalTransferedAmount': '0.123',
            'transferResult': [
                {'asset': 'BTC', 'success': True},
                {'asset': 'ETH', 'success': True},
            ]
        }
        mock_client._get_exchange = Mock(return_value=mock_exchange)
        
        result = mock_client.sweep_dust(target_asset="BNB")
        
        assert result["status"] == "success"
        assert "BTC" in result["swept"]
        assert "ETH" in result["swept"]
        assert result["received"] == 0.123
        assert result["target_asset"] == "BNB"


class TestSyncManagerDustSweep:
    """SyncManager periyodik dust sweep testleri."""
    
    def test_maybe_sweep_dust_interval(self):
        """Dust sweep her N cycle'da bir."""
        from execution.sync_manager import SyncManager
        from execution.exchange_client import ExchangeClient
        from risk.portfolio import PortfolioState
        
        portfolio = PortfolioState()
        exchange_client = ExchangeClient()
        
        # Mock sweep_dust
        exchange_client.sweep_dust = Mock(return_value={
            "status": "success",
            "swept": ["BTC"],
            "received": 0.01,
        })
        
        sync = SyncManager(
            portfolio=portfolio,
            exchange_client=exchange_client,
            dust_sweep_every_n_cycles=100,
        )
        
        # Cycle 50: Henüz erken
        result = sync._maybe_sweep_dust(cycle=50)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_time_yet"
        
        # Cycle 100: Zamanı geldi
        result = sync._maybe_sweep_dust(cycle=100)
        assert result["status"] == "success"
        assert sync._last_dust_sweep_cycle == 100
        
        # Cycle 150: Henüz erken (bir önceki 100'de yapıldı)
        result = sync._maybe_sweep_dust(cycle=150)
        assert result["status"] == "skipped"
        
        # Cycle 200: Tekrar zamanı
        result = sync._maybe_sweep_dust(cycle=200)
        assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
