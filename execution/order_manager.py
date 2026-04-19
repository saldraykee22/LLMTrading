"""
Emir Yönetimi Modülü
=====================
LLM kararlarını yapılandırılmış JSON emirlerine dönüştürür
ve borsa istemcisine iletir.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.settings import get_settings, get_trading_params

logger = logging.getLogger(__name__)


@dataclass
class TradeOrder:
    """Yapılandırılmış alım-satım emri (DCA desteği ile)."""

    symbol: str
    action: str  # buy | sell
    order_type: str  # market | limit
    amount: float
    price: float | None = None  # limit emri için
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
    timestamp: str = ""
    # DCA (Kademeli İşlem) alanları
    execution_size_pct: float = 1.0  # 0.0-1.0 arası (1.0 = %100)
    target_size: float = 0.0  # Hedeflenen toplam miktar
    is_dca_tranche: bool = False  # Bu bir DCA kademesi mi?
    tranche_number: int = 0  # Kaçıncı kademe?

    def validate(self) -> tuple[bool, str]:
        """Emrin geçerliliğini kontrol eder."""
        if self.action not in ("buy", "sell"):
            return False, f"Geçersiz aksiyon: {self.action}"
        if self.amount <= 0:
            return False, f"Geçersiz miktar: {self.amount}"
        if self.order_type == "limit" and (self.price is None or self.price <= 0):
            return False, "Limit emri için fiyat gerekli"
        
        # SL/TP Mantık Kontrolü
        ref_price = self.price if self.order_type == "limit" else self.stop_loss
        # Limit emri değilse ve market ise, SL ve TP yine de mantıklı olmalı (entry_price genelde reel fiyattır)
        
        if self.action == "buy":
            if self.stop_loss > 0 and self.price and self.stop_loss >= self.price:
                return False, f"Alış emrinde Stop-Loss ({self.stop_loss}) giriş fiyatından ({self.price}) küçük olmalı"
            if self.take_profit > 0 and self.price and self.take_profit <= self.price:
                return False, f"Alış emrinde Take-Profit ({self.take_profit}) giriş fiyatından ({self.price}) büyük olmalı"
        
        elif self.action == "sell":
            # Satış (Short) bu sistemde şimdilik desteklenmiyor (SPOT focus)
            # Ancak yine de mantığı kuralım
            if self.stop_loss > 0 and self.price and self.stop_loss <= self.price:
                return False, f"Satış emrinde Stop-Loss ({self.stop_loss}) giriş fiyatından ({self.price}) büyük olmalı"
            if self.take_profit > 0 and self.price and self.take_profit >= self.price:
                return False, f"Satış emrinde Take-Profit ({self.take_profit}) giriş fiyatından ({self.price}) küçük olmalı"

        if self.stop_loss <= 0 and self.action == "buy":
            return False, "Alış emri için Stop-Loss tanımlı değil"
            
        return True, "OK"


def parse_trade_decision(
    decision: dict[str, Any],
    current_price: float = 0.0,
    atr_value: float = 0.0,
) -> TradeOrder | None:
    """
    LLM trader kararını TradeOrder'a dönüştürür.
    Stop-loss eksikse ATR bazlı fallback hesaplar.

    Args:
        decision: Trader ajan çıktısı (JSON dict)
        current_price: Güncel fiyat (fallback stop-loss için)
        atr_value: ATR değeri (fallback stop-loss için)

    Returns:
        TradeOrder veya None (hold kararı ise)
    """
    from config.settings import get_trading_params

    action = decision.get("action", "hold")
    if action == "hold":
        logger.info("Trader kararı: BEKLE — emir oluşturulmadı")
        return None

    # Tip dönüşümü — güvenli
    try:
        amount = float(decision.get("amount", 0))
    except (ValueError, TypeError):
        logger.warning("Geçersiz amount değeri: %s", decision.get("amount"))
        return None

    try:
        stop_loss = float(decision.get("stop_loss", 0))
    except (ValueError, TypeError):
        stop_loss = 0.0

    try:
        take_profit = float(decision.get("take_profit", 0))
    except (ValueError, TypeError):
        take_profit = 0.0

    try:
        entry_price = float(decision.get("entry_price", 0)) or None
    except (ValueError, TypeError):
        entry_price = None

    # DCA parametreleri
    try:
        execution_size_pct = float(decision.get("execution_size_pct", 1.0))
        # 0.0-1.0 aralığına sınırla
        execution_size_pct = max(0.0, min(1.0, execution_size_pct))
    except (ValueError, TypeError):
        execution_size_pct = 1.0
    
    try:
        target_size = float(decision.get("target_size", 0))
    except (ValueError, TypeError):
        target_size = 0.0

    # Fallback stop-loss: LLM unutmuşsa ATR bazlı hesapla
    if stop_loss <= 0 and current_price > 0 and atr_value > 0:
        params = get_trading_params()
        mult = params.stop_loss.atr_multiplier
        if action == "buy":
            stop_loss = current_price - (atr_value * mult)
        else:
            stop_loss = current_price + (atr_value * mult)
        stop_loss = max(stop_loss, 0.0)
        logger.info(
            "Fallback stop-loss hesaplandı: %.4f (ATR=%.4f, mult=%.1f)",
            stop_loss,
            atr_value,
            mult,
        )

    # DCA için miktar ayarlaması
    actual_amount = amount
    if execution_size_pct < 1.0 and amount > 0:
        actual_amount = amount * execution_size_pct
        logger.info(
            "DCA boyutlandırması: %.4f * %.2f = %.4f (hedef: %.4f)",
            amount, execution_size_pct, actual_amount, target_size
        )

    order = TradeOrder(
        symbol=decision.get("symbol", ""),
        action=action,
        order_type=decision.get("order_type", "market"),
        amount=actual_amount,
        price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=float(decision.get("confidence", 0)),
        reasoning=decision.get("reasoning", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
        # DCA alanları
        execution_size_pct=execution_size_pct,
        target_size=target_size if target_size > 0 else amount,
        is_dca_tranche=execution_size_pct < 1.0,
        tranche_number=1 if execution_size_pct < 1.0 else 0,
    )

    valid, msg = order.validate()
    if not valid:
        logger.warning("Geçersiz emir: %s", msg)
        return None

    logger.info(
        "Emir oluşturuldu: %s %s %.6f %s @ %s (SL: %.4f, TP: %.4f)",
        order.action.upper(),
        order.symbol,
        order.amount,
        order.order_type,
        order.price or "market",
        order.stop_loss,
        order.take_profit,
    )
    return order
