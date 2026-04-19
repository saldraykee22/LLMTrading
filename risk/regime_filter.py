"""
Rejim Filtresi Modülü
======================
VIX + Crypto Fear & Greed hibrit piyasa rejimi tespiti.
Hızlı ve kripto-özel sinyaller ile pozisyon boyutunu dinamik ayarla.
"""

from __future__ import annotations

import logging
from enum import Enum

import numpy as np
import pandas as pd

from config.settings import RegimeState, get_trading_params

logger = logging.getLogger(__name__)


class CryptoRegimeState(Enum):
    """Kripto-özel rejim durumları."""
    BULLISH = "boğa"       # VIX düşük + F&G yüksek → %100 exposure
    NEUTRAL = "nötr"       # Karışık sinyaller → %60 exposure
    BEARISH = "ayı"        # VIX yüksek VEYA F&G düşük → %20 exposure
    CRASH = "çöküş"        # VIX çok yüksek + F&G çok düşük → %0 (nakit)


class RegimeFilter:
    """
    VIX + Crypto Fear & Greed hibrit rejim filtresi.
    
    Rejim Matrisi:
    - BOĞA:   VIX < 25  + F&G > 60  → %100 kripto
    - NÖTR:   VIX 25-35 + F&G 40-60 → %60 kripto
    - AYI:    VIX > 35  + F&G < 40  → %20 kripto
    - ÇÖKÜŞ:  VIX > 40  + F&G < 20  → %0 (tam nakit)
    """

    def __init__(self) -> None:
        self._params = get_trading_params()
        self._current_regime = CryptoRegimeState.NEUTRAL
        self._vix_current: float = 0.0
        self._vix_sma: float = 0.0
        self._fear_greed_index: int = 50  # Nötr başlangıç
        self._fear_greed_classification: str = "neutral"

    def update(self, vix_data: pd.DataFrame, fear_greed_index: int | None = None) -> CryptoRegimeState:
        """
        VIX ve Fear & Greed verilerini günceller, rejim durumunu belirler.

        Args:
            vix_data: VIX OHLCV DataFrame'i
            fear_greed_index: Crypto Fear & Greed Index (0-100)

        Returns:
            Güncel rejim durumu
        """
        # VIX güncelle
        if vix_data is not None and not vix_data.empty:
            self._vix_current = float(vix_data["close"].iloc[-1])
            
            if len(vix_data) >= self._params.regime.vix_sma_period:
                self._vix_sma = float(vix_data["close"].tail(self._params.regime.vix_sma_period).mean())
            else:
                self._vix_sma = self._vix_current
        else:
            logger.warning("VIX verisi yok, varsayılan değerler kullanılıyor")
            self._vix_current = 20.0  # Normal VIX
            self._vix_sma = 20.0
        
        # Fear & Greed güncelle
        if fear_greed_index is not None:
            self._fear_greed_index = fear_greed_index
            self._fear_greed_classification = self._classify_fear_greed(fear_greed_index)
        
        # Rejim skorlaması (0-100)
        regime_score = self._calculate_regime_score()
        
        # Rejim belirleme
        self._current_regime = self._determine_regime(regime_score)
        
        logger.info(
            "Rejim: %s (Skor: %.1f, VIX: %.2f, F&G: %d)",
            self._current_regime.value,
            regime_score,
            self._vix_current,
            self._fear_greed_index,
        )
        
        return self._current_regime
    
    def _classify_fear_greed(self, index_value: int) -> str:
        """Fear & Greed indeksini sınıflandır."""
        if index_value <= 20:
            return "extreme_fear"
        elif index_value <= 40:
            return "fear"
        elif index_value <= 60:
            return "neutral"
        elif index_value <= 80:
            return "greed"
        else:
            return "extreme_greed"
    
    def _calculate_regime_score(self) -> float:
        """
        Rejim skoru hesapla (0-100).
        Yüksek skor = boğa, düşük skor = ayı
        
        Returns:
            0-100 arası rejim skoru
        """
        # VIX skoru (0-50): VIX düşük = yüksek skor
        vix_score = 50.0
        if self._vix_current < 20:
            vix_score = 50  # Maksimal
        elif self._vix_current < 25:
            vix_score = 40
        elif self._vix_current < 30:
            vix_score = 30
        elif self._vix_current < 35:
            vix_score = 20
        elif self._vix_current < 40:
            vix_score = 10
        else:
            vix_score = 0  # Kriz
        
        # Fear & Greed skoru (0-50): F&G yüksek = yüksek skor
        fg_score = (self._fear_greed_index / 100.0) * 50
        
        return vix_score + fg_score
    
    def _determine_regime(self, score: float) -> CryptoRegimeState:
        """
        Rejim skoruna göre rejim durumu belirle.
        
        Args:
            score: 0-100 arası rejim skoru
        
        Returns:
            CryptoRegimeState
        """
        if score >= 70:
            return CryptoRegimeState.BULLISH
        elif score >= 40:
            return CryptoRegimeState.NEUTRAL
        elif score >= 20:
            return CryptoRegimeState.BEARISH
        else:
            return CryptoRegimeState.CRASH
    
    def get_max_exposure(self) -> float:
        """
        Rejime göre maksimum kripto pozisyon exposure'u.
        
        Returns:
            0.0-1.0 arası maksimum exposure oranı
        """
        exposure_map = {
            CryptoRegimeState.BULLISH: self._params.regime.bull_max_exposure,
            CryptoRegimeState.NEUTRAL: self._params.regime.neutral_max_exposure,
            CryptoRegimeState.BEARISH: self._params.regime.bear_max_exposure,
            CryptoRegimeState.CRASH: self._params.regime.crash_max_exposure,
        }
        return exposure_map.get(self._current_regime, 0.6)
    
    def should_halt_trading(self) -> bool:
        """Rejim nedeniyle işlem durdurulmalı mı?"""
        if not self._params.regime.halt_on_high_vol:
            return False
        # CRASH rejiminde işlemleri durdur
        return self._current_regime == CryptoRegimeState.CRASH
    
    def should_reduce_exposure(self) -> bool:
        """Pozisyon azaltma gerekli mi?"""
        return self._current_regime in (CryptoRegimeState.BEARISH, CryptoRegimeState.CRASH)
    
    @property
    def regime(self) -> CryptoRegimeState:
        return self._current_regime
    
    @property
    def vix_current(self) -> float:
        return self._vix_current
    
    @property
    def vix_sma(self) -> float:
        return self._vix_sma
    
    @property
    def fear_greed_index(self) -> int:
        return self._fear_greed_index
    
    def get_status(self) -> dict:
        """Rejim durumu özeti."""
        return {
            "regime": self._current_regime.value,
            "regime_score": self._calculate_regime_score(),
            "vix_current": round(self._vix_current, 2),
            "vix_sma": round(self._vix_sma, 2),
            "fear_greed_index": self._fear_greed_index,
            "fear_greed_classification": self._fear_greed_classification,
            "max_exposure": self.get_max_exposure(),
            "halt_trading": self.should_halt_trading(),
            "reduce_exposure": self.should_reduce_exposure(),
        }

# CryptoFearGreedFilter artık RegimeFilter içinde entegre
# Geriye dönük uyumluluk için wrapper
class CryptoFearGreedFilter:
    """
    Kripto Fear & Greed Index filtresi (geriye dönük uyumluluk).
    Alternative.me API'den çekilebilir (ücretsiz).
    """

    def __init__(self) -> None:
        self._params = get_trading_params()
        self._index_value: int = 50
        self._classification: str = "neutral"
        self._regime_filter = RegimeFilter()

    def update(self, index_value: int) -> str:
        """Fear & Greed indeksini günceller."""
        self._index_value = index_value
        self._classification = self._regime_filter._classify_fear_greed(index_value)
        logger.info("Kripto Fear & Greed: %d (%s)", index_value, self._classification)
        return self._classification

    def should_reduce_exposure(self) -> bool:
        """Aşırı korku veya açgözlülükte pozisyon azalt."""
        return self._index_value <= 25 or self._index_value >= 75

    def get_status(self) -> dict:
        return {
            "index": self._index_value,
            "classification": self._classification,
            "reduce_exposure": self.should_reduce_exposure(),
        }
