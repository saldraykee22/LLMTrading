"""
Watchdog — Flash Crash Protection
===================================
Monitors symbols for flash crash conditions and can halt trading
or close positions when extreme price movements are detected.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from config.settings import get_trading_params
from data.market_data import MarketDataClient
from risk.portfolio import PortfolioState

logger = logging.getLogger(__name__)


class Watchdog:
    """Flash crash watchdog that monitors symbols in a background thread."""

    def __init__(
        self,
        symbols: list[str],
        portfolio: PortfolioState,
        exchange_client=None,
        crash_threshold_pct: float = 5.0,
        check_interval_sec: int = 30,
    ) -> None:
        self.symbols = symbols
        self.portfolio = portfolio
        self.exchange_client = exchange_client
        self.crash_threshold_pct = crash_threshold_pct
        self.check_interval_sec = check_interval_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._market_client = MarketDataClient()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts the watchdog background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Watchdog started for symbols: %s", self.symbols)

    def stop(self) -> None:
        """Signals the watchdog thread to stop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("Watchdog stopped")

    def _run(self) -> None:
        """Main monitoring loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                self._check_symbols()
            except Exception as e:
                logger.error("Watchdog check failed: %s", e)
            self._stop_event.wait(self.check_interval_sec)

    def _check_symbols(self) -> None:
        """Checks all symbols for flash crash conditions."""
        for symbol in self.symbols:
            try:
                df = self._market_client.fetch_ohlcv(symbol, days=1)
                if df.empty or len(df) < 2:
                    continue

                current_price = float(df["close"].iloc[-1])
                prev_price = float(df["close"].iloc[-2])

                if prev_price <= 0:
                    continue

                drop_pct = (prev_price - current_price) / prev_price * 100

                if drop_pct >= self.crash_threshold_pct:
                    logger.critical(
                        "FLASH CRASH DETECTED: %s dropped %.2f%% (%.4f -> %.4f)",
                        symbol,
                        drop_pct,
                        prev_price,
                        current_price,
                    )
                    self._handle_crash(symbol, current_price, drop_pct)

            except Exception as e:
                logger.warning("Watchdog check failed for %s: %s", symbol, e)

    def _handle_crash(self, symbol: str, price: float, drop_pct: float) -> None:
        """Handles a detected flash crash for a symbol."""
        with self._lock:
            pos = next(
                (p for p in self.portfolio.positions if p.symbol == symbol), None
            )
            if pos and self.exchange_client:
                from execution.order_manager import TradeOrder

                order = TradeOrder(
                    symbol=symbol,
                    action="sell",
                    order_type="market",
                    amount=pos.amount,
                )
                try:
                    result = self.exchange_client.execute_order(order, price)
                    if result.get("status") in ("filled", "closed", "open"):
                        self.portfolio.close_position(
                            symbol, float(result.get("price") or price)
                        )
                        logger.warning(
                            "Emergency sell executed for %s due to flash crash (%.2f%% drop)",
                            symbol,
                            drop_pct,
                        )
                except Exception as e:
                    logger.error("Emergency sell failed for %s: %s", symbol, e)

    def get_status(self) -> dict:
        """Returns watchdog status."""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "symbols": self.symbols,
            "crash_threshold_pct": self.crash_threshold_pct,
            "check_interval_sec": self.check_interval_sec,
        }
