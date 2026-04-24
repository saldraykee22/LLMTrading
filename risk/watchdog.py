"""
Watchdog — Flash Crash Protection
===================================
Monitors symbols for flash crash conditions and can halt trading
or close positions when extreme price movements are detected.
"""

from __future__ import annotations

import logging
import concurrent.futures
import threading
import time
from datetime import datetime, timezone

from pathlib import Path

from config.settings import DATA_DIR, get_trading_params
from data.market_data import MarketDataClient
from risk.portfolio import PortfolioState
from risk.system_status import SystemStatus

logger = logging.getLogger(__name__)


class Watchdog:
    """Flash crash watchdog that monitors symbols in a background thread."""

    def __init__(
        self,
        symbols: list[str],
        portfolio: PortfolioState | None = None,
        exchange_client=None,
        account_manager=None,
        crash_threshold_pct: float = 5.0,
        check_interval_sec: int = 10,
        heartbeat_timeout_sec: int = 60,
    ) -> None:
        self.symbols = symbols
        self.portfolio = portfolio
        self.exchange_client = exchange_client
        self._account_manager = account_manager
        self.crash_threshold_pct = crash_threshold_pct
        self.check_interval_sec = check_interval_sec
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._market_client = MarketDataClient()
        self._lock = threading.Lock()
        self._last_heartbeat = time.time()
        self._system_status = SystemStatus.get_instance()

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
                self._check_position_sl_tp()
                # Heartbeat güncelle
                self._update_heartbeat()
            except Exception as e:
                logger.error("Watchdog check failed: %s", e)
            self._stop_event.wait(self.check_interval_sec)
    
    def _update_heartbeat(self) -> None:
        """Heartbeat timestamp'ini güncelle."""
        with self._lock:
            self._last_heartbeat = time.time()
    
    def check_heartbeat(self) -> bool:
        """
        Watchdog'un hala çalışıp çalışmadığını kontrol et.
        Main thread'den çağrılır.
        
        Returns:
            True if watchdog is alive, False if timeout
        """
        with self._lock:
            elapsed = time.time() - self._last_heartbeat
        
        if elapsed > self.heartbeat_timeout_sec:
            logger.critical(
                "🚨 WATCHDOG HEARTBEAT TIMEOUT: %.1f seconds (threshold: %d)",
                elapsed,
                self.heartbeat_timeout_sec,
            )
            # SystemStatus'u emergency stop'a al
            self._system_status.emergency_stop(
                f"Watchdog heartbeat timeout ({elapsed:.1f}s > {self.heartbeat_timeout_sec}s)"
            )
            return False
        
        return True

    def _check_single_symbol(self, symbol: str) -> None:
        """Helper to check a single symbol for flash crash."""
        try:
            df = self._market_client.fetch_ohlcv(symbol, days=1)
            if df.empty or len(df) < 2:
                return

            current_price = float(df["close"].iloc[-1])
            prev_price = float(df["close"].iloc[-2])

            if prev_price <= 0:
                return

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

    def _check_symbols(self) -> None:
        """Checks all symbols for flash crash conditions."""
        if not self.symbols:
            return

        workers = min(len(self.symbols), 10)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            executor.map(self._check_single_symbol, self.symbols)

    def _check_position_sl_tp(self) -> None:
        """Checks all open positions for stop-loss and take-profit triggers - thread-safe."""
        # Multi-account mode: check all accounts
        if self._account_manager:
            self._check_sl_tp_multi_account()
            return
        
        # Single account mode
        if self.portfolio:
            self._check_sl_tp_single(self.portfolio, self.exchange_client)
    
    def _check_sl_tp_multi_account(self) -> None:
        """Check SL/TP for all accounts in multi-account mode."""
        for name, data in self._account_manager.get_all_accounts().items():
            portfolio = data["portfolio"]
            client = data["client"]
            self._check_sl_tp_single(portfolio, client, account_name=name)
    
    def _check_sl_tp_single(self, portfolio, exchange_client, account_name: str = "") -> None:
        """Check SL/TP for single account."""
        prefix = f"[{account_name}] " if account_name else ""
        
        try:
            positions_snapshot = portfolio.get_positions_safe()
        except Exception as e:
            logger.warning(f"{prefix}SL/TP check failed - could not get positions: {e}")
            return
        
        for pos in positions_snapshot:
            try:
                if pos.stop_loss <= 0 and pos.take_profit <= 0:
                    continue

                current_price = self._market_client.fetch_current_price(pos.symbol)
                if current_price is None or current_price <= 0:
                    continue

                if pos.should_stop_loss(current_price):
                    logger.warning(
                        f"{prefix}STOP-LOSS TRIGGERED: %s (entry=%.4f, SL=%.4f, current=%.4f, amount=%.6f)",
                        pos.symbol,
                        pos.entry_price,
                        pos.stop_loss,
                        current_price,
                        pos.amount,
                    )
                    self._emergency_close(pos, current_price, "stop-loss", exchange_client, portfolio, account_name, halt_system=False)

                elif pos.should_take_profit(current_price):
                    logger.info(
                        f"{prefix}TAKE-PROFIT TRIGGERED: %s (entry=%.4f, TP=%.4f, current=%.4f, amount=%.6f)",
                        pos.symbol,
                        pos.entry_price,
                        pos.take_profit,
                        current_price,
                        pos.amount,
                    )
                    self._emergency_close(pos, current_price, "take-profit", exchange_client, portfolio, account_name, halt_system=False)

            except Exception as e:
                logger.warning(f"{prefix}SL/TP check failed for %s: %s", pos.symbol, e)

    def _trigger_system_halt(self, reason: str) -> None:
        """STOP dosyası ve merkezi durum yönetimini tek yerde tetikle."""
        try:
            stop_path = DATA_DIR / "STOP"
            stop_path.parent.mkdir(parents=True, exist_ok=True)
            stop_path.touch()
            self._system_status.emergency_stop(reason)
            logger.critical("EMERGENCY HALT triggered by Watchdog: %s", reason)
        except OSError as stop_err:
            logger.critical("Failed to create STOP file: %s", stop_err)
            from risk.circuit_breaker import CircuitBreaker

            CircuitBreaker().manual_stop()

    def _emergency_close(
        self,
        pos,
        price: float,
        reason: str,
        exchange_client=None,
        portfolio=None,
        account_name: str = "",
        halt_system: bool = True,
    ) -> None:
        """Executes an emergency close for a position - atomic."""
        client = exchange_client or self.exchange_client
        portf = portfolio or self.portfolio
        prefix = f"[{account_name}] " if account_name else ""

        if not client:
            logger.error(f"{prefix}No exchange client available for emergency close")
            return

        from execution.order_manager import TradeOrder

        order = TradeOrder(
            symbol=pos.symbol,
            action="sell",
            order_type="market",
            amount=pos.amount,
        )
        try:
            # Atomic check: close_position_safe None dönerse pozisyon zaten yok
            pos_snapshot = portf.get_position_by_symbol_safe(pos.symbol)
            if pos_snapshot is None:
                logger.info(f"{prefix}Position already closed: %s", pos.symbol)
                return

            result = client.execute_order(order, price)
            if result.get("status") in ("filled", "closed", "open"):
                fill_price = float(result.get("price") or price)
                # Atomic close: sadece bir thread başarılı olur
                close_result = portf.close_position_safe(pos.symbol, fill_price)
                if close_result is None:
                    logger.info(f"{prefix}Position already closed (race): %s", pos.symbol)
                    return
                logger.warning(
                    f"{prefix}Emergency sell executed for %s due to %s",
                    pos.symbol,
                    reason,
                )
                if halt_system:
                    self._trigger_system_halt(f"Watchdog {reason}: {pos.symbol}")
                else:
                    logger.info(f"{prefix}System halt bypassed for normal {reason}")
        except Exception as e:
            logger.error(f"{prefix}Emergency sell failed for %s: %s", pos.symbol, e)

    def _handle_crash(
        self,
        symbol: str,
        price: float,
        drop_pct: float,
        account_name: str = "",
    ) -> None:
        """Handles a detected flash crash for a symbol - thread-safe."""
        # Multi-account mode: iterate all accounts if no specific account given
        if self._account_manager:
            if account_name:
                # Specific account
                data = self._account_manager.get_account(account_name)
                if data:
                    self._handle_crash_single(
                        symbol, price, drop_pct,
                        data["client"],
                        data["portfolio"],
                        account_name
                    )
            else:
                # No account specified: crash to ALL accounts
                for name, data in self._account_manager.get_all_accounts().items():
                    self._handle_crash_single(
                        symbol, price, drop_pct,
                        data["client"],
                        data["portfolio"],
                        name
                    )
            return
        
        # Single account mode
        self._handle_crash_single(symbol, price, drop_pct, self.exchange_client, self.portfolio, "")
    
    def _handle_crash_single(
        self,
        symbol: str,
        price: float,
        drop_pct: float,
        exchange_client,
        portfolio,
        account_name: str = "",
    ) -> None:
        """Handle crash for single account."""
        prefix = f"[{account_name}] " if account_name else ""
        
        try:
            pos = portfolio.get_position_by_symbol_safe(symbol)
        except Exception as e:
            logger.warning(f"{prefix}Flash crash - could not get position: {e}")
            return
            
        if pos is None:
            logger.info(f"{prefix}Flash crash: pozisyon bulunamadı %s", symbol)
            return

        if exchange_client:
            from execution.order_manager import TradeOrder

            order = TradeOrder(
                symbol=symbol,
                action="sell",
                order_type="market",
                amount=pos.amount,
            )
            try:
                result = exchange_client.execute_order(order, price)
                if result.get("status") in ("filled", "closed", "open"):
                    fill_price = float(result.get("price") or price)
                    close_result = portfolio.close_position_safe(symbol, fill_price)
                    if close_result is None:
                        logger.warning(
                            "%sPosition was closed by another thread, verifying state",
                            prefix,
                        )
                        # Race-safe: re-check if position still exists locally
                        if portfolio.get_position_by_symbol_safe(symbol) is not None:
                            portfolio.remove_position_safe(symbol)
                            logger.info(
                                "%sRemoved stale position from local state: %s",
                                prefix,
                                symbol,
                            )
                        return
                    logger.warning(
                        "%sEmergency sell executed for %s due to flash crash (%.2f%% drop)",
                        prefix,
                        symbol,
                        drop_pct,
                    )
                    self._trigger_system_halt(
                        f"Flash crash detected for {symbol} ({drop_pct:.2f}% drop)"
                    )
            except Exception as e:
                logger.error("%sEmergency sell failed for %s: %s", prefix, symbol, e)

    def get_status(self) -> dict:
        """Returns watchdog status."""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "symbols": self.symbols,
            "crash_threshold_pct": self.crash_threshold_pct,
            "check_interval_sec": self.check_interval_sec,
        }
