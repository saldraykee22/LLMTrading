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
from typing import Any, cast

import ccxt
from ccxt.base.types import OrderSide

from config.settings import TradingMode, get_settings, get_trading_params
from execution.order_manager import TradeOrder
from execution.paper_engine import PaperTradingEngine
from risk.system_status import SystemStatus, Status

logger = logging.getLogger(__name__)


class ExchangeClient:
    """CCXT tabanlı borsa istemcisi."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._settings = get_settings()
        self._params = get_trading_params()
        self._exchange: ccxt.Exchange | None = None
        self._last_request_time: float = 0
        self._paper_engine: PaperTradingEngine | None = None

        # Multi-account support: use provided keys or fallback to settings
        self._api_key = api_key or self._settings.binance_api_key
        self._api_secret = api_secret or self._settings.binance_api_secret

        # Fail-safe mechanism
        self._last_successful_call = time.time()
        self._connection_timeout = 300  # 5 dakika
        self._system_status = SystemStatus.get_instance()

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
        Başarılı olursa SystemStatus'u RUNNING yapar.
        
        Paper mode'da exchange None olabilir, bu durumda hemen başarılı dön.
        """
        if not self._system_status.is_emergency() and not self._system_status.is_reconnecting():
            return True
        
        # Paper mode kontrolü - exchange None olabilir
        if self._params.execution.mode == TradingMode.PAPER:
            logger.info("📝 Paper mode: Reconnection simüle edildi")
            self._system_status.resume()
            return True
        
        logger.info("Reconnection attempt (max %d attempts)...", max_attempts)
        
        for attempt in range(max_attempts):
            lock_acquired = False
            try:
                # Bağlantı testi
                lock_acquired = self._exchange_lock.acquire(timeout=5)
                if not lock_acquired:
                    raise TimeoutError("exchange lock timeout during reconnect")

                if self._exchange:
                    # Basit bir API çağrısı ile bağlantıyı test et
                    self._exchange.fetch_balance()

                self._last_successful_call = time.time()
                # SystemStatus'u RUNNING yap
                self._system_status.resume()
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
            finally:
                if lock_acquired:
                    self._exchange_lock.release()
        
        logger.error("❌ Reconnection failed after %d attempts", max_attempts)
        return False
    
    def _check_connection(self) -> bool:
        """Heartbeat kontrolü, timeout varsa emergency moda geç."""
        # Eğer emergency mode'daysak reconnect dene
        if self._system_status.is_emergency() or self._system_status.is_reconnecting():
            if self.try_reconnect():
                return True
            return False
        
        if time.time() - self._last_successful_call > self._connection_timeout:
            logger.critical("API bağlantı kesildi — EMERGENCY MODE")
            # SystemStatus'u güncelle
            self._system_status.emergency_stop("API connection timeout")
            self._system_status.reconnecting("Attempting reconnection")
            self._emergency_close_all()
            return False
        
        return True

    def _emergency_close_all(self, portfolio: Any = None) -> None:
        """Tüm açık pozisyonları akıllı (Smart Close) emirlerle kapatır - thread-safe."""
        from risk.portfolio import PortfolioState

        target_portfolio = portfolio or self._portfolio_ref
        if target_portfolio is None:
            logger.error(
                "Emergency close: no portfolio reference available, aborting"
            )
            return

        with target_portfolio._lock:
            positions_to_close = list(target_portfolio.positions)

            if not positions_to_close:
                logger.info("Emergency close: Açık pozisyon yok.")
                return

            logger.critical(
                "🚨 EMERGENCY CLOSE ALL: %d pozisyon kapatılıyor! (Smart Close Devrede)",
                len(positions_to_close),
            )

            closed_symbols = []

            for pos in positions_to_close:
                action = "sell" if pos.side == "long" else "buy"
                order = TradeOrder(
                    symbol=pos.symbol,
                    action=action,
                    amount=pos.amount,
                    order_type="market",  # Market emir + slippage toleranslı fallback
                )
                try:
                    if self._params.execution.mode == TradingMode.PAPER:
                        self._get_paper_engine().execute_order(order, pos.current_price)
                        closed_symbols.append(pos.symbol)
                    else:
                        with self._exchange_lock:
                            exchange = self._get_exchange()
                            
                            # Önce market emir dene, başarısız olursa slippage toleranslı limit fallback
                            try:
                                ticker = exchange.fetch_ticker(order.symbol)
                                current_price = float(ticker.get('last', pos.current_price))
                            except Exception:
                                current_price = float(pos.current_price)

                            exec_amount_str = exchange.amount_to_precision(order.symbol, order.amount)

                            logger.info(
                                "Emergency Close [%s]: %s %s @ market (~%s)", 
                                order.symbol, order.action.upper(), exec_amount_str, current_price
                            )

                            try:
                                exchange.create_order(
                                    symbol=order.symbol,
                                    type="market",
                                    side=order.action,
                                    amount=float(exec_amount_str),
                                )
                            except Exception as market_err:
                                logger.warning(
                                    "Market emir başarısız (%s), slippage toleranslı limit deneniyor: %s",
                                    order.symbol, market_err
                                )
                                # Fallback: %5 slippage toleranslı limit emir
                                if order.action == "sell":
                                    safe_price = current_price * 0.95
                                else:
                                    safe_price = current_price * 1.05
                                safe_price_str = exchange.price_to_precision(order.symbol, safe_price)
                                exchange.create_order(
                                    symbol=order.symbol,
                                    type="limit",
                                    side=order.action,
                                    amount=float(exec_amount_str),
                                    price=float(safe_price_str)
                                )
                        closed_symbols.append(pos.symbol)
                except Exception as e:
                    logger.error("Emergency close hatası (%s): %s", pos.symbol, e)

            # Pozisyonları thread-safe şekilde kaldır
            for sym in closed_symbols:
                target_portfolio.remove_position_safe(sym)

            target_portfolio.save_to_file()
            logger.info(
                "Emergency close tamamlandı: %s pozisyon kapatıldı (market emir + limit fallback)", len(closed_symbols)
            )

    def _get_paper_engine(self) -> PaperTradingEngine:
        """Paper trading engine'i lazy olarak başlatır (thread-safe)."""
        with self._exchange_lock:
            if self._paper_engine is None:
                self._paper_engine = PaperTradingEngine(
                    initial_cash=self._params.backtest.initial_cash,
                )
            return self._paper_engine

    def _execute_paper_order(
        self, order: TradeOrder, current_price: float
    ) -> dict[str, Any]:
        """
        Paper emrini yürütür.
        Eğer portfolio referansı varsa PortfolioState üzerinden çalışır,
        böylece tek bir kaynak doğruluğu (single source of truth) sağlanır.
        """
        from datetime import datetime, timezone

        if not self._portfolio_ref:
            # Fallback: eski PaperTradingEngine
            return self._get_paper_engine().execute_order(order, current_price)

        portfolio = self._portfolio_ref

        if order.action == "buy":
            existing_pos = portfolio.get_position_by_symbol_safe(order.symbol)
            if not order.is_dca_tranche:
                if existing_pos:
                    return {
                        "status": "rejected",
                        "message": f"Position already exists: {order.symbol}",
                        "symbol": order.symbol,
                    }
                pos = portfolio.open_position(
                    symbol=order.symbol,
                    side="long",
                    price=current_price,
                    amount=order.amount,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    target_size=order.target_size,
                    target_size_usd=order.target_size * current_price
                    if order.target_size > 0
                    else order.amount * current_price,
                )
                if pos:
                    return {
                        "status": "filled",
                        "order_id": f"paper_{order.symbol}_{int(datetime.now(timezone.utc).timestamp())}",
                        "symbol": order.symbol,
                        "side": "buy",
                        "type": order.order_type,
                        "amount": order.amount,
                        "price": current_price,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mode": "paper",
                    }
                return {
                    "status": "rejected",
                    "message": "Portfolio open_position failed",
                }
            else:
                # DCA kademesi
                if not existing_pos:
                    return {
                        "status": "rejected",
                        "message": f"No existing position for DCA: {order.symbol}",
                    }
                pos = portfolio.add_dca_tranche(
                    symbol=order.symbol,
                    amount=order.amount,
                    price=current_price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                )
                if pos:
                    return {
                        "status": "filled",
                        "order_id": f"paper_dca_{order.symbol}_{int(datetime.now(timezone.utc).timestamp())}",
                        "symbol": order.symbol,
                        "side": "buy",
                        "type": order.order_type,
                        "amount": order.amount,
                        "price": current_price,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mode": "paper",
                    }
                return {
                    "status": "rejected",
                    "message": "Portfolio add_dca_tranche failed",
                }

        elif order.action == "sell":
            existing_pos = portfolio.get_position_by_symbol_safe(order.symbol)
            if not existing_pos:
                return {
                    "status": "rejected",
                    "message": f"No position to sell: {order.symbol}",
                }
            result = portfolio.close_position_safe(order.symbol, current_price)
            if result:
                return {
                    "status": "filled",
                    "order_id": f"paper_sell_{order.symbol}_{int(datetime.now(timezone.utc).timestamp())}",
                    "symbol": order.symbol,
                    "side": "sell",
                    "type": order.order_type,
                    "amount": order.amount,
                    "price": current_price,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode": "paper",
                }
            return {
                "status": "rejected",
                "message": "Portfolio close_position_safe failed",
            }

        return {
            "status": "error",
            "message": f"Unknown action: {order.action}",
        }

    def _get_exchange(self) -> ccxt.Exchange:
        """Borsa bağlantısını başlatır (lazy)."""
        if self._exchange is None:
            exchange_id = self._params.execution.exchange
            config: dict = {
                "apiKey": self._api_key,
                "secret": self._api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
                "maxConcurrentRequests": 5,
            }

            if self._settings.binance_testnet:
                config["sandbox"] = True

            def _sanitize_config(cfg: dict) -> dict:
                """Deep sanitize config dict for safe logging."""
                sensitive_keys = {"apiKey", "secret", "password", "uid", "login"}
                sanitized = {}
                for k, v in cfg.items():
                    if k in sensitive_keys:
                        sanitized[k] = "***" if v else ""
                    elif isinstance(v, dict):
                        sanitized[k] = _sanitize_config(v)
                    else:
                        sanitized[k] = v
                return sanitized

            safe_config = _sanitize_config(config)

            exchange_class = getattr(ccxt, exchange_id, None)
            if exchange_class is None:
                raise ValueError(f"CCXT borsa bulunamadı: {exchange_id}")

            try:
                self._exchange = exchange_class(config)
                # Market bilgisini (precision, limits vb.) yükle
                self._exchange.load_markets()
            except Exception as e:
                logger.error(
                    "Borsa bağlantısı başlatılamadı: %s (config=%s)",
                    str(e),
                    safe_config,
                )
                raise
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
        # 1. SystemStatus Check (event-driven, STOP file polling yerine)
        if not self._system_status.is_running():
            reason = self._system_status.get_halt_reason() or "System halted"
            logger.warning("SYSTEM HALTED: Emir reddedildi (%s %s) - %s", order.action, order.symbol, reason)
            return {"status": "rejected", "message": f"System halted: {reason}"}
        
        # 2. Circuit Breaker Check (SystemStatus ile entegre)
        from risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        portfolio = self._portfolio_ref
        equity = getattr(portfolio, "equity", 1.0)
        daily_pnl = getattr(portfolio, "daily_pnl", 0.0)
        is_halt, cb_reason = cb.should_halt(equity=equity, daily_pnl=daily_pnl)
        if is_halt:
            logger.warning("CIRCUIT BREAKER ACTIVE: New orders blocked. Reason: %s", cb_reason)
            return {"status": "rejected", "message": "Circuit breaker active"}

        # Check connection BEFORE acquiring portfolio lock to avoid lock nesting deadlock
        if not self._check_connection():
            return {"status": "error", "message": "API bağlantı kesildi"}

        # Paper mod — simülasyon (portfolio optional, legacy engine fallback)
        if self._params.execution.mode == TradingMode.PAPER:
            logger.info(
                "📝 PAPER TRADING: %s %s %.6f %s",
                order.action.upper(),
                order.symbol,
                order.amount,
                order.order_type,
            )
            result = self._execute_paper_order(order, current_price)
            self._last_successful_call = time.time()
            return result

        if portfolio is None:
            return {"status": "error", "message": "Portfolio reference missing"}

        with portfolio._lock:

            # Live mod — gerçek borsa
            with self._exchange_lock:
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
            
            import uuid
            # Idempotent execution: generate a unique clientOrderId with 'llm_' prefix for tagging
            client_order_id = f"llm_{str(uuid.uuid4()).replace('-', '')[:28]}"

            for attempt in range(self._params.execution.retry_count):
                # Retry öncesi emir gerçekleşti mi kontrolü (Idempotency Check)
                if attempt > 0:
                    try:
                        with self._exchange_lock:
                            recent_orders = exchange.fetch_orders(order.symbol, limit=10)
                            found_order = next((o for o in recent_orders if o.get('clientOrderId') == client_order_id or o.get('info', {}).get('clientOrderId') == client_order_id), None)
                            
                            if found_order:
                                logger.info("Önceki deneme başarılı olmuş, emir tekrar edilmeyecek: %s", client_order_id)
                                order_status = found_order.get("status", "")
                                filled_status = "filled" if order_status == "closed" else order_status
                                return {
                                    "status": filled_status,
                                    "order_id": found_order.get("id"),
                                    "symbol": found_order.get("symbol"),
                                    "side": found_order.get("side"),
                                    "type": found_order.get("type"),
                                    "amount": found_order.get("amount"),
                                    "price": found_order.get("price") or found_order.get("average"),
                                    "cost": found_order.get("cost"),
                                    "fee": found_order.get("fee"),
                                    "timestamp": found_order.get("datetime"),
                                }
                    except Exception as verify_exc:
                        logger.warning("Retry öncesi emir durumu doğrulanamadı: %s", verify_exc)

                try:
                    with self._exchange_lock:
                        # Miktar ve fiyatı borsa hassasiyetine göre yuvarla
                        exec_amount = exchange.amount_to_precision(order.symbol, order.amount)
                        
                        params = {"clientOrderId": client_order_id}

                        if order.order_type == "market":
                            result = exchange.create_order(
                                symbol=order.symbol,
                                type="market",
                                side=order.action,
                                amount=exec_amount,
                                params=params
                            )
                        elif order.order_type == "limit":
                            exec_price = exchange.price_to_precision(order.symbol, order.price)
                            result = exchange.create_order(
                                symbol=order.symbol,
                                type="limit",
                                side=order.action,
                                amount=exec_amount,
                                price=exec_price,
                                params=params
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
                        "Emir gönderildi: ID=%s, durum=%s, fiyat=%s (clientOrderId=%s)",
                        order_info["order_id"],
                        order_info["status"],
                        order_info["price"],
                        client_order_id
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
    
    def sweep_dust(self, target_asset: str = "BNB") -> dict[str, Any]:
        """
        Dust (küçük bakiye) temizleme.
        Binance "Convert to BNB" API'sini kullanır.
        
        Endpoint: /sapi/v1/asset/dust
        Docs: https://binance-docs.github.io/apidocs/spot/en/#dust-transfer-user_data
        
        Args:
            target_asset: Dönüştürülecek varlık (varsayılan: BNB)
        
        Returns:
            {
                "status": "success" | "paper_mode" | "no_dust" | "error",
                "swept": ["BTC", "ETH", ...],
                "received": 0.123,  # Alınan BNB miktarı
                "target_asset": "BNB"
            }
        """
        with self._exchange_lock:
            # Paper mode kontrolü
            if self._params.execution.mode == TradingMode.PAPER:
                logger.info("🧹 Paper mode: Dust süpürme simüle edildi")
                return {
                    "status": "paper_mode",
                    "swept": [],
                    "received": 0.0,
                    "target_asset": target_asset,
                }
            
            exchange = self._get_exchange()
            
            # CCXT Binance'de dust transfer desteği kontrolü
            dust_method = None
            for method_name in ('sapi_post_asset_dust', 'sapiPostAssetDust'):
                if hasattr(exchange, method_name):
                    dust_method = getattr(exchange, method_name)
                    break
            if dust_method is None:
                logger.warning("Borsa dust transfer'i desteklemiyor")
                return {
                    "status": "not_supported",
                    "swept": [],
                    "received": 0.0,
                    "target_asset": target_asset,
                }
            
            self._rate_limit()
            
            try:
                dust_assets = self._get_dust_assets()
                
                if not dust_assets:
                    logger.debug("🧹 Temizlenecek dust bulunamadı")
                    return {
                        "status": "no_dust",
                        "swept": [],
                        "received": 0.0,
                        "target_asset": target_asset,
                    }
                
                # Binance API çağrısı
                # CCXT formatı: {'asset': ['BTC', 'ETH'], ...}
                result = dust_method({
                    'asset': dust_assets
                })
                
                self._last_successful_call = time.time()
                
                # Sonuç parse
                total_bnb = float(result.get('totalTransferedAmount', 0))
                swept_assets = [
                    transfer['asset']
                    for transfer in result.get('transferResult', [])
                    if transfer.get('success')
                ]
                
                logger.info(
                    "✅ Dust süpürme tamamlandı: %d varlık → %.4f %s",
                    len(swept_assets),
                    total_bnb,
                    target_asset
                )
                
                return {
                    "status": "success",
                    "swept": swept_assets,
                    "received": total_bnb,
                    "target_asset": target_asset,
                }
                
            except ccxt.BaseError as e:
                logger.error("Dust süpürme hatası: %s", e)
                if not self._check_connection():
                    logger.warning("Bağlantı koptuğu için acil duruma geçildi.")
                return {
                    "status": "error",
                    "swept": [],
                    "received": 0.0,
                    "target_asset": target_asset,
                    "error": str(e),
                }
    
    def _get_dust_assets(self, threshold_usdt: float = 1.0) -> list[str]:
        """
        $1 altı dust bakiyeleri tespit et.
        
        Args:
            threshold_usdt: Dust eşiği (USD)
        
        Returns:
            Dust varlık listesi (örn: ["BTC", "ETH", "ALT"])
        """
        try:
            # Tüm bakiyeleri çek
            balance = self.get_balance()
            
            if "error" in balance:
                return []
            
            # USDT fiyatlarını çek
            tickers = self._get_exchange().fetch_tickers()
            
            dust_assets = []
            
            for asset, amount in balance.items():
                if asset in ["USDT", "BNB"]:  # USDT ve BNB'yi temizleme
                    continue
                
                # USDT paritesi bul
                symbol = f"{asset}/USDT"
                
                if symbol not in tickers:
                    # USDT paritesi yoksa, BTC paritesini dene
                    symbol = f"{asset}/BTC"
                    if symbol not in tickers:
                        continue
                    
                    # BTC/USDT fiyatı ile çapraz hesapla
                    btc_usdt = tickers.get("BTC/USDT", {})
                    btc_price = float(btc_usdt.get('last', 0) or 0)
                    asset_btc = float(tickers[symbol].get('last', 0) or 0)
                    usdt_price = btc_price * asset_btc
                else:
                    usdt_price = float(tickers[symbol].get('last', 0) or 0)
                
                # USD değeri hesapla
                usdt_value = amount * usdt_price
                
                if usdt_value < threshold_usdt and usdt_value > 0:
                    logger.debug(
                        "🔍 Dust tespit edildi: %s = %.4f (%.2f USDT)",
                        asset, amount, usdt_value
                    )
                    dust_assets.append(asset)
            
            logger.info("🧹 Toplam %d dust varlık bulundu", len(dust_assets))
            return dust_assets
            
        except Exception as e:
            logger.error("Dust tespit hatası: %s", e)
            return []
