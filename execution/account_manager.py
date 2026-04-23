"""
Multi-Account Manager
=====================
1:N mimarisi için birden fazla Binance hesabını yönetir.

Her hesap:
- Kendi ExchangeClient (farklı API key/secret)
- Kendi PortfolioState (ayrı JSON dosyası)
- Bağımsız pozisyon ve risk yönetimi

Fan-out execution: LLM kararı tüm hesaplara dağıtılır,
her hesap kendi bakiyesine göre pozisyon boyutlandırır.

Kullanım:
    from execution.account_manager import MultiAccountManager
    from config.settings import get_settings
    
    settings = get_settings()
    manager = MultiAccountManager(settings.binance_accounts)
    
    # Tüm hesapları al
    accounts = manager.get_all_accounts()
    
    # Fan-out trade
    manager.execute_trade(order)
    
    # Emergency close
    manager.emergency_close_all()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR, get_settings, get_trading_params
from risk.portfolio import PortfolioState
from execution.order_manager import TradeOrder

logger = logging.getLogger(__name__)

ACCOUNT_RATE_LIMIT_DELAY = 0.2  # Saniye cinsinden rate limit delay


@dataclass
class AccountStatus:
    """Hesap durumu."""
    name: str
    is_active: bool = True
    last_error: str = ""
    last_sync_cycle: int = 0
    open_positions_count: int = 0


class MultiAccountManager:
    """Birden fazla Binance hesabını yönetir."""
    
    def __init__(
        self,
        accounts: list[dict[str, str]],
        load_portfolios: bool = True,
    ) -> None:
        """
        Multi-account manager başlatır.
        
        Args:
            accounts: [{"name": "...", "api_key": "...", "api_secret": "..."}, ...]
            load_portfolios: True ise portföyler dosyadan yüklenir
        """
        self._accounts_config = accounts
        self._accounts: dict[str, dict[str, Any]] = {}
        self._account_statuses: dict[str, AccountStatus] = {}
        self._lock = threading.RLock()
        self._cycle = 0
        
        # Her hesabı başlat
        for acc in accounts:
            name = acc.get("name", "")
            api_key = acc.get("api_key", "")
            api_secret = acc.get("api_secret", "")
            
            if not name:
                logger.warning("Hesap adı yok, atlanıyor")
                continue
            
            logger.info(f"Hesap başlatılıyor: {name}")
            
            # ExchangeClient (lazy loading)
            from execution.exchange_client import ExchangeClient
            client = ExchangeClient(api_key=api_key, api_secret=api_secret)
            
            # PortfolioState (ayrı dosya)
            if load_portfolios:
                portfolio_path = DATA_DIR / f"portfolio_state_{name}.json"
                portfolio = PortfolioState.load_from_file(portfolio_path)
            else:
                portfolio = PortfolioState()
            
            # Client'a portfolio referansı set et (emergency close için)
            client.set_portfolio(portfolio)
            
            # Store
            self._accounts[name] = {
                "client": client,
                "portfolio": portfolio,
            }
            self._account_statuses[name] = AccountStatus(name=name, is_active=True)
            
            logger.info(f"Hesap hazır: {name} (equity: ${portfolio.equity:,.2f})")
        
        logger.info(f"Toplam {len(self._accounts)} hesap başlatıldı")
    
    def get_all_accounts(self) -> dict[str, dict[str, Any]]:
        """Tüm hesapları döndür."""
        return self._accounts
    
    def get_account(self, name: str) -> dict[str, Any] | None:
        """Hesap adı ile hesabı al."""
        return self._accounts.get(name)
    
    def get_active_accounts(self) -> dict[str, dict[str, Any]]:
        """Sadece aktif hesapları döndür."""
        return {
            name: data
            for name, data in self._accounts.items()
            if self._account_statuses[name].is_active
        }
    
    def get_account_status(self, name: str) -> AccountStatus | None:
        """Hesap durumunu al."""
        return self._account_statuses.get(name)
    
    def set_account_inactive(self, name: str, reason: str = "") -> None:
        """Hesabı inactive olarak işaretle."""
        if name in self._account_statuses:
            self._account_statuses[name].is_active = False
            self._account_statuses[name].last_error = reason
            logger.warning(f"Hesap deaktif edildi: {name} - {reason}")
    
    def set_account_active(self, name: str) -> None:
        """Hesabı aktif olarak işaretle."""
        if name in self._account_statuses:
            self._account_statuses[name].is_active = True
            self._account_statuses[name].last_error = ""
            logger.info(f"Hesap aktif edildi: {name}")
    
    def _test_connection(self, name: str) -> bool:
        """Hesap bağlantısını test et."""
        data = self._accounts.get(name)
        if not data:
            return False
        
        try:
            client = data["client"]
            balance = client.get_balance()
            return "error" not in balance
        except Exception as e:
            logger.warning(f"Hesap bağlantı testi başarısız ({name}): {e}")
            return False
    
    def sync_account(self, name: str) -> dict[str, Any]:
        """
        Hesabın portföyünü borsa ile senkronize et.
        Manuel restart sonrası çağrılır.
        
        Returns:
            Sync sonucu
        """
        data = self._accounts.get(name)
        if not data:
            return {"status": "error", "reason": "Hesap bulunamadı"}
        
        portfolio = data["portfolio"]
        client = data["client"]
        
        try:
            # Borsadaki bakiyeyi çek
            balance = client.get_balance()
            if "error" in balance:
                return {"status": "error", "reason": balance.get("error")}
            
            # Portföy senkronizasyonu
            portfolio.sync_with_exchange(client)
            
            # Durumu güncelle
            self.set_account_active(name)
            self._account_statuses[name].last_sync_cycle = self._cycle
            
            logger.info(f"Hesap senkronize edildi: {name}")
            return {"status": "success", "balance": balance}
            
        except Exception as e:
            logger.error(f"Senkronizasyon hatası ({name}): {e}")
            return {"status": "error", "reason": str(e)}
    
    def _calculate_position_size_for_account(
        self,
        portfolio: PortfolioState,
        client: Any,
        price: float,
        risk_pct: float | None = None,
    ) -> float:
        """
        Hesap için pozisyon boyutunu hesapla.
        
        Her hesap kendi bakiyesine göre boyutlandırır.
        """
        params = get_trading_params()
        risk_percentage = risk_pct or params.risk.max_position_pct
        
        # Canlı bakiye kullan (varsa)
        current_cash = portfolio.cash
        if params.execution.mode.value == "live":
            try:
                balance = client.get_balance()
                current_cash = balance.get("USDT", portfolio.cash)
            except Exception:
                pass
        
        max_value = current_cash * risk_percentage
        
        if price <= 0:
            return 0.0
        
        return max_value / price
    
    def execute_trade(self, order: TradeOrder) -> dict[str, Any]:
        """
        TradeOrder'ı tüm aktif hesaplara dağıtır (fan-out).
        
        Her hesap:
        1. Kendi bakiyesine göre pozisyon boyutlandırır
        2. Order execute eder
        3. Hata olursa logla ve devam et
        
        Returns:
            {account_name: result_dict, ...}
        """
        results = {}
        active_accounts = self.get_active_accounts()
        
        if not active_accounts:
            logger.warning("Aktif hesap yok")
            return {"status": "error", "reason": "No active accounts"}
        
        # Kullanılacak risk yüzdesi (order'dan veya default)
        risk_pct = order.execution_size_pct if order.execution_size_pct > 0 else 1.0
        
        for name, data in active_accounts.items():
            # Rate limit delay
            if results:  # İlk hesap değilse bekle
                time.sleep(ACCOUNT_RATE_LIMIT_DELAY)
            
            client = data["client"]
            portfolio = data["portfolio"]
            
            try:
                # Fiyatı al
                price = order.price or 0.0
                if price <= 0:
                    from data.market_data import MarketDataClient
                    market = MarketDataClient()
                    price = market.fetch_current_price(order.symbol) or 0.0
                
                # Pozisyon boyutunu hesapla (hesabın bakiyesine göre)
                size = self._calculate_position_size_for_account(
                    portfolio, client, price, risk_pct
                )
                
                if size <= 0:
                    logger.warning(f"[{name}] Yetersiz bakiye veya boyut hesaplanamadı")
                    results[name] = {"status": "skipped", "reason": "Insufficient balance or size"}
                    continue
                
                # Order'ı kopyala ve boyutu güncelle
                account_order = TradeOrder(
                    symbol=order.symbol,
                    action=order.action,
                    order_type=order.order_type,
                    amount=size,
                    price=order.price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    confidence=order.confidence,
                    reasoning=f"{order.reasoning} (fan-out: {name})",
                    timestamp=order.timestamp,
                    execution_size_pct=order.execution_size_pct,
                    target_size=order.target_size,
                    is_dca_tranche=order.is_dca_tranche,
                    tranche_number=order.tranche_number,
                )
                
                # Execute
                logger.info(f"[{name}] Emir gönderiliyor: {order.action} {order.symbol} {size}")
                result = client.execute_order(account_order, current_price=price)
                results[name] = result
                
                # Başarılıysa portföyü güncelle
                if result.get("status") in ("filled", "closed", "open"):
                    exec_price = float(result.get("price") or price)
                    exec_amount = float(result.get("amount") or size)
                    
                    if order.action == "buy" and not order.is_dca_tranche:
                        portfolio.open_position(
                            symbol=order.symbol,
                            side="long",
                            price=exec_price,
                            amount=exec_amount,
                            stop_loss=order.stop_loss,
                            take_profit=order.take_profit,
                            target_size=order.target_size,
                            target_size_usd=order.target_size * exec_price,
                        )
                    elif order.action == "buy" and order.is_dca_tranche:
                        portfolio.add_dca_tranche(
                            symbol=order.symbol,
                            amount=exec_amount,
                            price=exec_price,
                            stop_loss=order.stop_loss,
                            take_profit=order.take_profit,
                        )
                    elif order.action == "sell":
                        portfolio.close_position_safe(order.symbol, exec_price)
                    
                    portfolio.save_to_file()
                
                logger.info(f"[{name}] Emir sonucu: {result.get('status')}")
            
            except Exception as e:
                logger.error(f"[{name}] Emir hatası: {e}")
                error_msg = str(e)
                
                # IP/ban hatası mı?
                if "429" in error_msg or "IP" in error_msg.upper() or "BAN" in error_msg.upper():
                    self.set_account_inactive(name, f"IP/Rate limit: {error_msg}")
                else:
                    # Diğer hatalar - logla ama devam et
                    results[name] = {"status": "error", "message": error_msg}
        
        self._cycle += 1
        
        # Özet
        success_count = sum(1 for r in results.values() if r.get("status") in ("filled", "closed", "open"))
        logger.info(f"Fan-out tamamlandı: {success_count}/{len(results)} hesap başarılı")
        
        return results
    
    def emergency_close_all(self) -> dict[str, Any]:
        """
        Tüm hesaplardaki açık pozisyonları kapatır (emergency stop).
        
        Returns:
            {account_name: close_result, ...}
        """
        results = {}
        
        for name, data in self._accounts.items():
            client = data["client"]
            portfolio = data["portfolio"]
            
            try:
                logger.warning(f"[{name}] Emergency close başlatılıyor")
                client._emergency_close_all(portfolio)
                results[name] = {"status": "success"}
            except Exception as e:
                logger.error(f"[{name}] Emergency close hatası: {e}")
                results[name] = {"status": "error", "message": str(e)}
        
        return results
    
    def save_all_portfolios(self) -> None:
        """Tüm hesapların portföylerini kaydet."""
        for name, data in self._accounts.items():
            try:
                data["portfolio"].save_to_file()
            except Exception as e:
                logger.error(f"Portföy kaydetme hatası ({name}): {e}")
    
    def get_portfolio(self, name: str) -> PortfolioState | None:
        """Hesabın portföyünü al."""
        data = self._accounts.get(name)
        return data["portfolio"] if data else None
    
    def get_representative_portfolio(self) -> PortfolioState:
        """
        LLM için temsili portföy döndürür.
        Genellikle "Main" hesabı kullanılır.
        """
        # Main hesabı dene
        if "Main" in self._accounts:
            return self._accounts["Main"]["portfolio"]
        
        # İlk hesabı al
        first_name = next(iter(self._accounts), None)
        if first_name:
            return self._accounts[first_name]["portfolio"]
        
        # Fallback
        return PortfolioState()
    
    def get_status_summary(self) -> dict[str, Any]:
        """Hesap durum özetini döndürür."""
        return {
            "total_accounts": len(self._accounts),
            "active_accounts": sum(1 for s in self._account_statuses.values() if s.is_active),
            "accounts": {
                name: {
                    "is_active": status.is_active,
                    "last_error": status.last_error,
                    "equity": data["portfolio"].equity,
                    "cash": data["portfolio"].cash,
                    "open_positions": data["portfolio"].open_position_count,
                }
                for name, data in self._accounts.items()
                for status in [self._account_statuses[name]]
            }
        }


# ── Convenience Function ──────────────────────────────────────

def create_account_manager() -> MultiAccountManager:
    """MultiAccountManager factory function."""
    from config.settings import get_settings
    settings = get_settings()
    return MultiAccountManager(settings.binance_accounts)
