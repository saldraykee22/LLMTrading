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
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import DATA_DIR, get_trading_params

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = DATA_DIR / "portfolio_state.json"
PORTFOLIO_DB = DATA_DIR / "portfolio_state.db"
# NOT: Global kilit kaldırıldı, artık PortfolioState._lock (instance-level) kullanılıyor.

# ── Backward-compatible shim (test uyumluluğu için) ──────
# Yeni kodda KULLANMAYIN — sadece eski testlerin çalışması için.
_portfolio_lock = threading.RLock()


def _acquire_portfolio_lock(timeout: float = -1) -> bool:
    """Test uyumluluğu için. Yeni kodda portfolio._lock kullanın."""
    return _portfolio_lock.acquire(
        blocking=True, timeout=timeout if timeout > 0 else -1
    )


def _release_portfolio_lock() -> None:
    """Test uyumluluğu için. Yeni kodda portfolio._lock kullanın."""
    _portfolio_lock.release()


@dataclass
class Position:
    """Tek bir açık pozisyon (DCA desteği ile)."""

    symbol: str
    entry_price: float
    amount: float  # Şu an alınan miktar (current_size)
    entry_time: str
    side: str = "long"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    # DCA (Kademeli Alım-Satım) alanları
    target_size: float = 0.0  # Hedeflenen toplam miktar
    target_size_usd: float = 0.0  # Hedeflenen toplam USD değeri
    executed_tranches: int = 0  # Kaç kademe执行 edildi
    remaining_size: float = 0.0  # Kalan tahsis (target - current)

    def __post_init__(self) -> None:
        """Position validation - invalid values exception fırlat."""
        from config.constants import MIN_PRICE, MIN_AMOUNT, MAX_PRICE, MAX_AMOUNT
        
        # Side validation
        if self.side != "long":
            raise ValueError(f"SPOT only supports long positions, got: {self.side}")
        
        # Symbol validation
        if not self.symbol or not isinstance(self.symbol, str):
            raise ValueError(f"Invalid symbol: {self.symbol}")
        if len(self.symbol) > 50:
            raise ValueError(f"Symbol too long (max 50 chars): {self.symbol[:20]}...")
        
        # Price validation (entry_price)
        if not isinstance(self.entry_price, (int, float)):
            raise ValueError(f"entry_price must be numeric: {self.entry_price}")
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be positive: {self.entry_price}")
        if self.entry_price < MIN_PRICE:
            raise ValueError(f"entry_price below minimum ({MIN_PRICE}): {self.entry_price}")
        if self.entry_price > MAX_PRICE:
            raise ValueError(f"entry_price above maximum ({MAX_PRICE}): {self.entry_price}")
        
        # Amount validation
        if not isinstance(self.amount, (int, float)):
            raise ValueError(f"amount must be numeric: {self.amount}")
        if self.amount <= 0:
            raise ValueError(f"amount must be positive: {self.amount}")
        if self.amount < MIN_AMOUNT:
            raise ValueError(f"amount below minimum ({MIN_AMOUNT}): {self.amount}")
        if self.amount > MAX_AMOUNT:
            raise ValueError(f"amount above maximum ({MAX_AMOUNT}): {self.amount}")
        
        # Stop-loss validation (non-negative)
        if not isinstance(self.stop_loss, (int, float)):
            raise ValueError(f"stop_loss must be numeric: {self.stop_loss}")
        if self.stop_loss < 0:
            raise ValueError(f"stop_loss cannot be negative: {self.stop_loss}")
        
        # Take-profit validation (non-negative)
        if not isinstance(self.take_profit, (int, float)):
            raise ValueError(f"take_profit must be numeric: {self.take_profit}")
        if self.take_profit < 0:
            raise ValueError(f"take_profit cannot be negative: {self.take_profit}")
        
        # Current price validation (non-negative)
        if not isinstance(self.current_price, (int, float)):
            raise ValueError(f"current_price must be numeric: {self.current_price}")
        if self.current_price < 0:
            raise ValueError(f"current_price cannot be negative: {self.current_price}")
        
        # DCA alanları otomatik doldur (eğer verilmemişse)
        if self.target_size <= 0:
            self.target_size = self.amount
        if self.target_size_usd <= 0:
            self.target_size_usd = self.amount * self.entry_price
        if self.remaining_size <= 0:
            self.remaining_size = self.target_size - self.amount
        
        # Entry time validation
        if not self.entry_time:
            raise ValueError("entry_time is required")

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
    
    def add_tranche(self, amount: float, price: float) -> None:
        """
        DCA kademesi ekle.
        
        Args:
            amount: Eklenen miktar
            price: Giriş fiyatı
        """
        old_amount = self.amount
        old_cost = old_amount * self.entry_price
        new_cost = amount * price
        
        # Ağırlıklı ortalama fiyat hesapla
        total_amount = old_amount + amount
        if total_amount > 0:
            self.entry_price = (old_cost + new_cost) / total_amount
        
        self.amount = total_amount
        self.executed_tranches += 1
        self.remaining_size = max(0, self.target_size - self.amount)
        self.current_price = price
        
        # P&L sıfırla (yeni ortalama ile yeniden hesaplanacak)
        self.unrealized_pnl = 0.0
        self.unrealized_pnl_pct = 0.0
        
        logger.info(
            "DCA kademesi eklendi: %s +%d @ %.4f (Ortalama: %.4f, Kalan: %.4f)",
            self.symbol, amount, price, self.entry_price, self.remaining_size
        )
    
    def is_dca_complete(self) -> bool:
        """DCA tamamlandı mı?"""
        return self.remaining_size <= 0 or self.amount >= self.target_size


def _position_from_dict(d: dict) -> Position:
    """Dict'ten Position oluşturur (DCA alanları ile)."""
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
        target_size=d.get("target_size", 0.0),
        target_size_usd=d.get("target_size_usd", 0.0),
        executed_tranches=d.get("executed_tranches", 0),
        remaining_size=d.get("remaining_size", 0.0),
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
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        """daily_pnl_date boşsa bugünün tarihini ata, cash ve max_equity'yi initial_cash'e eşitle."""
        if not self.daily_pnl_date:
            self.daily_pnl_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # cash ve max_equity'yi initial_cash'e eşitle (loaded state override'ını önle)
        # Sorun: cash=10000 default iken initial_cash farklıysa, cash override edilmiyordu
        # Çözüm: cash/max_equity default değerindeyse her zaman initial_cash'e eşitle
        if self.cash == 10000.0:
            self.cash = self.initial_cash
        if self.max_equity == 10000.0:
            self.max_equity = self.initial_cash

    # ── Persistence ────────────────────────────────────────

    def save_to_file(self, path: Path | None = None) -> None:
        """Portföy durumunu SQLite (ve JSON) dosyasına kaydet."""
        with self._lock:
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
            
            json_data = json.dumps(data, ensure_ascii=False, indent=2)
            
            # DB path belirle
            if path and path.suffix == '.json':
                db_path = path.with_suffix('.db')
            else:
                db_path = filepath.with_suffix('.db') if filepath.name == 'portfolio_state.json' else filepath
                if not db_path.name.endswith('.db') and not db_path.name.endswith('.json'):
                    db_path = db_path.with_suffix('.db')
            
            # SQLite Kaydı (Asıl koruma)
            try:
                conn = sqlite3.connect(db_path, timeout=20.0)
                try:
                    with conn:
                        conn.execute("CREATE TABLE IF NOT EXISTS portfolio_state (id INTEGER PRIMARY KEY, state_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                        conn.execute("INSERT OR REPLACE INTO portfolio_state (id, state_json) VALUES (1, ?)", (json_data,))
                finally:
                    conn.close()
            except Exception as exc:
                logger.error("SQLite yazma hatası, fallback JSON: %s", exc)

            # JSON Kaydı (Dashboard/Geriye dönük uyumluluk)
            tmp_path = filepath.with_suffix(".tmp")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except (PermissionError, OSError):
                pass
            
            try:
                tmp_path.write_text(json_data, encoding="utf-8")
                for attempt in range(5):
                    try:
                        os.replace(tmp_path, filepath)
                        break
                    except (PermissionError, FileNotFoundError, OSError):
                        if attempt == 4:
                            filepath.write_text(json_data, encoding="utf-8")
                            break
                        time.sleep(0.1 * (2 ** attempt))
            except Exception as exc:
                logger.warning("JSON update failed: %s", exc)

            logger.info("Portföy kaydedildi: %s (equity: %.2f)", filepath, self.equity)

    @classmethod
    def load_from_file(cls, path: Path | None = None) -> "PortfolioState":
        """SQLite dosyasından (yoksa JSON'dan) portföy durumunu yükle."""
        filepath = path or PORTFOLIO_FILE
        
        # DB path belirle
        if path and path.suffix == '.json':
            db_path = path.with_suffix('.db')
        else:
            db_path = filepath.with_suffix('.db') if filepath.name == 'portfolio_state.json' else filepath
            if not db_path.name.endswith('.db') and not db_path.name.endswith('.json'):
                db_path = db_path.with_suffix('.db')

        json_text = None
        
        # 1. SQLite'dan dene
        if db_path.exists():
            try:
                with sqlite3.connect(db_path, timeout=20.0) as conn:
                    cursor = conn.execute("SELECT state_json FROM portfolio_state WHERE id=1")
                    row = cursor.fetchone()
                    if row:
                        json_text = row[0]
            except Exception as e:
                logger.error("SQLite okuma hatası: %s", e)

        # 2. SQLite'da yoksa JSON'a bak
        if not json_text and filepath.exists():
            try:
                json_text = filepath.read_text(encoding="utf-8")
            except Exception as e:
                logger.error("JSON okuma hatası: %s", e)

        if not json_text:
            logger.info("Portföy dosyası/veritabanı bulunamadı, yeni portföy oluşturuluyor")
            return cls()

        try:
            data = json.loads(json_text)
            positions = [_position_from_dict(p) for p in data.get("positions", [])]
            state = cls(
                initial_cash=data.get("initial_cash", 10000.0),
                cash=data.get("cash", 10000.0),
                positions=positions,
                closed_trades=data.get("closed_trades", [])[-1000:],
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
        with self._lock:
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

    # ── Dust Management ────────────────────────────────────
    
    DUST_THRESHOLD_USDT = 1.0  # $1 altı dust olarak kabul edilir
    
    def get_dust_balances(self, balance_data: dict[str, float]) -> dict[str, float]:
        """
        Dust bakiyeleri filtrele ($1 altı).
        
        Args:
            balance_data: {asset: amount} formatında bakiye
        
        Returns:
            Dust bakiyeler (threshold altı)
        """
        if not balance_data:
            return {}
        
        # USDT fiyatlarını almak için market data
        try:
            from data.market_data import MarketDataClient
            market = MarketDataClient()
            tickers = market.fetch_tickers()
        except Exception as e:
            logger.warning("Dust filtreleme için ticker alınamadı: %s", e)
            return {}
        
        dust_balances = {}
        
        for asset, amount in balance_data.items():
            if asset in ["USDT", "BNB"]:  # USDT ve BNB'yi temizleme
                continue
            
            # USDT paritesi bul
            symbol = f"{asset}/USDT"
            
            if symbol not in tickers:
                # BTC paritesini dene
                symbol = f"{asset}/BTC"
                if symbol not in tickers:
                    continue
                
                # Çapraz hesaplama
                btc_usdt = tickers.get("BTC/USDT", {})
                btc_price = float(btc_usdt.get('last', 0) or 0)
                asset_btc = float(tickers[symbol].get('last', 0) or 0)
                usdt_price = btc_price * asset_btc
            else:
                usdt_price = float(tickers[symbol].get('last', 0) or 0)
            
            # USD değeri
            usdt_value = amount * usdt_price
            
            if usdt_value < self.DUST_THRESHOLD_USDT and usdt_value > 0:
                dust_balances[asset] = amount
                logger.debug(
                    "🔍 Dust: %s = %.4f (%.2f USDT)",
                    asset, amount, usdt_value
                )
        
        return dust_balances
    
    def filter_dust_from_balance(self, balance_data: dict[str, float]) -> dict[str, float]:
        """
        Bakiyeden dust'ları çıkar (tradable equity için).
        
        Args:
            balance_data: {asset: amount}
        
        Returns:
            Dust temizlenmiş bakiye
        """
        dust = self.get_dust_balances(balance_data)
        dust_assets = set(dust.keys())
        
        return {
            asset: amount
            for asset, amount in balance_data.items()
            if asset not in dust_assets
        }
    
    # ── Equity & Drawdown ──────────────────────────────────

    @property
    def equity(self) -> float:
        """Toplam özvarlık (nakit + açık pozisyonlar)."""
        with self._lock:
            position_value = sum(p.current_price * p.amount for p in self.positions)
            return self.cash + position_value

    @property
    def open_position_count(self) -> int:
        with self._lock:
            return len(self.positions)

    def update_drawdown(self) -> None:
        """Drawdown günceller."""
        with self._lock:
            eq = self.equity
            if eq > self.max_equity:
                self.max_equity = eq
            if self.max_equity > 0:
                self.current_drawdown = (self.max_equity - eq) / self.max_equity

    def update_benchmark(
        self, market_data: pd.DataFrame, benchmark_symbol: str | None = None
    ) -> float:
        """Benchmark getirisini ve alpha'yı hesaplar - thread-safe."""
        with self._lock:
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
        exchange_client: Any = None,
    ) -> float:
        """
        Pozisyon boyutunu hesaplar.

        Args:
            price: Giriş fiyatı
            risk_per_trade: İşlem başına risk oranı (varsayılan: YAML'den)
            exchange_client: Canlı bakiye çekmek için opsiyonel borsa istemcisi

        Returns:
            Alınabilecek miktar (amount)
        """
        params = get_trading_params()
        risk_pct = risk_per_trade or params.risk.max_position_pct
        
        # Thread-safe cash okuma
        with self._lock:
            current_cash = self.cash
        
        # Canlı bakiye kullan (eğer live mode ve client sağlandıysa)
        if exchange_client and params.execution.mode.value == "live":
            try:
                balance = exchange_client.get_balance()
                current_cash = balance.get("USDT", current_cash)
                logger.debug("Sizing using live USDT balance: %.2f", current_cash)
            except Exception as e:
                logger.error("Could not fetch live balance for sizing, falling back to local: %s", e)

        max_value = current_cash * risk_pct

        if price <= 0:
            return 0.0

        return max_value / price

    # ── Serialization ──────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serileştirme (ajan state'e gönderim için)."""
        with self._lock:
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
                        "target_size": p.target_size,
                        "target_size_usd": p.target_size_usd,
                        "remaining_size": p.remaining_size,
                        "executed_tranches": p.executed_tranches,
                        "unrealized_pnl": round(p.unrealized_pnl, 4),
                        "dca_complete": p.is_dca_complete(),
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
        # DCA parametreleri
        target_size: float = 0.0,
        target_size_usd: float = 0.0,
    ) -> Position | None:
        """
        Yeni pozisyon açar (DCA desteği ile).
        
        Args:
            target_size: Hedeflenen toplam miktar (DCA için)
            target_size_usd: Hedeflenen toplam USD değeri (DCA için)
        """
        with self._lock:
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

            # Korelasyon kontrolü - Lock içinde verileri hazırla, 
            # kontrolü lock DIŞINDA yap (deadlock önleme)
            market_data_copy = None
            positions_symbols = None
            positions_for_check = None
            if (
                max_correlation is not None
                and market_data is not None
                and self.positions
            ):
                # Market data ve positions kopyasını lock içinde al
                market_data_copy = {
                    k: v.copy() if isinstance(v, pd.DataFrame) else v
                    for k, v in market_data.items()
                }
                positions_symbols = [p.symbol for p in self.positions]
                # Position referanslarını da lock içinde al (başka thread 
                # değiştirmesin diye listeyi kopyala)
                positions_for_check = list(self.positions)

        # ── Lock DIŞINDA: Correlation check (deadlock önleme) ────────────────
        # CorrelationChecker başka bir lock almaya çalışırsa deadlock oluşmaz
        if positions_symbols is not None and market_data_copy is not None:
            from risk.correlation_checker import CorrelationChecker

            checker = CorrelationChecker([], market_data_copy)
            symbols_to_check = positions_symbols + [symbol]
            available = {
                s: market_data_copy[s]
                for s in symbols_to_check
                if s in market_data_copy
            }
            if len(available) >= 2:
                # Lock içinde alınan pozisyon kopyasını kullan
                filtered_positions = [
                    p for p in positions_for_check if p.symbol in available
                ]
                
                check_result = checker.check_positions(
                    filtered_positions,
                    market_data_copy,
                    max_correlation=max_correlation,
                )
                if not check_result["is_safe"]:
                    logger.warning(
                        "Pozisyon reddedildi: yüksek korelasyon tespit edildi. %s",
                        check_result["correlated_pairs"],
                    )
                    return None

        # ── Tekrar Lock Al: Pozisyon açma ────────────────────────────────────
        with self._lock:
            # TOCTOU Kontrolü: Lock serbestken bakiye veya pozisyon sayısı değişmiş olabilir
            cost = price * amount
            if cost > self.cash:
                logger.warning("Yetersiz bakiye (TOCTOU): %.2f > %.2f", cost, self.cash)
                return None
            
            if len(self.positions) >= params.risk.max_open_positions:
                logger.warning("Max pozisyon sayısı aşıldı (TOCTOU): %d", len(self.positions))
                return None

            # DCA parametrelerini işle
            if target_size <= 0:
                target_size = amount
            if target_size_usd <= 0:
                target_size_usd = cost
            
            remaining_size = target_size - amount
            
            position = Position(
                symbol=symbol,
                side=side,
                entry_price=price,
                amount=amount,
                entry_time=datetime.now(timezone.utc).isoformat(),
                stop_loss=stop_loss,
                take_profit=take_profit,
                current_price=price,
                # DCA alanları
                target_size=target_size,
                target_size_usd=target_size_usd,
                executed_tranches=1,
                remaining_size=remaining_size,
            )

            self.cash -= cost
            self.positions.append(position)
            
            # Anlık kaydet (Elektrik kesintisine karşı)
            self.save_to_file()

            logger.info(
                "Pozisyon açıldı: %s %s %.4f @ %.4f (SL: %.4f, TP: %.4f, DCA: %d/%d)",
                side.upper(),
                symbol,
                amount,
                price,
                stop_loss,
                take_profit,
                position.executed_tranches,
                position.target_size,
            )
            return position

    def close_position(self, symbol: str, price: float) -> dict | None:
        """Pozisyonu kapatır. Thread-safe."""
        with self._lock:
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
            
            # Limit history to prevent unbounded growth
            if len(self.closed_trades) > 1000:
                self.closed_trades = self.closed_trades[-1000:]

            logger.info(
                "Pozisyon kapatıldı: %s P&L: %.4f (%.2f%%)",
                symbol,
                pnl,
                pos.unrealized_pnl_pct * 100,
            )
            self.update_drawdown()
            self.save_to_file()
            return trade_record

    # ── DCA (Kademeli Alım-Satım) ─────────────────────────

    def add_dca_tranche(
        self,
        symbol: str,
        amount: float,
        price: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> Position | None:
        """
        Mevcut pozisyona DCA kademesi ekler.
        
        Args:
            symbol: Sembol
            amount: Eklenecek miktar
            price: Giriş fiyatı
            stop_loss: Yeni stop-loss (opsiyonel, 0 ise mevcut kullanılır)
            take_profit: Yeni take-profit (opsiyonel, 0 ise mevcut kullanılır)
        
        Returns:
            Güncellenen Position veya None (pozisyon bulunamazsa)
        """
        with self._lock:
            pos = next((p for p in self.positions if p.symbol == symbol), None)
            if not pos:
                logger.warning("DCA için pozisyon bulunamadı: %s", symbol)
                return None
            
            # Kalan tahsis kontrolü
            if pos.remaining_size <= 0:
                logger.warning(
                    "DCA reddedildi: %s için kalan tahsis yok (remaining: %.4f)",
                    symbol, pos.remaining_size
                )
                return None
            
            # Nakit kontrolü (önce - miktar düşürmeden)
            cost = price * amount
            if cost > self.cash:
                logger.warning(
                    "Yetersiz bakiye (DCA): %.2f > %.2f (istenen: %.4f @ %.4f)",
                    cost, self.cash, amount, price
                )
                return None
            
            # Miktar kontrolü (kalan tahsisi aşmasın)
            original_amount = amount
            if amount > pos.remaining_size:
                adjusted_amount = pos.remaining_size
                logger.info(
                    "⚠️  DCA miktarı %.4f → %.4f'ye düşürüldü (kalan tahsis: %.4f)",
                    original_amount, adjusted_amount, pos.remaining_size
                )
                amount = adjusted_amount
                
                # Miktar düşürüldü, tekrar nakit kontrolü
                cost = price * amount
                if cost > self.cash:
                    logger.warning(
                        "DCA miktarı düşürüldü ama hala yetersiz bakiye: %.2f > %.2f",
                        self.cash, cost
                    )
                    return None
            
            # SL/TP güncelle (eğer yeni değerler verildiyse)
            if stop_loss > 0:
                pos.stop_loss = stop_loss
            if take_profit > 0:
                pos.take_profit = take_profit
            
            # Kademe ekle
            pos.add_tranche(amount, price)
            
            # Nakit düş
            self.cash -= cost
            
            # Anlık kaydet
            self.save_to_file()
            
            logger.info(
                "✅ DCA kademesi eklendi: %s +%d @ %.4f (Toplam: %.4f, Kalan: %.4f)",
                symbol, amount, price, pos.amount, pos.remaining_size
            )
            
            return pos
    
    # ── Thread-Safe API ────────────────────────────────────

    def get_positions_safe(self) -> list[Position]:
        """Thread-safe pozisyon kopyası döndürür."""
        with self._lock:
            return list(self.positions)

    def get_position_by_symbol_safe(self, symbol: str) -> Position | None:
        """Thread-safe tek pozisyon alma."""
        with self._lock:
            return next((p for p in self.positions if p.symbol == symbol), None)

    def remove_position_safe(self, symbol: str) -> Position | None:
        """Thread-safe pozisyon kaldırma (kapanan pozisyon için)."""
        with self._lock:
            for i, p in enumerate(self.positions):
                if p.symbol == symbol:
                    return self.positions.pop(i)
            return None

    def close_position_safe(self, symbol: str, price: float) -> dict | None:
        """Thread-safe pozisyon kapatma."""
        with self._lock:
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
            
            # Limit history to prevent unbounded growth
            if len(self.closed_trades) > 1000:
                self.closed_trades = self.closed_trades[-1000:]

            logger.info(
                "Pozisyon kapatıldı (thread-safe): %s P&L: %.4f (%.2f%%)",
                symbol,
                pnl,
                pos.unrealized_pnl_pct * 100,
            )
            self.update_drawdown()
            self.save_to_file() # Anlık kaydet
            return trade_record

    # ── Exchange Sync ──────────────────────────────────────

    def sync_with_exchange(self, exchange_client: Any) -> None:
        """
        Borsa bakiyesi ile yerel state'i senkronize eder.
        Restart sonrası veya elektrik kesintisi sonrası tutarlılık sağlar.
        """
        params = get_trading_params()
        if params.execution.mode.value != "live":
            logger.info("Sync skipped: Not in live mode")
            return

        logger.info("🔄 Borsa ile portföy senkronizasyonu başlatılıyor...")
        
        # Ağ isteğini _portfolio_lock DIŞINDA yapıyoruz
        try:
            balance = exchange_client.get_balance()
        except Exception as e:
            logger.error("Senkronizasyon sırasında ağ hatası (bakiye çekilemedi): %s", e)
            return

        with self._lock:
            try:
                # 1. Nakit (USDT) senkronizasyonu
                if "USDT" in balance:
                    old_cash = self.cash
                    self.cash = balance["USDT"]
                    if abs(old_cash - self.cash) > 1.0:
                        logger.warning("Bakiye senkronize edildi: %.2f -> %.2f USDT", old_cash, self.cash)

                # 2. Açık pozisyon kontrolü
                active_symbols = [p.symbol for p in self.positions]
                for symbol in active_symbols:
                    # Sembol borsa formatına (BTC/USDT -> BTC)
                    base_currency = symbol.split("/")[0]
                    actual_amount = balance.get(base_currency, 0.0)
                    
                    # Zaten lock içindeyiz, direkt arama yap (redundant lock önleme)
                    pos = next((p for p in self.positions if p.symbol == symbol), None)
                    if not pos:
                        continue

                    if actual_amount < pos.amount * 0.98:  # %2 pay payı (komisyon vb)
                        logger.error(
                            "Kritik Uyumsuzluk: %s JSON'da var ama borsada eksik! (%.4f vs %.4f). Pozisyon kaldırılıyor.",
                            symbol, pos.amount, actual_amount
                        )
                        self.positions.remove(pos)
                    else:
                        logger.info("Pozisyon doğrulandı: %s (Miktar: %.4f)", symbol, actual_amount)
                
                self.save_to_file()
                logger.info("✅ Portföy senkronizasyonu tamamlandı.")

            except Exception as e:
                logger.error("Senkronizasyon (lock içi) sırasında hata: %s", e)
