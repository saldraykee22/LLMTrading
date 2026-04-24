"""
Exchange Sync Manager
======================
Borsa ile yerel state arasındaki tutarlılığı sağlar.

Özellikler:
- Açık emir karşılaştırması (bot vs borsa)
- Bakiye mutabakatı (local vs remote)
- "Zombi emir" tespiti ve temizleme
- Uyuşmazlık alert'i

Kullanım:
    from execution.sync_manager import SyncManager
    
    sync = SyncManager(portfolio, exchange_client)
    
    # Her 10 döngüde 1 çalıştır
    if cycle % 10 == 0:
        sync.reconcile()
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import TradingMode, get_trading_params
from risk.portfolio import PortfolioState
from execution.exchange_client import ExchangeClient

logger = logging.getLogger(__name__)


class SyncManager:
    """Exchange sync manager for reconciliation."""
    
    def __init__(
        self,
        portfolio: PortfolioState | None = None,
        exchange_client: ExchangeClient | None = None,
        account_manager: Any = None,
        reconcile_every_n_cycles: int = 10,
        dust_sweep_every_n_cycles: int = 100,  # Her 100 cycle'da bir dust temizle
    ) -> None:
        # Multi-account support
        self._account_manager = account_manager
        self.portfolio = portfolio
        self.exchange_client = exchange_client
        
        self.reconcile_every_n_cycles = reconcile_every_n_cycles
        self.dust_sweep_every_n_cycles = dust_sweep_every_n_cycles
        self._params = get_trading_params()
        self._last_reconcile_cycle = 0
        self._last_dust_sweep_cycle = 0
        
        # Multi-account mode
        if account_manager:
            logger.info("SyncManager: Multi-account mode enabled")
    
    def should_reconcile(self, cycle: int) -> bool:
        """Reconciliation zamanı geldi mi?"""
        if cycle % self.reconcile_every_n_cycles == 0:
            if cycle != self._last_reconcile_cycle:
                return True
        return False
    
    def reconcile(self, cycle: int = 0) -> dict[str, Any]:
        """
        Full reconciliation işlemi.
        
        Returns:
            Sync result dict
        """
        if self._params.execution.mode == TradingMode.PAPER:
            logger.debug("Paper mode - sync skipped")
            return {"status": "skipped", "reason": "paper_mode"}
        
        # Multi-account mode
        if self._account_manager:
            return self._reconcile_multi_account(cycle)
        
        logger.info("🔄 Exchange reconciliation started (cycle %d)", cycle)
        
        result = {
            "status": "success",
            "cycle": cycle,
            "balance_sync": self._sync_balances(),
            "open_orders_sync": self._sync_open_orders(),
            "dust_sweep": self._maybe_sweep_dust(cycle),
            "zombie_orders_cleaned": 0,
            "discrepancies": [],
        }
        
        self._last_reconcile_cycle = cycle
        logger.info("✅ Reconciliation completed")
        
        return result
    
    def _reconcile_multi_account(self, cycle: int) -> dict[str, Any]:
        """Multi-account reconciliation."""
        results = {}
        total_zombies = 0
        
        for name, data in self._account_manager.get_all_accounts().items():
            portfolio = data["portfolio"]
            client = data["client"]
            
            try:
                result = {
                    "cycle": cycle,
                    "balance_sync": self._sync_balances_for_account(client, portfolio),
                    "open_orders_sync": self._sync_open_orders_for_account(client),
                    "dust_sweep": self._maybe_sweep_dust_for_account(client, cycle),
                }
                results[name] = result
                total_zombies += result.get("open_orders_sync", {}).get("cleaned", 0)
            except Exception as e:
                logger.error(f"Hesap senkronizasyon hatası ({name}): {e}")
                results[name] = {"status": "error", "error": str(e)}
        
        self._last_reconcile_cycle = cycle
        logger.info(f"✅ Multi-account reconciliation tamamlandı: {len(results)} hesap")
        
        return {
            "status": "success",
            "cycle": cycle,
            "accounts": results,
            "zombie_orders_cleaned": total_zombies,
        }
    
    def _sync_balances_for_account(self, client, portfolio) -> dict[str, Any]:
        """Single account balance sync."""
        try:
            remote_balance = client.get_balance()
            local_usdt = portfolio.cash
            remote_usdt = remote_balance.get("USDT", 0.0)

            tolerance = 0.05

            if local_usdt == 0 and remote_usdt > 0:
                logger.warning(
                    f"⚠️  Balance discrepancy: local=0 (empty portfolio), remote={remote_usdt} — possible out-of-sync reset"
                )
                return {"status": "discrepancy", "local": 0.0, "remote": remote_usdt, "diff_pct": 1.0}

            diff_pct = abs(remote_usdt - local_usdt) / local_usdt if local_usdt > 0 else 0

            if diff_pct > tolerance:
                logger.warning(
                    f"⚠️  Balance discrepancy: local={local_usdt}, remote={remote_usdt} ({diff_pct*100:.2f}%)"
                )
                return {"status": "discrepancy", "local": local_usdt, "remote": remote_usdt, "diff_pct": diff_pct}
            
            return {"status": "ok", "local": local_usdt, "remote": remote_usdt}
        except Exception as e:
            logger.error(f"Balance sync failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def _sync_open_orders_for_account(self, client) -> dict[str, Any]:
        """Single account open orders sync."""
        try:
            remote_orders = client.get_open_orders()
            if remote_orders:
                cleaned = self._cancel_zombie_orders_for_account(client, remote_orders)
                return {"status": "zombie_cleaned", "remote_orders": len(remote_orders), "cleaned": cleaned}
            return {"status": "ok", "remote_orders": 0}
        except Exception as e:
            logger.error(f"Open orders sync failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def _maybe_sweep_dust_for_account(self, client, cycle: int) -> dict[str, Any]:
        """Single account dust sweep."""
        if cycle - self._last_dust_sweep_cycle < self.dust_sweep_every_n_cycles:
            return {"status": "skipped", "reason": "not_time_yet"}
        try:
            result = client.sweep_dust(target_asset="BNB")
            self._last_dust_sweep_cycle = cycle
            return result
        except Exception as e:
            logger.error(f"Dust sweep failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def _cancel_zombie_orders_for_account(self, client, orders: list[dict]) -> int:
        """Cancel zombie orders for single account - Only bot-tagged orders."""
        cleaned = 0
        for order in orders:
            order_id = order.get("id")
            client_id = order.get("clientOrderId") or order.get("info", {}).get("clientOrderId", "")
            symbol = order.get("symbol")
            
            # Bot emirlerini ayır
            is_bot_order = str(client_id).startswith("llm_")
            
            if is_bot_order:
                logger.warning(f"🧟 Zombie Bot Order: {order.get('side')} {symbol} (ID: {order_id}, CID: {client_id})")
                try:
                    result = client.cancel_order(order_id, symbol)
                    if result.get("status") == "cancelled":
                        cleaned += 1
                except Exception as e:
                    logger.error(f"Zombie order cancellation failed: {e}")
            else:
                logger.info(f"👤 Manual Order detected (skipped): {order.get('side')} {symbol} (ID: {order_id})")
                
        return cleaned
    
    def _maybe_sweep_dust(self, cycle: int) -> dict[str, Any]:
        """
        Periyodik dust süpürme.
        
        Args:
            cycle: Mevcut cycle
        
        Returns:
            Dust sweep sonucu
        """
        # Her N cycle'da bir
        if cycle - self._last_dust_sweep_cycle < self.dust_sweep_every_n_cycles:
            return {"status": "skipped", "reason": "not_time_yet"}
        
        logger.info("🧹 Dust sweep başlatılıyor (cycle %d)", cycle)
        
        try:
            result = self.exchange_client.sweep_dust(target_asset="BNB")
            self._last_dust_sweep_cycle = cycle
            return result
        except Exception as e:
            logger.error("Dust sweep hatası: %s", e)
            return {"status": "error", "error": str(e)}
    
    def _sync_balances(self) -> dict[str, Any]:
        """Bakiye mutabakatı."""
        try:
            remote_balance = self.exchange_client.get_balance()
            
            # USDT bakiyesini karşılaştır
            local_usdt = self.portfolio.cash
            remote_usdt = remote_balance.get("USDT", 0.0)
            
            # %5 tolerans (commission/slippage farkları için)
            tolerance = 0.05
            diff_pct = abs(remote_usdt - local_usdt) / local_usdt if local_usdt > 0 else 0
            
            if diff_pct > tolerance:
                logger.warning(
                    "⚠️  Balance discrepancy: local=%.2f, remote=%.2f (%.2f%% diff)",
                    local_usdt,
                    remote_usdt,
                    diff_pct * 100,
                )
                return {
                    "status": "discrepancy",
                    "local": local_usdt,
                    "remote": remote_usdt,
                    "diff_pct": diff_pct,
                }
            else:
                logger.debug("Balance sync OK: local=%.2f, remote=%.2f", local_usdt, remote_usdt)
                return {
                    "status": "ok",
                    "local": local_usdt,
                    "remote": remote_usdt,
                }
        
        except Exception as e:
            logger.error("Balance sync failed: %s", e)
            return {"status": "error", "error": str(e)}
    
    def _sync_open_orders(self) -> dict[str, Any]:
        """Açık emir mutabakatı."""
        try:
            # Borsadaki açık emirleri al
            remote_orders = self.exchange_client.get_open_orders()
            
            # Local'de açık emir yok (basit implementation)
            # İleride portfolio'ya open_orders eklenebilir
            
            if remote_orders:
                logger.warning(
                    "⚠️  Found %d open orders on exchange (not tracked locally)",
                    len(remote_orders),
                )
                
                # Zombi emirleri iptal et
                cleaned = self._cancel_zombie_orders(remote_orders)
                
                return {
                    "status": "zombie_cleaned",
                    "remote_orders": len(remote_orders),
                    "cleaned": cleaned,
                }
            else:
                logger.debug("Open orders sync OK: no remote orders")
                return {"status": "ok", "remote_orders": 0}
        
        except Exception as e:
            logger.error("Open orders sync failed: %s", e)
            return {"status": "error", "error": str(e)}
    
    def _cancel_zombie_orders(self, orders: list[dict]) -> int:
        """
        Zombi bot emirlerini iptal eder.
        Manuel emirleri pas geçer.
        """
        cleaned = 0
        
        for order in orders:
            order_id = order.get("id")
            client_id = order.get("clientOrderId") or order.get("info", {}).get("clientOrderId", "")
            symbol = order.get("symbol")
            
            is_bot_order = str(client_id).startswith("llm_")
            
            if is_bot_order:
                logger.warning(
                    "🧟 Zombie Bot Order detected: %s %s (ID: %s, CID: %s)",
                    order.get("side"),
                    symbol,
                    order_id,
                    client_id
                )
                
                try:
                    result = self.exchange_client.cancel_order(order_id, symbol)
                    if result.get("status") == "cancelled":
                        logger.info("Zombie bot order cancelled: %s", order_id)
                        cleaned += 1
                    else:
                        logger.error("Failed to cancel zombie bot order: %s", order_id)
                except Exception as e:
                    logger.error("Zombie bot order cancellation failed (%s): %s", order_id, e)
            else:
                logger.info(
                    "👤 Manual Order detected: %s %s (ID: %s) - Skipping automatic cancellation",
                    order.get("side"),
                    symbol,
                    order_id
                )
        
        return cleaned
    
    def force_sync(self) -> dict[str, Any]:
        """
        Zorla senkronizasyon (cycle sayacına bakmaz).
        Acil durumlarda kullan.
        """
        return self.reconcile(cycle=self._last_reconcile_cycle + 1)


# ── Convenience Function ──────────────────────────────────

def create_sync_manager(
    portfolio: PortfolioState | None = None,
    exchange_client: ExchangeClient | None = None,
    account_manager: Any = None,
) -> SyncManager:
    """SyncManager factory function."""
    return SyncManager(portfolio, exchange_client, account_manager)
