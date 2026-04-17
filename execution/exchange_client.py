"""
Borsa İstemcisi (Exchange Client)
==================================
CCXT üzerinden Binance (ve diğer borsalar) ile alım-satım bağlantısı.
Paper trading ve live trading modlarını destekler.
"""

from __future__ import annotations

import logging
import time
import threading
from pathlib import Path
from typing import Any, cast

import ccxt
from ccxt.base.types import OrderSide

from config.settings import TradingMode, get_settings, get_trading_params
from execution.order_manager import TradeOrder
from execution.paper_engine import PaperTradingEngine

logger = logging.getLogger(__name__)


class ExchangeClient:
    """CCXT tabanlı borsa istemcisi."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._params = get_trading_params()
        self._exchange: ccxt.Exchange | None = None
        self._last_request_time: float = 0
        self._paper_engine: PaperTradingEngine | None = None

        # Fail-safe mechanism
        self._last_successful_call = time.time()
        self._connection_timeout = 300  # 5 dakika
        self._emergency_mode = False

        # Thread-safe portfolio reference for emergency close
        self._portfolio_ref: Any = None
        self._exchange_lock = threading.RLock()

    def set_portfolio(self, portfolio) -> None:
        """Emergency close için portföy referansı kaydet."""
        self._portfolio_ref = portfolio
        logger.debug("Portfolio reference set for emergency close")

    def try_reconnect(self, max_attempts: int = 5) -> bool:
        """
        Acil durum modundan çıkmak için yeniden bağlanma dene.
        Exponential backoff ile 5 deneme yapar.
        """
        if not self._emergency_mode:
            return True
        
        logger.info("Reconnection attempt (max %d attempts)...", max_attempts)
        
        for attempt in range(max_attempts):
            try:
                # Bağlantı testi
                with self._exchange_lock:
                    if self._exchange:
                        # Basit bir API çağrısı ile bağlantıyı test et
                        self._exchange.fetch_balance()
                    
                    self._emergency_mode = False
                    self._last_successful_call = time.time()
                    logger.info("✅ Reconnection successful after %d attempt(s)", attempt + 1)
                    return True
                    
            except Exception as e:
                delay = 2 ** (attempt + 1)  # 2s, 4s, 8s, 16s, 32s
                logger.warning(
                    "Reconnection attempt %d/%d failed: %s. Retrying in %ds...",
                    attempt + 1,
                    max_attempts,
                    e,
                    delay,
                )
                time.sleep(delay)
        
        logger.error("❌ Reconnection failed after %d attempts", max_attempts)
        return False
    
    def _check_connection(self) -> bool:
        """Heartbeat kontrolü, timeout varsa emergency moda geç."""
        # Eğer emergency mode'daysak reconnect dene
        if self._emergency_mode:
            if self.try_reconnect():
                return True
            return False
        
        if time.time() - self._last_successful_call > self._connection_timeout:
            logger.critical("API bağlantı kesildi — EMERGENCY MODE")
            self._emergency_mode = True
            self._emergency_close_all()
            return False
        
        return True

    def _emergency_close_all(self, portfolio: Any = None) -> None:
        """Tüm açık pozisyonları market emriyle kapatır - thread-safe."""
        from risk.portfolio import PortfolioState, _portfolio_lock

        with _portfolio_lock:
            target_portfolio = portfolio or self._portfolio_ref
            if target_portfolio is None:
                logger.warning(
                    "Emergency close: no portfolio reference, loading from file"
                )
                target_portfolio = PortfolioState.load_from_file()

            positions_to_close = list(target_portfolio.positions)

            if not positions_to_close:
                logger.info("Emergency close: Açık pozisyon yok.")
                return

            logger.critical(
                "🚨 EMERGENCY CLOSE ALL: %d pozisyon kapatılıyor!",
                len(positions_to_close),
            )

            closed_symbols = []

            for pos in positions_to_close:
                action = "sell" if pos.side == "long" else "buy"
                order = TradeOrder(
                    symbol=pos.symbol,
                    action=action,
                    amount=pos.amount,
                    order_type="market",
                )
                try:
                    if self._params.execution.mode == TradingMode.PAPER:
                        self._get_paper_engine().execute_order(order, pos.current_price)
                        closed_symbols.append(pos.symbol)
                    else:
                        with self._exchange_lock:
                            exchange = self._get_exchange()
                            exchange.create_order(  # type: ignore
                                symbol=order.symbol,
                                type="market",
                                side=order.action,
                                amount=order.amount,
                            )
                        closed_symbols.append(pos.symbol)
                except Exception as e:
                    logger.error("Emergency close hatası (%s): %s", pos.symbol, e)

            # Pozisyonları thread-safe şekilde kaldır
            for sym in closed_symbols:
                target_portfolio.remove_position_safe(sym)

            target_portfolio.save_to_file()
            logger.info(
                "Emergency close tamamlandı: %s pozisyon kapatıldı", len(closed_symbols)
            )

    def _get_paper_engine(self) -> PaperTradingEngine:
        """Paper trading engine'i lazy olarak başlatır."""
        if self._paper_engine is None:
            self._paper_engine = PaperTradingEngine(
                initial_cash=self._params.backtest.initial_cash,
            )
        return self._paper_engine

    def _get_exchange(self) -> ccxt.Exchange:
        """Borsa bağlantısını başlatır (lazy)."""
        if self._exchange is None:
            exchange_id = self._params.execution.exchange
            config: dict = {
                "apiKey": self._settings.binance_api_key,
                "secret": self._settings.binance_api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
                "maxConcurrentRequests": 5,
            }

            if self._settings.binance_testnet:
                config["sandbox"] = True

            exchange_class = getattr(ccxt, exchange_id, None)
            if exchange_class is None:
                raise ValueError(f"CCXT borsa bulunamadı: {exchange_id}")

            try:
                self._exchange = exchange_class(config)
                # Market bilgisini (precision, limits vb.) yükle
                self._exchange.load_markets()
            except Exception as e:
                logger.error("Borsa bağlantısı başlatılamadı: %s", str(e))
                raise
            finally:
                config["apiKey"] = "***"
                config["secret"] = "***"
            status = (
                "TESTNET (Sandbox)" if self._settings.binance_testnet else "MAINNET"
            )
            logger.warning(
                "CONNECTED TO %s: %s (Mode: %s)",
                status,
                exchange_id,
                self._params.execution.mode.value.upper(),
            )
        return self._exchange

    def _rate_limit(self) -> None:
        """Rate limit bekleme."""
        delay = self._params.execution.rate_limit_ms / 1000.0
        elapsed = time.time() - self._last_request_time
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_time = time.time()

    def execute_order(
        self, order: TradeOrder, current_price: float = 0.0
    ) -> dict[str, Any]:
        """
        Emri yürütür (paper veya live).

        Args:
            order: Yapılandırılmış alım-satım emri
            current_price: Güncel piyasa fiyatı (paper mod için gerekli)

        Returns:
            Emir sonucu (order ID, durum vb.)
        """
        # Check for STOP file (Emergency Halt)
        if order.action == "buy" and Path("data/STOP").exists():
            logger.warning("EMERGENCY HALT (data/STOP detected): Yeni alım emri reddedildi.")
            return {"status": "rejected", "message": "Emergency halt active"}
        
        with self._exchange_lock:
            if not self._check_connection():
                return {"status": "error", "message": "API bağlantı kesildi"}

            # Paper mod — simülasyon
            if self._params.execution.mode == TradingMode.PAPER:
                logger.info(
                    "📝 PAPER TRADING: %s %s %.6f %s",
                    order.action.upper(),
                    order.symbol,
                    order.amount,
                    order.order_type,
                )
                result = self._get_paper_engine().execute_order(order, current_price)
                self._last_successful_call = time.time()
                return result

            # Live mod — gerçek borsa
            exchange = self._get_exchange()

            # Güvenlik kontrolü — live mode'da ekstra onay
            if self._params.execution.mode == TradingMode.LIVE:
                if not self._settings.confirm_live_trade:
                    logger.error("LIVE trading rejected: confirm_live_trade is not enabled")
                    return {
                        "status": "rejected",
                        "message": "Live trading confirmation not enabled in settings",
                    }
                logger.warning(
                    "⚠ CANLI İŞLEM: %s %s %.6f %s",
                    order.action.upper(),
                    order.symbol,
                    order.amount,
                    order.order_type,
                )

            self._rate_limit()

            for attempt in range(self._params.execution.retry_count):
                try:
                    # Miktar ve fiyatı borsa hassasiyetine göre yuvarla
                    exec_amount = exchange.amount_to_precision(order.symbol, order.amount)
                    
                    if order.order_type == "market":
                        result = exchange.create_order(
                            symbol=order.symbol,
                            type="market",
                            side=order.action,
                            amount=exec_amount,
                        )
                    elif order.order_type == "limit":
                        exec_price = exchange.price_to_precision(order.symbol, order.price)
                        result = exchange.create_order(
                            symbol=order.symbol,
                            type="limit",
                            side=order.action,
                            amount=exec_amount,
                            price=exec_price,
                        )
                    else:
                        logger.error("Bilinmeyen emir tipi: %s", order.order_type)
                        return {
                            "status": "error",
                            "message": f"Unknown order type: {order.order_type}",
                        }

                    order_status = result.get("status", "")
                    filled_status = "filled" if order_status == "closed" else order_status
                    order_info = {
                        "status": filled_status,
                        "order_id": result.get("id"),
                        "symbol": result.get("symbol"),
                        "side": result.get("side"),
                        "type": result.get("type"),
                        "amount": result.get("amount"),
                        "price": result.get("price") or result.get("average"),
                        "cost": result.get("cost"),
                        "fee": result.get("fee"),
                        "timestamp": result.get("datetime"),
                    }

                    logger.info(
                        "Emir gönderildi: ID=%s, durum=%s, fiyat=%s",
                        order_info["order_id"],
                        order_info["status"],
                        order_info["price"],
                    )
                    self._last_successful_call = time.time()
                    return order_info

                except ccxt.InsufficientFunds as e:
                    logger.error("Yetersiz bakiye: %s", e)
                    return {"status": "error", "message": f"Insufficient funds: {e}"}

                except ccxt.InvalidOrder as e:
                    logger.error("Geçersiz emir: %s", e)
                    return {"status": "error", "message": f"Invalid order: {e}"}

                except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
                    logger.warning(
                        "Ağ hatası (deneme %d/%d): %s",
                        attempt + 1,
                        self._params.execution.retry_count,
                        e,
                    )
                    if attempt < self._params.execution.retry_count - 1:
                        time.sleep(self._params.execution.retry_delay_ms / 1000.0)
                    continue

                except ccxt.BaseError as e:
                    logger.error("CCXT hatası: %s", e)
                    return {"status": "error", "message": str(e)}

            return {"status": "error", "message": "Max retry exceeded"}

    def get_paper_status(self) -> dict[str, Any]:
        """Paper trading engine durumunu döndürür (public API)."""
        if self._params.execution.mode == TradingMode.PAPER:
            engine = self._get_paper_engine()
            return engine.get_status()
        return {"error": "Not in paper trading mode"}

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Bekleyen emri iptal eder."""
        with self._exchange_lock:
            exchange = self._get_exchange()
            self._rate_limit()
            try:
                result = exchange.cancel_order(order_id, symbol)
                logger.info("Emir iptal edildi: %s", order_id)
                self._last_successful_call = time.time()
                return {"status": "cancelled", "order_id": order_id}
            except ccxt.BaseError as e:
                logger.error("İptal hatası: %s", e)
                if not self._check_connection():
                    logger.warning("Bağlantı koptuğu için acil duruma geçildi.")
                return {"status": "error", "message": str(e)}

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        """Açık emirleri listeler."""
        with self._exchange_lock:
            exchange = self._get_exchange()
            self._rate_limit()
            try:
                orders = exchange.fetch_open_orders(symbol)
                self._last_successful_call = time.time()
                return [
                    {
                        "id": o["id"],
                        "symbol": o["symbol"],
                        "side": o["side"],
                        "amount": o["amount"],
                        "price": o["price"],
                        "status": o["status"],
                    }
                    for o in orders
                ]
            except ccxt.BaseError as e:
                logger.error("Açık emir sorgulama hatası: %s", e)
                if not self._check_connection():
                    logger.warning("Bağlantı koptuğu için acil duruma geçildi.")
                return [{"error": str(e), "data": None}]

    def get_balance(self) -> dict[str, Any]:
        """Hesap bakiyesini çeker."""
        with self._exchange_lock:
            exchange = self._get_exchange()
            self._rate_limit()
            try:
                balance = exchange.fetch_balance()
                self._last_successful_call = time.time()
                return {
                    k: float(v)
                    for k, v in balance.get("total", {}).items()
                    if v and float(v) > 0
                }
            except ccxt.BaseError as e:
                logger.error("Bakiye hatası: %s", e)
                if not self._check_connection():
                    logger.warning("Bağlantı koptuğu için acil duruma geçildi.")
                return {"error": str(e), "data": None}
