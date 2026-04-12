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
        side: str = "long",
    ) -> float:
        """Side-aware hard stop calculation"""
        pct = self._params.stop_loss.hard_stop_pct
        
        if side == "long":
            return entry_price * (1 - pct)
        elif side == "short":
            return entry_price * (1 + pct)
        else:
            raise ValueError(f"Geçersiz side: {side}")

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
            if len(df) > 0:
                # Geçici: Son 5 mumun ortalama range'i
                recent = df.tail(min(5, len(df)))
                return float((recent["high"] - recent["low"]).mean())
            return 0.01 * float(df["close"].iloc[-1]) if not df.empty else 1.0  # %1 fallback

        atr = ta.atr(df["high"], df["low"], df["close"], length=p)
        if atr is not None and not atr.empty:
            val = float(atr.iloc[-1])
            if not np.isnan(val) and val > 0:
                return val

        # Minimum ATR: fiyatın %0.5'i
        fallback = 0.005 * float(df["close"].iloc[-1]) if not df.empty else 1.0
        logger.warning(f"ATR hesaplanamadı, fallback: {fallback:.4f}")
        return fallback

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
