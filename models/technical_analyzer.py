"""
Teknik Analiz Modülü
=====================
pandas-ta kullanarak teknik göstergeler hesaplar ve sinyal üretir.
- RSI, MACD, Bollinger Bands, ATR, EMA, SMA
- Destek/Direnç seviyeleri
- Trend gücü değerlendirmesi
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


@dataclass
class TechnicalSignals:
    """Teknik analiz sonuçları."""

    symbol: str
    trend: str = "neutral"  # bullish | bearish | neutral
    trend_strength: float = 0.0  # 0.0 → 1.0
    signal: str = "hold"  # buy | sell | hold

    # Göstergeler
    rsi_14: float = 50.0
    macd_signal: str = "neutral"  # bullish_cross | bearish_cross | neutral
    macd_histogram: float = 0.0
    bb_position: str = "middle"  # above_upper | middle | below_lower
    atr_14: float = 0.0
    ema_20: float = 0.0
    ema_50: float = 0.0
    sma_200: float = 0.0
    current_price: float = 0.0
    volume_sma_ratio: float = 1.0  # Güncel hacim / 20-günlük ort. hacim

    # Seviyeler
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Dict'e dönüştürür (LLM'e gönderim için)."""
        return {
            "trend": self.trend,
            "trend_strength": round(self.trend_strength, 3),
            "signal": self.signal,
            "rsi_14": round(self.rsi_14, 2),
            "macd_signal": self.macd_signal,
            "macd_histogram": round(self.macd_histogram, 4),
            "bb_position": self.bb_position,
            "atr_14": round(self.atr_14, 4),
            "ema_20": round(self.ema_20, 4),
            "ema_50": round(self.ema_50, 4),
            "sma_200": round(self.sma_200, 4),
            "current_price": round(self.current_price, 4),
            "volume_sma_ratio": round(self.volume_sma_ratio, 2),
            "support_levels": [round(s, 4) for s in self.support_levels[:3]],
            "resistance_levels": [round(r, 4) for r in self.resistance_levels[:3]],
        }


class TechnicalAnalyzer:
    """Teknik gösterge hesaplama ve sinyal üretme motoru."""

    def analyze(self, df: pd.DataFrame, symbol: str = "") -> TechnicalSignals:
        """
        OHLCV DataFrame'inden teknik göstergeleri hesaplar.

        Args:
            df: OHLCV verileri (datetime, open, high, low, close, volume)
            symbol: Varlık sembolü

        Returns:
            TechnicalSignals: Hesaplanan göstergeler ve sinyal
        """
        if df.empty or len(df) < 30:
            logger.warning("Yetersiz veri (%d mum), varsayılan signal dönüyor", len(df))
            return TechnicalSignals(symbol=symbol)

        signals = TechnicalSignals(symbol=symbol)
        signals.current_price = float(df["close"].iloc[-1])

        # ── RSI (14) ──────────────────────────────────────
        rsi = ta.rsi(df["close"], length=14)
        if rsi is not None and not rsi.empty:
            signals.rsi_14 = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

        # ── MACD ──────────────────────────────────────────
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            macd_col = "MACD_12_26_9"
            signal_col = "MACDs_12_26_9"
            hist_col = "MACDh_12_26_9"

            if macd_col in macd_df.columns and signal_col in macd_df.columns:
                macd_line = macd_df[macd_col].iloc[-1]
                signal_line = macd_df[signal_col].iloc[-1]
                hist_val = (
                    macd_df[hist_col].iloc[-1]
                    if hist_col in macd_df.columns
                    else macd_line - signal_line
                )

                signals.macd_histogram = (
                    float(hist_val) if not np.isnan(hist_val) else 0.0
                )

                if not np.isnan(macd_line) and not np.isnan(signal_line):
                    if len(macd_df) >= 2:
                        prev_macd = macd_df[macd_col].iloc[-2]
                        prev_signal = macd_df[signal_col].iloc[-2]
                        if not np.isnan(prev_macd) and not np.isnan(prev_signal):
                            if prev_macd <= prev_signal and macd_line > signal_line:
                                signals.macd_signal = "bullish_cross"
                            elif prev_macd >= prev_signal and macd_line < signal_line:
                                signals.macd_signal = "bearish_cross"
            else:
                macd_line = macd_df.iloc[-1, 0]
                signal_line = macd_df.iloc[-1, 2]
                hist = macd_df.iloc[-1, 1]
                signals.macd_histogram = float(hist) if not np.isnan(hist) else 0.0
                if not np.isnan(macd_line) and not np.isnan(signal_line):
                    if len(macd_df) >= 2:
                        prev_macd = macd_df.iloc[-2, 0]
                        prev_signal = macd_df.iloc[-2, 2]
                        if not np.isnan(prev_macd) and not np.isnan(prev_signal):
                            if prev_macd <= prev_signal and macd_line > signal_line:
                                signals.macd_signal = "bullish_cross"
                            elif prev_macd >= prev_signal and macd_line < signal_line:
                                signals.macd_signal = "bearish_cross"

        # ── Bollinger Bands ───────────────────────────────
        bbands = ta.bbands(df["close"], length=20, std=2.0)
        if bbands is not None and not bbands.empty:
            upper_col = f"BBU_20_2.0"
            lower_col = f"BBL_20_2.0"

            if upper_col in bbands.columns and lower_col in bbands.columns:
                upper = bbands[upper_col].iloc[-1]
                lower = bbands[lower_col].iloc[-1]
            else:
                upper = bbands.iloc[-1, 0]
                lower = bbands.iloc[-1, 2]

            if not np.isnan(upper) and not np.isnan(lower):
                price = signals.current_price
                if price > upper:
                    signals.bb_position = "above_upper"
                elif price < lower:
                    signals.bb_position = "below_lower"
                else:
                    signals.bb_position = "middle"

        # ── ATR (14) ──────────────────────────────────────
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr is not None and not atr.empty:
            signals.atr_14 = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0

        # ── Moving Averages ───────────────────────────────
        ema20 = ta.ema(df["close"], length=20)
        ema50 = ta.ema(df["close"], length=50)
        sma200 = ta.sma(df["close"], length=200)

        if ema20 is not None and not ema20.empty:
            signals.ema_20 = (
                float(ema20.iloc[-1]) if not np.isnan(ema20.iloc[-1]) else 0.0
            )
        if ema50 is not None and not ema50.empty:
            signals.ema_50 = (
                float(ema50.iloc[-1]) if not np.isnan(ema50.iloc[-1]) else 0.0
            )
        if sma200 is not None and not sma200.empty and len(df) >= 200:
            signals.sma_200 = (
                float(sma200.iloc[-1]) if not np.isnan(sma200.iloc[-1]) else 0.0
            )

        # ── Hacim Analizi ─────────────────────────────────
        vol_sma = ta.sma(df["volume"], length=20)
        if vol_sma is not None and not vol_sma.empty:
            current_vol = float(df["volume"].iloc[-1])
            avg_vol = float(vol_sma.iloc[-1])
            if avg_vol > 0:
                signals.volume_sma_ratio = current_vol / avg_vol

        # ── Destek / Direnç ───────────────────────────────
        signals.support_levels, signals.resistance_levels = self._find_levels(df)

        # ── Trend Belirleme ───────────────────────────────
        signals.trend, signals.trend_strength = self._determine_trend(signals)

        # ── Sinyal Üretimi ────────────────────────────────
        signals.signal = self._generate_signal(signals)

        logger.info(
            "Teknik: %s → %s (güç: %.2f, RSI: %.1f, sinyal: %s)",
            symbol,
            signals.trend,
            signals.trend_strength,
            signals.rsi_14,
            signals.signal,
        )
        return signals

    def _determine_trend(self, s: TechnicalSignals) -> tuple[str, float]:
        """Trend yönü ve gücünü belirler."""
        score = 0.0
        factors = 0

        # EMA çaprazı
        if s.ema_20 > 0 and s.ema_50 > 0:
            if s.ema_20 > s.ema_50:
                score += 1.0
            else:
                score -= 1.0
            factors += 1

        # Fiyat vs EMA20
        if s.current_price > 0 and s.ema_20 > 0:
            if s.current_price > s.ema_20:
                score += 0.5
            else:
                score -= 0.5
            factors += 1

        # RSI
        if s.rsi_14 > 60:
            score += 0.5
        elif s.rsi_14 < 40:
            score -= 0.5
        factors += 1

        # MACD
        if s.macd_signal == "bullish_cross":
            score += 1.0
        elif s.macd_signal == "bearish_cross":
            score -= 1.0
        factors += 1

        if factors == 0:
            return "neutral", 0.0

        normalized = score / factors  # -1 → 1 aralığında

        if normalized > 0.3:
            trend = "bullish"
        elif normalized < -0.3:
            trend = "bearish"
        else:
            trend = "neutral"

        strength = min(abs(normalized), 1.0)
        return trend, strength

    def _generate_signal(self, s: TechnicalSignals) -> str:
        """Teknik göstergelere dayalı sinyal üretir."""
        buy_score = 0
        sell_score = 0

        # RSI
        if s.rsi_14 < 30:
            buy_score += 2  # Aşırı satım
        elif s.rsi_14 < 40:
            buy_score += 1
        elif s.rsi_14 > 70:
            sell_score += 2  # Aşırı alım
        elif s.rsi_14 > 60:
            sell_score += 1

        # MACD
        if s.macd_signal == "bullish_cross":
            buy_score += 2
        elif s.macd_signal == "bearish_cross":
            sell_score += 2

        # Bollinger
        if s.bb_position == "below_lower":
            buy_score += 1
        elif s.bb_position == "above_upper":
            sell_score += 1

        # Trend
        if s.trend == "bullish":
            buy_score += 1
        elif s.trend == "bearish":
            sell_score += 1

        # Hacim
        if s.volume_sma_ratio > 1.5:
            # Yüksek hacim, mevcut trendi güçlendirir
            if buy_score > sell_score:
                buy_score += 1
            elif sell_score > buy_score:
                sell_score += 1

        if buy_score >= 4 and buy_score > sell_score:
            return "buy"
        elif sell_score >= 4 and sell_score > buy_score:
            return "sell"
        return "hold"

    def _find_levels(
        self, df: pd.DataFrame, window: int = 20
    ) -> tuple[list[float], list[float]]:
        """Basit pivot noktalarından destek/direnç seviyeleri bulur."""
        if len(df) < window * 2:
            return [], []

        highs = df["high"].values
        lows = df["low"].values
        current = float(df["close"].iloc[-1])

        supports: list[float] = []
        resistances: list[float] = []

        for i in range(window, len(df) - window):
            # Yerel minimum → destek
            if lows[i] == min(lows[i - window : i + window + 1]):
                if lows[i] < current:
                    supports.append(float(lows[i]))
            # Yerel maksimum → direnç
            if highs[i] == max(highs[i - window : i + window + 1]):
                if highs[i] > current:
                    resistances.append(float(highs[i]))

        # En yakın seviyeleri seç
        supports = sorted(set(supports), reverse=True)[:5]
        resistances = sorted(set(resistances))[:5]

        return supports, resistances
