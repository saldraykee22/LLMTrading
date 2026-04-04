"""
Rejim Filtresi Modülü
======================
VIX endeksine dayalı piyasa volatilite rejimi tespiti.
Yüksek volatilite dönemlerinde duyarlılık bazlı işlemleri durdurur.
"""

from __future__ import annotations

import logging
from enum import Enum

import numpy as np
import pandas as pd

from config.settings import RegimeState, get_trading_params

logger = logging.getLogger(__name__)


class RegimeFilter:
    """VIX tabanlı piyasa rejimi filtresi."""

    def __init__(self) -> None:
        self._params = get_trading_params()
        self._current_regime = RegimeState.NORMAL
        self._vix_current: float = 0.0
        self._vix_sma: float = 0.0

    def update(self, vix_data: pd.DataFrame) -> RegimeState:
        """
        VIX verisini günceller ve rejim durumunu belirler.

        Args:
            vix_data: VIX OHLCV DataFrame'i

        Returns:
            Güncel rejim durumu
        """
        if vix_data.empty or len(vix_data) < self._params.regime.vix_sma_period:
            logger.warning("Yetersiz VIX verisi, varsayılan NORMAL rejim")
            self._current_regime = RegimeState.NORMAL
            return self._current_regime

        # Güncel VIX
        self._vix_current = float(vix_data["close"].iloc[-1])

        # VIX SMA
        sma_period = self._params.regime.vix_sma_period
        self._vix_sma = float(vix_data["close"].tail(sma_period).mean())

        # Eşik değeri
        threshold = self._vix_sma * self._params.regime.vix_threshold_multiplier

        # Rejim belirleme
        if self._vix_current > 40:
            self._current_regime = RegimeState.CRISIS
        elif self._vix_current > threshold:
            self._current_regime = RegimeState.HIGH_VOL
        elif self._vix_current < self._vix_sma * 0.8:
            self._current_regime = RegimeState.LOW_VOL
        else:
            self._current_regime = RegimeState.NORMAL

        logger.info(
            "Rejim: %s (VIX: %.2f, SMA: %.2f, Eşik: %.2f)",
            self._current_regime.value,
            self._vix_current,
            self._vix_sma,
            threshold,
        )
        return self._current_regime

    def should_halt_trading(self) -> bool:
        """Yüksek volatilite nedeniyle işlem durdurulmalı mı?"""
        if not self._params.regime.halt_on_high_vol:
            return False
        return self._current_regime in (RegimeState.HIGH_VOL, RegimeState.CRISIS)

    @property
    def regime(self) -> RegimeState:
        return self._current_regime

    @property
    def vix_current(self) -> float:
        return self._vix_current

    @property
    def vix_sma(self) -> float:
        return self._vix_sma

    def get_status(self) -> dict:
        """Rejim durumu özeti."""
        return {
            "regime": self._current_regime.value,
            "vix_current": round(self._vix_current, 2),
            "vix_sma": round(self._vix_sma, 2),
            "halt_trading": self.should_halt_trading(),
        }


class CryptoFearGreedFilter:
    """
    Kripto Fear & Greed Index filtresi.
    Alternative.me API'den çekilebilir (ücretsiz).
    """

    def __init__(self) -> None:
        self._params = get_trading_params()
        self._index_value: int = 50  # Varsayılan: nötr
        self._classification: str = "neutral"

    def update(self, index_value: int) -> str:
        """
        Fear & Greed indeksini günceller.

        Args:
            index_value: 0 (aşırı korku) → 100 (aşırı açgözlülük)
        """
        self._index_value = index_value

        if index_value <= 20:
            self._classification = "extreme_fear"
        elif index_value <= 40:
            self._classification = "fear"
        elif index_value <= 60:
            self._classification = "neutral"
        elif index_value <= 80:
            self._classification = "greed"
        else:
            self._classification = "extreme_greed"

        logger.info(
            "Kripto Fear & Greed: %d (%s)", index_value, self._classification
        )
        return self._classification

    def should_reduce_exposure(self) -> bool:
        """Aşırı korku veya açgözlülükte pozisyon azalt."""
        threshold = self._params.regime.crypto_fear_greed_threshold
        return self._index_value <= threshold or self._index_value >= (100 - threshold)

    def get_status(self) -> dict:
        return {
            "index": self._index_value,
            "classification": self._classification,
            "reduce_exposure": self.should_reduce_exposure(),
        }
