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
    """Yapılandırılmış alım-satım emri."""

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

    def validate(self) -> tuple[bool, str]:
        """Emrin geçerliliğini kontrol eder."""
        if self.action not in ("buy", "sell"):
            return False, f"Geçersiz aksiyon: {self.action}"
        if self.amount <= 0:
            return False, f"Geçersiz miktar: {self.amount}"
        if self.order_type == "limit" and (self.price is None or self.price <= 0):
            return False, "Limit emri için fiyat gerekli"
        if self.stop_loss <= 0:
            return False, "Stop-loss tanımlı değil"
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

    order = TradeOrder(
        symbol=decision.get("symbol", ""),
        action=action,
        order_type=decision.get("order_type", "market"),
        amount=amount,
        price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=float(decision.get("confidence", 0)),
        reasoning=decision.get("reasoning", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
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
