"""
Portföy Yönetimi Modülü
=========================
Pozisyon boyutlandırma, portföy takibi ve P&L hesaplama.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.settings import get_trading_params

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Tek bir açık pozisyon."""
    symbol: str
    side: str               # long | short
    entry_price: float
    amount: float
    entry_time: str
    stop_loss: float = 0.0
    take_profit: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    def update_price(self, price: float) -> None:
        """Güncel fiyatı günceller ve P&L hesaplar."""
        self.current_price = price
        if self.side == "long":
            self.unrealized_pnl = (price - self.entry_price) * self.amount
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.amount
        if self.entry_price > 0:
            self.unrealized_pnl_pct = self.unrealized_pnl / (self.entry_price * self.amount)

    def should_stop_loss(self, price: float) -> bool:
        """Stop-loss kontrolü."""
        if self.stop_loss <= 0:
            return False
        if self.side == "long":
            return price <= self.stop_loss
        return price >= self.stop_loss

    def should_take_profit(self, price: float) -> bool:
        """Take-profit kontrolü."""
        if self.take_profit <= 0:
            return False
        if self.side == "long":
            return price >= self.take_profit
        return price <= self.take_profit


@dataclass
class PortfolioState:
    """Portföy durumu."""
    initial_cash: float = 10000.0
    cash: float = 10000.0
    positions: list[Position] = field(default_factory=list)
    closed_trades: list[dict] = field(default_factory=list)
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    max_equity: float = 10000.0
    current_drawdown: float = 0.0

    @property
    def equity(self) -> float:
        """Toplam özvarlık (nakit + açık pozisyonlar)."""
        position_value = sum(
            p.current_price * p.amount for p in self.positions
        )
        return self.cash + position_value

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def update_drawdown(self) -> None:
        """Drawdown günceller."""
        eq = self.equity
        if eq > self.max_equity:
            self.max_equity = eq
        if self.max_equity > 0:
            self.current_drawdown = (self.max_equity - eq) / self.max_equity

    def calculate_position_size(
        self,
        price: float,
        risk_per_trade: float | None = None,
    ) -> float:
        """
        Pozisyon boyutunu hesaplar.

        Args:
            price: Giriş fiyatı
            risk_per_trade: İşlem başına risk oranı (varsayılan: YAML'den)

        Returns:
            Alınabilecek miktar (amount)
        """
        params = get_trading_params()
        risk_pct = risk_per_trade or params.risk.max_position_pct
        max_value = self.equity * risk_pct

        if price <= 0:
            return 0.0

        return max_value / price

    def to_dict(self) -> dict[str, Any]:
        """Serileştirme (ajan state'e gönderim için)."""
        return {
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "open_positions": self.open_position_count,
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "current_drawdown": round(self.current_drawdown, 4),
            "max_equity": round(self.max_equity, 2),
            "positions": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "amount": p.amount,
                    "unrealized_pnl": round(p.unrealized_pnl, 4),
                }
                for p in self.positions
            ],
        }

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> Position | None:
        """Yeni pozisyon açar."""
        params = get_trading_params()

        # Limit kontrolü
        if self.open_position_count >= params.risk.max_open_positions:
            logger.warning("Max pozisyon limiti aşıldı")
            return None

        cost = price * amount
        if cost > self.cash:
            logger.warning("Yetersiz bakiye: %.2f > %.2f", cost, self.cash)
            return None

        # Drawdown kontrolü
        self.update_drawdown()
        if self.current_drawdown >= params.risk.max_drawdown_pct:
            logger.warning("Max drawdown aşıldı: %.2f%%", self.current_drawdown * 100)
            return None

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            amount=amount,
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=price,
        )

        self.cash -= cost
        self.positions.append(position)

        logger.info(
            "Pozisyon açıldı: %s %s %.4f @ %.4f (SL: %.4f, TP: %.4f)",
            side.upper(), symbol, amount, price, stop_loss, take_profit,
        )
        return position

    def close_position(self, symbol: str, price: float) -> dict | None:
        """Pozisyonu kapatır."""
        pos = next((p for p in self.positions if p.symbol == symbol), None)
        if not pos:
            logger.warning("Kapatılacak pozisyon bulunamadı: %s", symbol)
            return None

        pos.update_price(price)
        pnl = pos.unrealized_pnl

        self.cash += price * pos.amount
        self.total_pnl += pnl
        self.daily_pnl += pnl
        self.positions.remove(pos)

        trade_record = {
            "symbol": symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": price,
            "amount": pos.amount,
            "pnl": round(pnl, 4),
            "pnl_pct": round(pos.unrealized_pnl_pct, 4),
            "entry_time": pos.entry_time,
            "exit_time": datetime.now(timezone.utc).isoformat(),
        }
        self.closed_trades.append(trade_record)

        logger.info(
            "Pozisyon kapatıldı: %s P&L: %.4f (%.2f%%)",
            symbol, pnl, pos.unrealized_pnl_pct * 100,
        )
        self.update_drawdown()
        return trade_record
