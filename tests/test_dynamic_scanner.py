"""
Dinamik Tarayıcı Testleri (Faz 3)
==================================
Hacim spike'ı ve dinamik keşif testleri.
"""

import pytest
from unittest.mock import Mock, MagicMock
from data.scanner import MarketScanner


class TestDynamicScanner:
    """MarketScanner dinamik tarama testleri."""
    
    def test_should_scan_adaptive_timing(self):
        """Akıllı zamanlama: Nakit oranına göre tarama sıklığı."""
        mock_client = Mock()
        scanner = MarketScanner(client=mock_client)
        
        scanner.params_dict["scan_interval_hours"] = 6
        scanner.params_dict["scan_interval_hours_high_cash"] = 3
        scanner.params_dict["min_cash_ratio_for_frequent_scan"] = 0.50

        # Test 1: Normal nakit (%30), 6 saatte bir
        scanner.last_scan_cycle = 0
        assert scanner.should_scan(cycle=3, cash_ratio=0.30) is False  # Henüz erken
        assert scanner.should_scan(cycle=6, cash_ratio=0.30) is True   # 6 saat geçti
        assert scanner.should_scan(cycle=7, cash_ratio=0.30) is True   # Geçti
        
        # Test 2: Yüksek nakit (%70), 3 saatte bir
        scanner.last_scan_cycle = 0
        assert scanner.should_scan(cycle=2, cash_ratio=0.70) is False  # Henüz erken
        assert scanner.should_scan(cycle=3, cash_ratio=0.70) is True   # 3 saat geçti
        assert scanner.should_scan(cycle=5, cash_ratio=0.70) is True   # Geçti
    
    def test_mark_scan_complete(self):
        """Tarama tamamlandı işaretleme."""
        mock_client = Mock()
        scanner = MarketScanner(client=mock_client)
        
        scanner.last_scan_cycle = 0
        scanner.mark_scan_complete(cycle=10)
        
        assert scanner.last_scan_cycle == 10
    
    def test_dynamic_scanner_disabled(self):
        """Dinamik tarayıcı kapalıysa tarama yapma."""
        mock_client = Mock()
        scanner = MarketScanner(client=mock_client)
        scanner.params_dict['dynamic_scanner_enabled'] = False
        
        assert scanner.should_scan(cycle=100, cash_ratio=0.90) is False
    
    def test_get_top_gainers_and_volume_spikes(self):
        """Hacim spike'ı ve gainers tespiti."""
        # Mock market data client
        mock_client = Mock()
        
        # Mock ticker verisi
        mock_tickers = {
            "BTC/USDT": {
                'last': 50000.0,
                'percentage': 3.0,  # %3 artış
                'quoteVolume': 50000000,  # $50M hacim
            },
            "ETH/USDT": {
                'last': 3000.0,
                'percentage': 5.0,  # %5 artış
                'quoteVolume': 30000000,  # $30M hacim
            },
            "SOL/USDT": {
                'last': 100.0,
                'percentage': 8.5,  # %8.5 (çok yüksek, elenecek)
                'quoteVolume': 10000000,
            },
            "PEPE/USDT": {
                'last': 0.00001,
                'percentage': 4.0,  # %4 (ideal)
                'quoteVolume': 5000000,  # $5M
            },
            "LOW_VOL/USDT": {
                'last': 10.0,
                'percentage': 3.0,
                'quoteVolume': 100000,  # $100K (çok düşük, elenecek)
            },
        }
        
        mock_client.fetch_tickers.return_value = mock_tickers
        
        scanner = MarketScanner(client=mock_client)
        
        results = scanner.get_top_gainers_and_volume_spikes(limit=3)
        
        # En az 1 sonuç olmalı (BTC, ETH, PEPE uygun)
        assert len(results) >= 1
        
        # Tüm sonuçlar dinamik keşif flag'li olmalı
        for r in results:
            assert r['dynamic_discovery'] is True
            assert 'discovery_reason' in r
            assert r['volume_ratio'] >= 2.0  # Hacim spike'ı
        
        # Hacim spike'ına göre sıralı olmalı
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i]['volume_ratio'] >= results[i+1]['volume_ratio']
    
    def test_volume_spike_detection(self):
        """Hacim spike'ı tespiti."""
        mock_client = Mock()
        
        mock_tickers = {
            "SPIKE/USDT": {
                'last': 50.0,
                'percentage': 5.0,
                'quoteVolume': 20000000,  # $20M (20x min_volume)
            },
        }
        
        mock_client.fetch_tickers.return_value = mock_tickers
        scanner = MarketScanner(client=mock_client)
        
        results = scanner.get_top_gainers_and_volume_spikes(limit=5)
        
        assert len(results) == 1
        assert results[0]['symbol'] == "SPIKE/USDT"
        assert results[0]['volume_ratio'] >= 2.0
        assert "Hacim spike" in results[0]['discovery_reason']
    
    def test_early_momentum_filter(self):
        """Erken momentum filtresi (2-8% bandı)."""
        mock_client = Mock()
        
        mock_tickers = {
            "TOO_EARLY/USDT": {
                'last': 10.0,
                'percentage': 1.0,  # %1 (çok erken, elenecek)
                'quoteVolume': 5000000,
            },
            "EARLY/USDT": {
                'last': 20.0,
                'percentage': 3.0,  # %3 (ideal)
                'quoteVolume': 5000000,
            },
            "MID/USDT": {
                'last': 30.0,
                'percentage': 6.0,  # %6 (kabul edilebilir)
                'quoteVolume': 5000000,
            },
            "TOO_LATE/USDT": {
                'last': 40.0,
                'percentage': 10.0,  # %10 (geç kalındı, elenecek)
                'quoteVolume': 5000000,
            },
        }
        
        mock_client.fetch_tickers.return_value = mock_tickers
        scanner = MarketScanner(client=mock_client)
        
        results = scanner.get_top_gainers_and_volume_spikes(limit=10)
        
        # Sadece EARLY ve MID geçmeli
        symbols = [r['symbol'] for r in results]
        assert "EARLY/USDT" in symbols
        assert "MID/USDT" in symbols
        assert "TOO_EARLY/USDT" not in symbols
        assert "TOO_LATE/USDT" not in symbols
    
    def test_empty_results(self):
        """Uygun varlık yoksa boş liste dönmeli."""
        mock_client = Mock()
        
        # Hiçbiri kriterlere uymuyor
        mock_tickers = {
            "LOW_VOL/USDT": {
                'last': 10.0,
                'percentage': 3.0,
                'quoteVolume': 100000,  # Düşük hacim
            },
            "NO_CHANGE/USDT": {
                'last': 20.0,
                'percentage': 0.5,  # Düşük değişim
                'quoteVolume': 5000000,
            },
        }
        
        mock_client.fetch_tickers.return_value = mock_tickers
        scanner = MarketScanner(client=mock_client)
        
        results = scanner.get_top_gainers_and_volume_spikes(limit=5)
        
        assert len(results) == 0
    
    def test_excluded_symbols(self):
        """Dışlanan semboller (stablecoin, leveraged tokenlar)."""
        mock_client = Mock()
        
        mock_tickers = {
            "USDT/USDT": {
                'last': 1.0,
                'percentage': 0.0,
                'quoteVolume': 100000000,
            },
            "BTC/USDT": {
                'last': 50000.0,
                'percentage': 3.0,
                'quoteVolume': 50000000,
            },
            "BULL/USDT": {
                'last': 100.0,
                'percentage': 6.0,
                'quoteVolume': 5000000,
            },
            "DOWN/USDT": {
                'last': 50.0,
                'percentage': -5.0,
                'quoteVolume': 5000000,
            },
        }
        
        mock_client.fetch_tickers.return_value = mock_tickers
        scanner = MarketScanner(client=mock_client)
        
        results = scanner.get_top_gainers_and_volume_spikes(limit=10)
        
        symbols = [r['symbol'] for r in results]
        assert "BTC/USDT" in symbols
        assert "USDT/USDT" not in symbols
        assert "BULL/USDT" not in symbols
        assert "DOWN/USDT" not in symbols


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
