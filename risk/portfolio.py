"""
Portföy Yönetimi Modülü
=========================
Pozisyon boyutlandırma, portföy takibi ve P&L hesaplama.
JSON tabanlı kalıcılık (persistence) desteği ile bot restart sonrası
pozisyonlar, P&L ve drawdown bilgisi korunur.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import DATA_DIR, get_trading_params

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = DATA_DIR / "portfolio_state.json"
_portfolio_lock = threading.Lock()


@dataclass
class Position:
    """Tek bir açık pozisyon."""

    symbol: str
    entry_price: float
    amount: float
    entry_time: str
    side: str = "long"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.side != "long":
            raise ValueError(f"SPOT only supports long positions, got: {self.side}")

    def update_price(self, price: float) -> None:
        """Güncel fiyatı günceller ve P&L hesaplar."""
        self.current_price = price
        self.unrealized_pnl = (price - self.entry_price) * self.amount
        if self.entry_price > 0 and self.amount > 0:
            self.unrealized_pnl_pct = self.unrealized_pnl / (
                self.entry_price * self.amount
            )

    def should_stop_loss(self, price: float) -> bool:
        """Stop-loss kontrolü."""
        if self.stop_loss <= 0:
            return False
        return price <= self.stop_loss

    def should_take_profit(self, price: float) -> bool:
        """Take-profit kontrolü."""
        if self.take_profit <= 0:
            return False
        return price >= self.take_profit


def _position_from_dict(d: dict) -> Position:
    """Dict'ten Position oluşturur."""
    return Position(
        symbol=d["symbol"],
        side=d["side"],
        entry_price=d["entry_price"],
        amount=d["amount"],
        entry_time=d["entry_time"],
        stop_loss=d.get("stop_loss", 0.0),
        take_profit=d.get("take_profit", 0.0),
        current_price=d.get("current_price", 0.0),
        unrealized_pnl=d.get("unrealized_pnl", 0.0),
        unrealized_pnl_pct=d.get("unrealized_pnl_pct", 0.0),
    )


@dataclass
class PortfolioState:
    """Portföy durumu."""

    initial_cash: float = 10000.0
    cash: float = 10000.0
    positions: list[Position] = field(default_factory=list)
    closed_trades: list[dict] = field(default_factory=list)
    daily_pnl: float = 0.0
    daily_pnl_date: str = ""
    total_pnl: float = 0.0
    max_equity: float = 10000.0
    current_drawdown: float = 0.0
    benchmark_symbol: str = "BTC/USDT"
    benchmark_return: float = 0.0
    alpha: float = 0.0

    def __post_init__(self) -> None:
        """daily_pnl_date boşsa bugünün tarihini ata."""
        if not self.daily_pnl_date:
            self.daily_pnl_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Persistence ────────────────────────────────────────

    def save_to_file(self, path: Path | None = None) -> None:
        """Portföy durumunu JSON dosyasına kaydet."""
        with _portfolio_lock:
            filepath = path or PORTFOLIO_FILE
            filepath.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "initial_cash": self.initial_cash,
                "cash": self.cash,
                "positions": [asdict(p) for p in self.positions],
                "closed_trades": self.closed_trades,
                "daily_pnl": self.daily_pnl,
                "daily_pnl_date": self.daily_pnl_date,
                "total_pnl": self.total_pnl,
                "max_equity": self.max_equity,
                "current_drawdown": self.current_drawdown,
                "benchmark_symbol": self.benchmark_symbol,
                "benchmark_return": self.benchmark_return,
                "alpha": self.alpha,
            }
            tmp_path = filepath.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            tmp_path.replace(filepath)
            logger.info("Portföy kaydedildi: %s (equity: %.2f)", filepath, self.equity)

    @classmethod
    def load_from_file(cls, path: Path | None = None) -> "PortfolioState":
        """JSON dosyasından portföy durumunu yükle."""
        filepath = path or PORTFOLIO_FILE
        if not filepath.exists():
            logger.info("Portföy dosyası bulunamadı, yeni portföy oluşturuluyor")
            return cls()

        try:
            with _portfolio_lock:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                positions = [_position_from_dict(p) for p in data.get("positions", [])]
                state = cls(
                    initial_cash=data.get("initial_cash", 10000.0),
                    cash=data.get("cash", 10000.0),
                    positions=positions,
                    closed_trades=data.get("closed_trades", []),
                    daily_pnl=data.get("daily_pnl", 0.0),
                    daily_pnl_date=data.get("daily_pnl_date", ""),
                    total_pnl=data.get("total_pnl", 0.0),
                    max_equity=data.get("max_equity", 10000.0),
                    current_drawdown=data.get("current_drawdown", 0.0),
                    benchmark_symbol=data.get("benchmark_symbol", "BTC/USDT"),
                    benchmark_return=data.get("benchmark_return", 0.0),
                    alpha=data.get("alpha", 0.0),
                )
                state.reset_daily_pnl_if_needed()
                logger.info(
                    "Portföy yüklendi: %s pozisyon, equity=%.2f, daily_pnl=%.2f",
                    len(positions),
                    state.equity,
                    state.daily_pnl,
                )
                return state
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Portföy dosyası okunamadı, yeni portföy oluşturuluyor: %s", e)
            return cls()

    # ── Daily PnL Reset ────────────────────────────────────

    def reset_daily_pnl_if_needed(self) -> bool:
        """Gün değişmişse günlük P&L'i sıfırlar. Değişiklik varsa True döner."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_pnl_date != today:
            logger.info(
                "Günlük P&L sıfırlandı (%s → %s), önceki: %.2f",
                self.daily_pnl_date,
                today,
                self.daily_pnl,
            )
            self.daily_pnl = 0.0
            self.daily_pnl_date = today
            return True
        return False

    # ── Equity & Drawdown ──────────────────────────────────

    @property
    def equity(self) -> float:
        """Toplam özvarlık (nakit + açık pozisyonlar)."""
        position_value = sum(p.current_price * p.amount for p in self.positions)
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

    def update_benchmark(
        self, market_data: pd.DataFrame, benchmark_symbol: str | None = None
    ) -> float:
        """Benchmark getirisini ve alpha'yı hesaplar."""
        sym = benchmark_symbol or self.benchmark_symbol
        if sym != self.benchmark_symbol:
            self.benchmark_symbol = sym
        if (
            market_data is None
            or market_data.empty
            or "close" not in market_data.columns
        ):
            return 0.0
        first_close = float(market_data["close"].iloc[0])
        last_close = float(market_data["close"].iloc[-1])
        if first_close <= 0:
            return 0.0
        self.benchmark_return = (last_close - first_close) / first_close
        portfolio_return = (
            (self.equity - self.initial_cash) / self.initial_cash
            if self.initial_cash > 0
            else 0.0
        )
        self.alpha = portfolio_return - self.benchmark_return
        return self.benchmark_return

    # ── Position Sizing ────────────────────────────────────

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
        max_value = self.cash * risk_pct

        if price <= 0:
            return 0.0

        return max_value / price

    # ── Serialization ──────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serileştirme (ajan state'e gönderim için)."""
        return {
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "open_positions": self.open_position_count,
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_date": self.daily_pnl_date,
            "current_drawdown": round(self.current_drawdown, 4),
            "max_equity": round(self.max_equity, 2),
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_return": round(self.benchmark_return, 4),
            "alpha": round(self.alpha, 4),
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

    # ── Position Management ────────────────────────────────

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        max_correlation: float | None = None,
        market_data: dict[str, Any] | None = None,
    ) -> Position | None:
        """Yeni pozisyon açar. Thread-safe."""
        with _portfolio_lock:
            if side != "long":
                raise ValueError(f"SPOT only supports long positions, got: {side}")
            params = get_trading_params()

            if self.open_position_count >= params.risk.max_open_positions:
                logger.warning("Max pozisyon limiti aşıldı")
                return None

            cost = price * amount
            if cost > self.cash:
                logger.warning("Yetersiz bakiye: %.2f > %.2f", cost, self.cash)
                return None

            self.update_drawdown()
            if self.current_drawdown >= params.risk.max_drawdown_pct:
                logger.warning(
                    "Max drawdown aşıldı: %.2f%%", self.current_drawdown * 100
                )
                return None

            if (
                max_correlation is not None
                and market_data is not None
                and self.positions
            ):
                # Market data'nın thread-safe kopyasını al
                market_data_copy = {
                    k: v.copy() if isinstance(v, pd.DataFrame) else v
                    for k, v in market_data.items()
                }

                from risk.correlation_checker import CorrelationChecker

                checker = CorrelationChecker([], market_data_copy)
                symbols_to_check = [p.symbol for p in self.positions] + [symbol]
                available = {
                    s: market_data_copy[s] for s in symbols_to_check if s in market_data_copy
                }
                if len(available) >= 2:
                    check_result = checker.check_positions(
                        self.positions,
                        market_data_copy,
                        max_correlation=max_correlation,
                    )
                    if not check_result["is_safe"]:
                        logger.warning(
                            "Pozisyon reddedildi: yüksek korelasyon tespit edildi. %s",
                            check_result["correlated_pairs"],
                        )
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
                side.upper(),
                symbol,
                amount,
                price,
                stop_loss,
                take_profit,
            )
            return position

    def close_position(self, symbol: str, price: float) -> dict | None:
        """Pozisyonu kapatır. Thread-safe."""
        with _portfolio_lock:
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
                symbol,
                pnl,
                pos.unrealized_pnl_pct * 100,
            )
            self.update_drawdown()
            return trade_record
