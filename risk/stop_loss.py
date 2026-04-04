"""
Dinamik ATR Trailing Stop-Loss Modülü
=======================================
ATR (Average True Range) tabanlı izleyen zarar-kes mekanizması.
Fiyat lehte hareket ettikçe stop seviyesi otomatik olarak güncellenir.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pandas_ta as ta

from config.settings import get_trading_params

logger = logging.getLogger(__name__)


class DynamicStopLoss:
    """ATR tabanlı dinamik izleyen zarar-kes yöneticisi."""

    def __init__(self) -> None:
        self._params = get_trading_params()

    def calculate_initial_stop(
        self,
        entry_price: float,
        atr_value: float,
        multiplier: float | None = None,
    ) -> float:
        """
        İlk zarar-kes seviyesini hesaplar.

        Args:
            entry_price: Giriş fiyatı
            atr_value: Güncel ATR değeri
            multiplier: ATR çarpanı (varsayılan: YAML'den)

        Returns:
            Zarar-kes fiyat seviyesi
        """
        mult = multiplier or self._params.stop_loss.atr_multiplier

        stop = entry_price - (atr_value * mult)

        logger.debug(
            "Stop-loss long @ %.4f, ATR=%.4f, mult=%.1f → stop=%.4f",
            entry_price,
            atr_value,
            mult,
            stop,
        )
        return max(stop, 0.0)

    def calculate_hard_stop(
        self,
        entry_price: float,
    ) -> float:
        """Sabit yüzdelik zarar-kes (son savunma hattı)."""
        pct = self._params.stop_loss.hard_stop_pct
        return entry_price * (1 - pct)

    def update_trailing_stop(
        self,
        current_stop: float,
        current_price: float,
        atr_value: float,
        multiplier: float | None = None,
    ) -> float:
        """
        İzleyen zarar-kes seviyesini günceller.
        Stop sadece lehte hareket eder, asla aleyhte geri çekilmez.

        Args:
            current_stop: Mevcut stop seviyesi
            current_price: Güncel fiyat
            atr_value: Güncel ATR değeri
            multiplier: ATR çarpanı

        Returns:
            Güncellenmiş stop seviyesi
        """
        if not self._params.stop_loss.trailing_enabled:
            return current_stop

        mult = multiplier or self._params.stop_loss.atr_multiplier

        new_stop = current_price - (atr_value * mult)
        updated = max(current_stop, new_stop)

        if updated != current_stop:
            logger.debug(
                "Trailing stop güncellendi: %.4f → %.4f (fiyat: %.4f)",
                current_stop,
                updated,
                current_price,
            )

        return updated

    def calculate_atr(
        self,
        df: pd.DataFrame,
        period: int | None = None,
    ) -> float:
        """OHLCV DataFrame'inden ATR hesaplar."""
        p = period or self._params.stop_loss.atr_period
        if len(df) < p:
            logger.warning("Yetersiz veri ATR hesaplama için (%d < %d)", len(df), p)
            # Basit yaklaşım
            if len(df) > 0:
                return float((df["high"] - df["low"]).mean())
            return 0.0

        atr = ta.atr(df["high"], df["low"], df["close"], length=p)
        if atr is not None and not atr.empty:
            val = float(atr.iloc[-1])
            return val if not np.isnan(val) else 0.0
        return 0.0

    def should_exit(
        self,
        current_price: float,
        stop_level: float,
    ) -> bool:
        """Zarar-kes tetiklendi mi kontrol eder."""
        if stop_level <= 0:
            return False

        triggered = current_price <= stop_level

        if triggered:
            logger.warning(
                "STOP-LOSS TETİKLENDİ: fiyat=%.4f, stop=%.4f",
                current_price,
                stop_level,
            )
        return triggered
