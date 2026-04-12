"""
Paper Trading Engine
=====================
Gerçek borsaya emir göndermeden, simüle edilmiş alım-satım yapar.
- Slippage ve komisyon uygular
- Gerçek bakiye ve pozisyon takibi yapar
- Live modda gerçek borsaya, paper modda bu engine'e yönlendirilir
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.settings import get_trading_params
from execution.order_manager import TradeOrder

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    """Paper trading pozisyonu."""

    symbol: str
    entry_price: float
    amount: float
    entry_time: str
    side: str = "buy"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    current_price: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.amount

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price * self.amount == 0:
            return 0.0
        return self.unrealized_pnl / (self.entry_price * self.amount)


class PaperTradingEngine:
    """
    Simüle edilmiş alım-satım motoru.

    Gerçek borsaya bağlanmadan, piyasa fiyatından slippage ve komisyon
    uygulayarak emirleri simüle eder.
    """

    def __init__(
        self,
        initial_cash: float = 10000.0,
        slippage_pct: float = 0.001,
        commission_pct: float = 0.001,
    ) -> None:
        self._params = get_trading_params()
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[dict[str, Any]] = []
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.max_equity = initial_cash
        self.current_drawdown = 0.0

    @property
    def equity(self) -> float:
        """Toplam özvarlık (nakit + pozisyonlar)."""
        position_value = sum(
            p.current_price * p.amount for p in self.positions.values()
        )
        return self.cash + position_value

    def update_drawdown(self) -> None:
        eq = self.equity
        if eq > self.max_equity:
            self.max_equity = eq
        if self.max_equity > 0:
            self.current_drawdown = (self.max_equity - eq) / self.max_equity

    def execute_order(
        self,
        order: TradeOrder,
        current_price: float,
    ) -> dict[str, Any]:
        """
        Emri simüle eder.

        Args:
            order: Alım-satım emri
            current_price: Güncel piyasa fiyatı

        Returns:
            Simülasyon sonucu
        """
        if order.action == "buy":
            return self._execute_buy(order, current_price)
        elif order.action == "sell":
            return self._execute_sell(order, current_price)
        else:
            return {"status": "error", "message": f"Geçersiz aksiyon: {order.action}"}

    def _execute_buy(self, order: TradeOrder, current_price: float) -> dict[str, Any]:
        """Alım emrini simüle eder."""
        # Slippage uygula (alım fiyatı biraz daha yüksek)
        exec_price = current_price * (1 + self.slippage_pct)

        # Komisyon
        cost = exec_price * order.amount
        commission = cost * self.commission_pct
        total_cost = cost + commission

        # Bakiye kontrolü
        if total_cost > self.cash:
            logger.warning(
                "Paper: Yetersiz bakiye — gerekli: %.2f, mevcut: %.2f",
                total_cost,
                self.cash,
            )
            return {
                "status": "rejected",
                "message": f"Yetersiz bakiye (paper): {total_cost:.2f} > {self.cash:.2f}",
                "symbol": order.symbol,
                "side": "buy",
            }

        # Pozisyon aç/güncelle
        if order.symbol in self.positions:
            pos = self.positions[order.symbol]
            # Ortalama fiyat güncelle
            total_amount = pos.amount + order.amount
            pos.entry_price = (
                pos.entry_price * pos.amount + exec_price * order.amount
            ) / total_amount
            pos.amount = total_amount
        else:
            pos = PaperPosition(
                symbol=order.symbol,
                side="buy",
                entry_price=exec_price,
                amount=order.amount,
                entry_time=datetime.now(timezone.utc).isoformat(),
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                current_price=exec_price,
            )
            self.positions[order.symbol] = pos

        self.cash -= total_cost

        trade_record = {
            "status": "filled",
            "order_id": f"paper_{len(self.trades):06d}",
            "symbol": order.symbol,
            "side": "buy",
            "type": order.order_type,
            "amount": order.amount,
            "price": round(exec_price, 6),
            "commission": round(commission, 6),
            "cost": round(total_cost, 6),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "paper",
        }
        self.trades.append(trade_record)

        logger.info(
            "Paper BUY: %s %.6f @ %.4f (slippage: %.2f%%, komisyon: %.4f)",
            order.symbol,
            order.amount,
            exec_price,
            self.slippage_pct * 100,
            commission,
        )
        return trade_record

    def _execute_sell(self, order: TradeOrder, current_price: float) -> dict[str, Any]:
        """Satım emrini simüle eder."""
        if order.symbol not in self.positions:
            logger.warning("Paper: Satılacak pozisyon yok: %s", order.symbol)
            return {
                "status": "rejected",
                "message": f"Satılacak pozisyon yok (paper): {order.symbol}",
                "symbol": order.symbol,
                "side": "sell",
            }

        pos = self.positions[order.symbol]

        # Slippage uygula (satım fiyatı biraz daha düşük)
        exec_price = current_price * (1 - self.slippage_pct)

        # Satılacak miktar kontrolü
        sell_amount = min(order.amount, pos.amount)
        revenue = exec_price * sell_amount
        commission = revenue * self.commission_pct
        net_revenue = revenue - commission

        # P&L hesapla
        avg_cost = pos.entry_price * sell_amount
        pnl = (exec_price - pos.entry_price) * sell_amount - commission

        # Pozisyon güncelle
        pos.amount -= sell_amount
        pos.current_price = exec_price

        if pos.amount <= 0.000001:
            del self.positions[order.symbol]

        self.cash += net_revenue
        self.total_pnl += pnl
        self.daily_pnl += pnl
        self.update_drawdown()

        trade_record = {
            "status": "filled",
            "order_id": f"paper_{len(self.trades):06d}",
            "symbol": order.symbol,
            "side": "sell",
            "type": order.order_type,
            "amount": sell_amount,
            "price": round(exec_price, 6),
            "commission": round(commission, 6),
            "revenue": round(net_revenue, 6),
            "pnl": round(pnl, 6),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "paper",
        }
        self.trades.append(trade_record)

        logger.info(
            "Paper SELL: %s %.6f @ %.4f (P&L: %.4f)",
            order.symbol,
            sell_amount,
            exec_price,
            pnl,
        )
        return trade_record

    def check_stop_loss_take_profit(
        self, symbol: str, current_price: float
    ) -> dict | None:
        """
        Pozisyonun stop-loss veya take-profit seviyesine ulaşıp ulaşmadığını kontrol eder.

        Returns:
            Tetiklenen emir bilgisi veya None
        """
        pos = self.positions.get(symbol)
        if not pos:
            return None

        pos.current_price = current_price

        # Stop-loss kontrolü
        if pos.stop_loss > 0:
            if current_price <= pos.stop_loss:
                logger.warning(
                    "Paper STOP-LOSS tetiklendi: %s @ %.4f (stop: %.4f)",
                    symbol,
                    current_price,
                    pos.stop_loss,
                )
                return self._create_auto_sell_order(pos, "stop_loss")

        # Take-profit kontrolü
        if pos.take_profit > 0:
            if current_price >= pos.take_profit:
                logger.info(
                    "Paper TAKE-PROFIT tetiklendi: %s @ %.4f (tp: %.4f)",
                    symbol,
                    current_price,
                    pos.take_profit,
                )
                return self._create_auto_sell_order(pos, "take_profit")

        return None

    def _create_auto_sell_order(self, pos: PaperPosition, reason: str) -> dict:
        """Otomatik satım emri oluşturur ve çalıştırır.

        Slippage uygulanmaz çünkü fiyat zaten tetiklenen fiyattır.
        """
        pos_amount = pos.amount
        pos_price = pos.current_price

        # Slippage-free execution — price is already the trigger price
        exec_price = pos_price
        revenue = exec_price * pos_amount
        commission = revenue * self.commission_pct
        net_revenue = revenue - commission

        pnl = (exec_price - pos.entry_price) * pos_amount - commission

        pos.amount = 0
        del self.positions[pos.symbol]

        self.cash += net_revenue
        self.total_pnl += pnl
        self.daily_pnl += pnl
        self.update_drawdown()

        trade_record = {
            "status": "filled",
            "order_id": f"paper_{len(self.trades):06d}",
            "symbol": pos.symbol,
            "side": "sell",
            "type": "market",
            "amount": pos_amount,
            "price": round(exec_price, 6),
            "commission": round(commission, 6),
            "revenue": round(net_revenue, 6),
            "pnl": round(pnl, 6),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "paper",
            "exit_reason": reason,
        }
        self.trades.append(trade_record)

        logger.info(
            "Paper AUTO-SELL (%s): %s %.6f @ %.4f (P&L: %.4f)",
            reason,
            pos.symbol,
            pos_amount,
            exec_price,
            pnl,
        )
        return trade_record

    def get_status(self) -> dict[str, Any]:
        """Paper trading durumu."""
        return {
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.positions),
            "total_trades": len(self.trades),
            "max_equity": round(self.max_equity, 2),
            "current_drawdown": round(self.current_drawdown, 4),
            "positions": {
                sym: {
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "amount": p.amount,
                    "current_price": p.current_price,
                    "unrealized_pnl": round(p.unrealized_pnl, 4),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 4),
                }
                for sym, p in self.positions.items()
            },
        }
