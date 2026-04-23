"""
Market Scanner Modülü (Seviye 1)
================================
Piyasayı tarayıp ATR-normalized momentum ve divergence bazlı
"Erken Momentum" stratejisi ile adayları filtreler.

Strateji:
1. ATR bazlı göreceli momentum (Bitcoin/Altcoin farkı)
2. Sessiz birikim (hacim artışı > fiyat artışı)
3. Erken evre yakalama (%2-5 bandı)
"""

import logging
import pandas as pd
from typing import List, Dict, Any
from data.market_data import MarketDataClient
from config.settings import get_trading_params, MomentumThreshold

logger = logging.getLogger(__name__)


class MarketScanner:
    """Algoritmik piyasa tarayıcı - Early Momentum stratejisi + Dinamik Keşif."""

    # Dışlanacak semboller
    EXCLUDED_SYMBOLS = [
        "USDT", "USDC", "DAI", "BUSD", "FDUSD", "TUSD", "USDP", "WBTC", "WETH",
    ]
    EXCLUDED_SUFFIXES = ["UP", "DOWN", "BEAR", "BULL"]

    def __init__(self, client: MarketDataClient = None):
        self.client = client or MarketDataClient()
        self.params = get_trading_params().scanner
        # Akıllı zamanlama
        self.last_scan_cycle = 0
        # Pydantic model'den dict'e çevirip get kullan
        self.params_dict = self.params.model_dump() if hasattr(self.params, 'model_dump') else dict(self.params)
        self.scan_interval_hours = self.params_dict.get('scan_interval_hours', 6)

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """ATR hesapla (14 günlük ortalama)."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr.iloc[-1] if len(atr) > period else 0.0

    def _get_average_daily_volume_usdt(self, symbol: str, lookback_days: int = 7) -> float:
        """Son günler için ortalama günlük USDT hacmini tahmin et."""
        try:
            df = self.client.fetch_ohlcv(symbol, timeframe="1d", days=lookback_days + 2)
        except Exception as e:
            logger.debug("Ortalama hacim alınamadı (%s): %s", symbol, e)
            return float(self.params.min_volume_24h_usdt)

        if df.empty or len(df) < 2:
            return float(self.params.min_volume_24h_usdt)

        baseline = df.iloc[:-1].tail(lookback_days).copy()
        if baseline.empty:
            return float(self.params.min_volume_24h_usdt)

        avg_volume = float((baseline["close"] * baseline["volume"]).mean())
        return avg_volume if avg_volume > 0 else float(self.params.min_volume_24h_usdt)

    def _get_momentum_score(
        self, 
        change_pct: float, 
        thresholds: List[MomentumThreshold]
    ) -> float:
        """
        Verilen değişim yüzdesi için uygun skor basamağını bul.
        
        Args:
            change_pct: Fiyat değişimi (%)
            thresholds: Skor basamakları (YAML'den)
            
        Returns:
            Skor değeri
        """
        for threshold in thresholds:
            if threshold.min_pct <= change_pct < threshold.max_pct:
                return threshold.score
        
        # Hiçbiri uymazsa (ör. tam sınırda), en yakın basamağı ver
        if change_pct >= thresholds[-1].max_pct:
            return thresholds[-1].score
        elif change_pct < thresholds[0].min_pct:
            return thresholds[0].score
        
        return 0.0

    def _calculate_atr_normalized_momentum(
        self, 
        symbol: str, 
        df: pd.DataFrame
    ) -> tuple[float, float]:
        """
        ATR bazlı normalize momentum hesapla.
        
        Mantık:
        - BTC için %2 artış = 1.5 ATR katı (güçlü sinyal)
        - PEPE için %2 artış = 0.3 ATR katı (zayıf sinyal)
        
        Returns:
            (normalized_score, raw_atr_multiple)
        """
        if len(df) < self.params.atr_normalization.lookback_days:
            return 0.0, 0.0
        
        current_price = df['close'].iloc[-1]
        prev_price = df['close'].iloc[-2] if len(df) > 1 else current_price
        
        # Division by zero guard
        if prev_price <= 0 or current_price <= 0:
            return 0.0, 0.0
        
        # 24h fiyat değişimi
        price_change_pct = ((current_price - prev_price) / prev_price) * 100
        
        # ATR hesapla
        atr = self._calculate_atr(df, self.params.atr_normalization.lookback_days)
        
        if atr <= 0 or prev_price <= 0:
            return 0.0, 0.0
        
        # ATR katı (price change / ATR)
        atr_multiple = price_change_pct / (atr / prev_price * 100)
        
        # Normalize skor (ATR katını 0-30 aralığına map et)
        # İdeal: 1.0-2.0 ATR katı = erken momentum (30 puan)
        if 1.0 <= atr_multiple <= 2.5:
            normalized_score = 30  # Altın bölge
        elif 2.5 < atr_multiple <= 4.0:
            normalized_score = 20  # Momentum devam ediyor
        elif 0.5 <= atr_multiple < 1.0:
            normalized_score = 15  # Zayıf ama var
        elif atr_multiple < 0.5:
            normalized_score = 5   # Çok zayıf
        else:  # > 4.0
            normalized_score = 0   # Aşırı (düzeltme riski)
        
        return normalized_score, atr_multiple

    def _detect_silent_accumulation(
        self, 
        symbol: str,
        volume_ratio: float, 
        change_24h: float
    ) -> tuple[bool, float]:
        """
        Sessiz birikim (divergence) tespiti.
        
        Kriterler:
        - Hacim 2x+ artmış (ilgi var)
        - Fiyat <3% artmış (henüz patlamadı)
        
        Returns:
            (is_detected, bonus_score)
        """
        if not self.params.silent_accumulation.enabled:
            return False, 0.0
        
        vol_threshold = self.params.silent_accumulation.volume_threshold
        price_threshold = self.params.silent_accumulation.price_threshold
        bonus = self.params.silent_accumulation.bonus_score
        
        if volume_ratio >= vol_threshold and 0 <= change_24h <= price_threshold:
            logger.debug(
                "🔍 SILENT ACCUMULATION: %s (vol=%.2fx, price=%.2f%%)",
                symbol, volume_ratio, change_24h
            )
            return True, bonus
        
        return False, 0.0

    def _calculate_quality_score(
        self,
        symbol: str,
        df_1h: pd.DataFrame,
        cand: Dict[str, Any]
    ) -> tuple[float, Dict[str, Any]]:
        """
        ATR-normalized kalite skoru hesapla.
        
        Returns:
            (total_score, breakdown_dict)
        """
        breakdown = {}
        
        # ── 1. HACİM SKORU ────────────────────────────────────
        vol_now = df_1h['volume'].iloc[-1]
        vol_avg = df_1h['volume'].tail(24).mean()
        vol_ratio = vol_now / vol_avg if vol_avg > 0 else 1.0
        
        vol_score_cap = self.params.max_volume_score_cap
        vol_score = min(vol_ratio, vol_score_cap) * self.params.volume_score_multiplier
        breakdown['volume_score'] = vol_score
        breakdown['volume_ratio'] = vol_ratio
        
        # ── 2. MOMENTUM SKORLARI ──────────────────────────────
        if self.params.atr_normalization.enabled:
            # ATR-normalized momentum kullan
            atr_score, atr_multiple = self._calculate_atr_normalized_momentum(
                symbol, df_1h.tail(self.params.atr_normalization.lookback_days + 5)
            )
            
            # 24h ATR skoru
            momentum_24h_score = atr_score
            breakdown['atr_multiple_24h'] = atr_multiple
            breakdown['momentum_24h_score'] = momentum_24h_score
            
            # 1h momentum (basit %, ATR gerekmez kısa vadede)
            close_now = df_1h['close'].iloc[-1]
            close_prev = df_1h['close'].iloc[-2] if len(df_1h) >= 2 else df_1h['close'].iloc[0]
            change_1h = ((close_now - close_prev) / close_prev) * 100

            momentum_1h_score = self._get_momentum_score(
                change_1h, 
                self.params.momentum_1h_thresholds
            )
            breakdown['change_1h'] = change_1h
            breakdown['momentum_1h_score'] = momentum_1h_score
        else:
            # Basit % bazlı skor (eski yöntem)
            change_24h = cand['change_24h']
            momentum_24h_score = self._get_momentum_score(
                change_24h,
                self.params.momentum_24h_thresholds
            )
            breakdown['momentum_24h_score'] = momentum_24h_score
            
            close_now = df_1h['close'].iloc[-1]
            close_prev = df_1h['close'].iloc[-4] if len(df_1h) >= 4 else df_1h['close'].iloc[0]
            change_1h = ((close_now - close_prev) / close_prev) * 100
            
            momentum_1h_score = self._get_momentum_score(
                change_1h,
                self.params.momentum_1h_thresholds
            )
            breakdown['change_1h'] = change_1h
            breakdown['momentum_1h_score'] = momentum_1h_score
        
        # ── 3. SESSİZ BİRİKİM BONUSU ─────────────────────────
        silent_detected, silent_bonus = self._detect_silent_accumulation(
            symbol,
            vol_ratio,
            cand['change_24h']
        )
        breakdown['silent_accumulation'] = silent_detected
        breakdown['silent_bonus'] = silent_bonus
        
        # ── 4. TOPLAM SKOR (Ağırlıklı) ───────────────────────
        weights = self.params.scoring_weights
        
        total_score = (
            vol_score * weights.volume_weight +
            momentum_1h_score * weights.momentum_1h_weight +
            momentum_24h_score * weights.momentum_24h_weight +
            silent_bonus
        )
        
        breakdown['total_score'] = total_score
        
        return total_score, breakdown

    def get_candidates(self) -> List[Dict]:
        """
        Piyasayı tarayıp kriterlere uyan adayları döndürür.
        
        Returns:
            Kalite skoruna göre sıralı aday listesi
        """
        logger.info("Piyasa taraması başlatılıyor (Early Momentum stratejisi)...")
        tickers = self.client.fetch_tickers()
        
        if not tickers:
            logger.error("Ticker verisi alınamadı!")
            return []

        initial_candidates = []
        quote_asset = self.params.quote_asset

        # ── AŞAMA 1: 24h Ticker Filtreleme ───────────────────
        for symbol, data in tickers.items():
            if not symbol.endswith(f"/{quote_asset}"):
                continue

            base_asset = symbol.split('/')[0]
            if any(ex in base_asset for ex in self.EXCLUDED_SYMBOLS):
                continue
            if any(base_asset.endswith(suf) for suf in self.EXCLUDED_SUFFIXES):
                continue

            volume_usdt = float(data.get('quoteVolume', 0) or 0)
            if volume_usdt < self.params.min_volume_24h_usdt:
                continue

            change_pct = float(data.get('percentage', 0) or 0)
            
            # Alt sınır
            if change_pct < self.params.min_price_change_24h_pct:
                continue
            
            # Üst sınır (geç kalma önleme)
            if change_pct > self.params.max_price_change_24h_pct:
                logger.debug("%s elendi: %.2f%% artış aşırı (max %.1f%%)", 
                           symbol, change_pct, self.params.max_price_change_24h_pct)
                continue

            initial_candidates.append({
                "symbol": symbol,
                "price": float(data.get('last', 0) or 0),
                "change_24h": change_pct,
                "volume_24h": volume_usdt,
            })

        # Hacme göre sırala ve en iyi N'yi al
        initial_candidates = sorted(
            initial_candidates, 
            key=lambda x: x['volume_24h'], 
            reverse=True
        )
        top_candidates = initial_candidates[:self.params.max_initial_candidates]
        
        logger.info(
            "Aşama 1 tamamlandı: %d aday bulundu. Top %d işleniyor.",
            len(initial_candidates), 
            len(top_candidates)
        )

        # ── AŞAMA 2: 1h Veri ile Kalite Skoru ────────────────
        final_candidates = []
        for cand in top_candidates:
            try:
                df_1h = self.client.fetch_ohlcv(
                    cand['symbol'], 
                    timeframe="1h", 
                    days=2
                )
                
                if df_1h.empty or len(df_1h) < 12:
                    continue

                # Kalite skoru hesapla (ATR-normalized)
                score, breakdown = self._calculate_quality_score(
                    cand['symbol'],
                    df_1h,
                    cand
                )
                
                # Tüm metrikleri güncelle
                cand.update({
                    "quality_score": score,
                    "quality_breakdown": breakdown,
                    "volume_ratio_1h": breakdown.get('volume_ratio', 1.0),
                    "change_1h": breakdown.get('change_1h', 0.0),
                    "atr_multiple": breakdown.get('atr_multiple_24h', 0.0),
                    "silent_accumulation": breakdown.get('silent_accumulation', False),
                    "momentum_stage": (
                        "early" if 2.0 <= cand['change_24h'] <= 5.0 
                        else "mid" if 5.0 < cand['change_24h'] <= 8.0 
                        else "late"
                    ),
                })
                
                # Skor alt sınırı kontrolü
                if score >= self.params.min_quality_score_threshold:
                    final_candidates.append(cand)
                    
            except Exception as e:
                logger.warning("Aday analizi hatası (%s): %s", cand['symbol'], e)

        # Skora göre sırala
        final_candidates = sorted(
            final_candidates, 
            key=lambda x: x['quality_score'], 
            reverse=True
        )
        results = final_candidates[:self.params.max_scout_recommendations]
        
        logger.info(
            "Tarama tamamlandı: %d nihai aday (min skor: %.1f)",
            len(results),
            self.params.min_quality_score_threshold
        )
        
        # Log sonuçları
        for c in results:
            logger.info(
                "✓ %s: Skor=%.1f (Vol=%.1f, Mom1h=%.1f, Mom24h=%.1f, Silent=%s)",
                c['symbol'],
                c['quality_score'],
                c['quality_breakdown'].get('volume_score', 0),
                c['quality_breakdown'].get('momentum_1h_score', 0),
                c['quality_breakdown'].get('momentum_24h_score', 0),
                "EVET" if c['silent_accumulation'] else "HAYIR"
            )
        
        return results
    
    def should_scan(self, cycle: int, cash_ratio: float = 0.0) -> bool:
        """
        Akıllı zamanlama: Tarama zamanı geldi mi?
        
        Args:
            cycle: Mevcut cycle sayısı
            cash_ratio: Nakit oranı (0.0-1.0)
        
        Returns:
            True eğer tarama zamanı geldi
        """
        # Dinamik tarayıcı kapalıysa
        if not self.params_dict.get('dynamic_scanner_enabled', True):
            return False
        
        # Nakit oranına göre adaptif zamanlama
        min_cash_ratio = self.params_dict.get('min_cash_ratio_for_frequent_scan', 0.50)
        if cash_ratio >= min_cash_ratio:
            # Nakit yüksek, sık tara (3 saat)
            interval = self.params_dict.get('scan_interval_hours_high_cash', 3)
        else:
            # Normal zamanlama (6 saat)
            interval = self.params_dict.get('scan_interval_hours', 6)
        
        # Cycle bazlı kontrol (1 cycle ≈ 1 saat varsayalım)
        cycles_since_scan = cycle - self.last_scan_cycle
        should_scan = cycles_since_scan >= interval
        
        if should_scan:
            logger.debug(
                "🔍 Tarama zamanı (cycle: %d, son tarama: %d, interval: %d)",
                cycle, self.last_scan_cycle, interval
            )
        
        return should_scan
    
    def mark_scan_complete(self, cycle: int) -> None:
        """Tarama tamamlandı olarak işaretle."""
        self.last_scan_cycle = cycle
        logger.debug("✅ Tarama tamamlandı, bir sonraki: cycle %d", cycle + self.scan_interval_hours)
    
    def get_top_gainers_and_volume_spikes(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Dinamik tarayıcı: Hacim spike'ı ve yükselen varlıkları keşfet.
        
        Kriterler:
        - 24h hacim > $1M (likidite)
        - Hacim artışı > 2x (ilgi spike'ı)
        - Fiyat artışı 2-8% (erken momentum, geç kalınmamış)
        - [DINAMIK_KEŞIF] flag'i ile işaretle
        
        Args:
            limit: Döndürülecek maksimum sembol
        
        Returns:
            Hacim spike'ı olan varlık listesi
        """
        logger.info("🔍 Dinamik tarayıcı çalışıyor (hacim spike'ı + gainers)...")
        
        tickers = self.client.fetch_tickers()
        
        if not tickers:
            logger.warning("Ticker verisi alınamadı, dinamik tarama atlandı")
            return []
        
        candidates = []
        quote_asset = self.params.quote_asset
        
        for symbol, data in tickers.items():
            if not symbol.endswith(f"/{quote_asset}"):
                continue
            
            base_asset = symbol.split('/')[0]
            if any(ex in base_asset for ex in self.EXCLUDED_SYMBOLS):
                continue
            if any(base_asset.endswith(suf) for suf in self.EXCLUDED_SUFFIXES):
                continue
            
            # 24h hacim kontrolü
            volume_usdt = float(data.get('quoteVolume', 0) or 0)
            if volume_usdt < self.params.min_volume_24h_usdt:
                continue
            
            # Fiyat değişimi
            change_pct = float(data.get('percentage', 0) or 0)
            
            # Erken momentum: 2-8% arası
            if not (self.params.min_price_change_24h_pct <= change_pct <= self.params.max_price_change_24h_pct):
                continue
            
            avg_volume_usdt = self._get_average_daily_volume_usdt(symbol)
            volume_ratio = volume_usdt / avg_volume_usdt if avg_volume_usdt > 0 else 0.0
            
            # Hacim spike'ı: 2x+ ortalama
            if volume_ratio < 2.0:
                continue
            
            candidates.append({
                "symbol": symbol,
                "price": float(data.get('last', 0) or 0),
                "change_24h": change_pct,
                "volume_24h": volume_usdt,
                "avg_volume_7d": avg_volume_usdt,
                "volume_ratio": volume_ratio,
                "quality_score": volume_ratio * 10 + change_pct,  # Basit skor
                "dynamic_discovery": True,  # [DINAMIK_KEŞIF] flag
                "discovery_reason": f"Hacim spike: {volume_ratio:.1f}x, Fiyat: +{change_pct:.1f}%",
            })
        
        # Hacim spike'ına göre sırala
        candidates = sorted(
            candidates,
            key=lambda x: x['volume_ratio'],
            reverse=True
        )
        
        results = candidates[:limit]
        
        logger.info(
            "✅ Dinamik tarama tamamlandı: %d sembol bulundu (hacim spike'ı)",
            len(results)
        )
        
        for c in results:
            logger.info(
                "🚀 [DINAMIK_KEŞIF] %s: Hacim %.1fx, Fiyat +%.1f%%",
                c['symbol'],
                c['volume_ratio'],
                c['change_24h']
            )
        
        return results


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    scanner = MarketScanner()
    res = scanner.get_candidates()
    
    print("\n" + "="*70)
    print("EARLY MOMENTUM TARAYICI SONUÇLARI")
    print("="*70)
    
    for c in res:
        print(f"\n{c['symbol']}:")
        print(f"  Kalite Skoru: {c['quality_score']:.1f}")
        print(f"  24h Değişim: %{c['change_24h']:.2f} ({c['momentum_stage']})")
        print(f"  1h Değişim: %{c['change_1h']:.2f}")
        print(f"  Hacim Artışı: {c['volume_ratio_1h']:.2f}x")
        print(f"  ATR Katı: {c['atr_multiple']:.2f}x")
        print(f"  Sessiz Birikim: {'✓' if c['silent_accumulation'] else '✗'}")
