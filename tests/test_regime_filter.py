"""
Rejim Filtresi Testleri (Faz 2)
================================
Hibrit rejim tespiti (VIX + Fear & Greed) testleri.
"""

import pytest
import pandas as pd
from risk.regime_filter import RegimeFilter, CryptoRegimeState


class TestRegimeFilter:
    """RegimeFilter hibrit rejim testleri."""
    
    def test_bullish_regime(self):
        """BOĞA rejimi: VIX düşük + F&G yüksek."""
        filter = RegimeFilter()
        
        # VIX < 25 + F&G > 60 → BOĞA
        vix_data = pd.DataFrame({
            "close": [18.0, 19.0, 20.0, 19.5, 18.5]  # Düşük VIX
        })
        
        regime = filter.update(vix_data, fear_greed_index=75)  # Yüksek F&G
        
        assert regime == CryptoRegimeState.BULLISH
        assert filter.get_max_exposure() == 1.0  # %100 kripto
    
    def test_neutral_regime(self):
        """NÖTR rejim: Karışık sinyaller."""
        filter = RegimeFilter()
        
        # VIX 25-35 + F&G 40-60 → NÖTR
        vix_data = pd.DataFrame({
            "close": [28.0, 29.0, 30.0, 29.5, 28.5]  # Orta VIX
        })
        
        regime = filter.update(vix_data, fear_greed_index=50)  # Nötr F&G
        
        assert regime == CryptoRegimeState.NEUTRAL
        assert filter.get_max_exposure() == 0.60  # %60 kripto
    
    def test_bearish_regime(self):
        """AYI rejimi: VIX yüksek + F&G düşük."""
        filter = RegimeFilter()
        
        # VIX > 35 + F&G < 40 → AYI
        vix_data = pd.DataFrame({
            "close": [38.0, 39.0, 40.0, 39.5, 38.5]  # Yüksek VIX
        })
        
        regime = filter.update(vix_data, fear_greed_index=30)  # Düşük F&G
        
        assert regime == CryptoRegimeState.BEARISH
        assert filter.get_max_exposure() == 0.20  # %20 kripto
    
    def test_crash_regime(self):
        """ÇÖKÜŞ rejimi: VIX çok yüksek + F&G çok düşük."""
        filter = RegimeFilter()
        
        # VIX > 40 + F&G < 20 → ÇÖKÜŞ
        vix_data = pd.DataFrame({
            "close": [45.0, 48.0, 50.0, 52.0, 55.0]  # Kriz VIX
        })
        
        regime = filter.update(vix_data, fear_greed_index=15)  # Aşırı korku
        
        assert regime == CryptoRegimeState.CRASH
        assert filter.get_max_exposure() == 0.0  # %0 kripto (tam nakit)
    
    def test_should_halt_trading(self):
        """CRASH rejiminde işlem durdurulmalı."""
        filter = RegimeFilter()
        
        vix_data = pd.DataFrame({"close": [50.0, 52.0, 55.0]})
        filter.update(vix_data, fear_greed_index=10)
        
        assert filter.should_halt_trading() is True
        assert filter.regime == CryptoRegimeState.CRASH
    
    def test_should_reduce_exposure(self):
        """AYI ve ÇÖKÜŞ rejimlerinde pozisyon azaltma."""
        filter = RegimeFilter()
        
        # AYI rejimi
        vix_data = pd.DataFrame({"close": [40.0, 41.0, 42.0]})
        filter.update(vix_data, fear_greed_index=25)
        
        assert filter.should_reduce_exposure() is True
        
        # ÇÖKÜŞ rejimi
        filter.update(vix_data, fear_greed_index=10)
        assert filter.should_reduce_exposure() is True
        
        # BOĞA rejimi (azaltma yok)
        vix_data = pd.DataFrame({"close": [18.0, 19.0, 20.0]})
        filter.update(vix_data, fear_greed_index=80)
        assert filter.should_reduce_exposure() is False
    
    def test_regime_score_calculation(self):
        """Rejim skoru hesaplama mantığı."""
        filter = RegimeFilter()
        
        # Maksimal skor: VIX çok düşük + F&G çok yüksek
        vix_data = pd.DataFrame({"close": [15.0]})
        filter.update(vix_data, fear_greed_index=100)
        score = filter._calculate_regime_score()
        assert score >= 90  # ~100'e yakın
        
        # Minimal skor: VIX çok yüksek + F&G çok düşük
        filter.update(vix_data, fear_greed_index=0)
        vix_data = pd.DataFrame({"close": [60.0]})
        filter.update(vix_data, fear_greed_index=0)
        score = filter._calculate_regime_score()
        assert score <= 10  # ~0'a yakın
    
    def test_get_status(self):
        """Rejim durum özeti."""
        filter = RegimeFilter()
        
        vix_data = pd.DataFrame({"close": [30.0, 31.0, 32.0]})
        result = filter.update(vix_data, fear_greed_index=45)
        
        status = filter.get_status()
        
        assert "regime" in status
        assert "vix_current" in status
        assert "fear_greed_classification" in status, f"Status keys: {status.keys()}"
        assert "max_exposure" in status
        assert "halt_trading" in status
        assert status["fear_greed_classification"] == "neutral"


class TestPortfolioExposureLimit:
    """Portfolio exposure limit testleri."""
    
    def test_bullish_full_exposure(self):
        """BOĞA rejiminde %100 exposure."""
        filter = RegimeFilter()
        
        vix_data = pd.DataFrame({"close": [20.0]})
        filter.update(vix_data, fear_greed_index=70)
        
        assert filter.get_max_exposure() == 1.0
    
    def test_neutral_partial_exposure(self):
        """NÖTR rejiminde %60 exposure."""
        filter = RegimeFilter()
        
        vix_data = pd.DataFrame({"close": [30.0]})
        filter.update(vix_data, fear_greed_index=50)
        
        assert abs(filter.get_max_exposure() - 0.60) < 0.01
    
    def test_bearish_low_exposure(self):
        """AYI rejiminde %20 exposure."""
        filter = RegimeFilter()
        
        vix_data = pd.DataFrame({"close": [38.0]})
        filter.update(vix_data, fear_greed_index=30)
        
        assert abs(filter.get_max_exposure() - 0.20) < 0.01
    
    def test_crash_zero_exposure(self):
        """ÇÖKÜŞ rejiminde %0 exposure."""
        filter = RegimeFilter()
        
        vix_data = pd.DataFrame({"close": [50.0]})
        filter.update(vix_data, fear_greed_index=15)
        
        assert filter.get_max_exposure() == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
