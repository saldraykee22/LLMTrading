"""
Circuit Breaker / Kill Switch
===============================
Acil durdurma mekanizması:
- Art arda N kayıp işlem → tüm işlemleri durdur
- Günlük kayıp limiti aşımı → pozisyonları kapat
- LLM API ardışık hataları → pipeline durdur
- Manuel durdurma için data/STOP dosyası
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from config.settings import DATA_DIR, get_trading_params

logger = logging.getLogger(__name__)

STOP_FILE = DATA_DIR / "STOP"
STATE_FILE = DATA_DIR / "circuit_breaker_state.json"


class CircuitBreaker:
    """
    Acil durdurma devre kesicisi.

    Kullanım:
        cb = CircuitBreaker()
        should_halt, reason = cb.should_halt(portfolio)
        if should_halt:
            logger.critical(reason)
            return

        # Her işlem sonrası
        cb.record_trade_result(pnl)

        # Her LLM hatasında
        cb.record_llm_error()
    """

    def __init__(self) -> None:
        self._params = get_trading_params()
        self.consecutive_losses = 0
        self.consecutive_llm_errors = 0
        self.consecutive_rate_limits = 0
        self._notified_halt = False
        self._load_state()
    
    def _save_state(self) -> None:
        """Durumu diske kaydet - her sayaç değişiminde çağrılır."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "consecutive_losses": self.consecutive_losses,
                "consecutive_llm_errors": self.consecutive_llm_errors,
                "consecutive_rate_limits": self.consecutive_rate_limits,
                "timestamp": time.time(),
            }
            STATE_FILE.write_text(json.dumps(data, indent=2))
            logger.debug("Circuit breaker state saved")
        except Exception as e:
            logger.warning("State save failed: %s", e)
    
    def _load_state(self) -> None:
        """Diskten durum yükle - sadece son 1 saat içindeki state'i kabul et."""
        if not STATE_FILE.exists():
            logger.debug("No circuit breaker state file found")
            return
        
        try:
            data = json.loads(STATE_FILE.read_text())
            last_update = data.get("timestamp", 0)
            
            # Sadece son 1 saat içindeki hataları yükle (3600 saniye)
            if time.time() - last_update < 3600:
                self.consecutive_losses = data.get("consecutive_losses", 0)
                self.consecutive_llm_errors = data.get("consecutive_llm_errors", 0)
                self.consecutive_rate_limits = data.get("consecutive_rate_limits", 0)
                logger.info(
                    "Circuit breaker state loaded (age: %.0f minutes)",
                    (time.time() - last_update) / 60,
                )
            else:
                logger.info("Circuit breaker state too old, ignoring")
        except Exception as e:
            logger.warning("State load failed: %s", e)

    def _send_notification(self, title: str, message: str) -> None:
        """Webhook/Telegram bildirim taslağı (Stub)."""
        logger.critical(f"🔔 [BİLDİRİM] {title}: {message}")
        # TODO: Implement actual webhook call here (e.g. requests.post)

    def should_halt(self, equity: float, daily_pnl: float) -> tuple[bool, str]:
        """
        Durdurma gerekip gerekmediğini kontrol eder ve durum değişirse bildirim gönderir.
        """
        is_halt, reason = self._check_halt_conditions(equity, daily_pnl)
        
        if is_halt and not self._notified_halt:
            self._send_notification("CIRCUIT BREAKER DEVREDE", reason)
            self._notified_halt = True
        elif not is_halt and self._notified_halt:
            self._notified_halt = False
            self._send_notification("SİSTEM NORMALE DÖNDÜ", "Circuit Breaker kaldırıldı.")
            
        return is_halt, reason

    def _check_halt_conditions(self, equity: float, daily_pnl: float) -> tuple[bool, str]:
        # 1. Manuel durdurma
        if STOP_FILE.exists():
            return True, "Manuel durdurma aktif (data/STOP dosyası mevcut)"

        # 2. Art arda kayıp
        max_losses = self._params.risk.max_consecutive_losses
        if max_losses > 0 and self.consecutive_losses >= max_losses:
            return (
                True,
                f"Art arda {self.consecutive_losses} kayıp işlem (limit: {max_losses})",
            )

        # 3. Günlük kayıp limiti
        if equity > 0:
            daily_loss = abs(min(daily_pnl, 0))
            daily_loss_pct = daily_loss / equity
            max_daily = self._params.risk.max_daily_loss_pct
            if max_daily > 0 and daily_loss_pct >= max_daily:
                return True, (
                    f"Günlük kayıp limiti aşıldı: {daily_loss_pct:.2%} >= {max_daily:.2%}"
                )

        # 4. LLM ardışık hataları
        max_llm_errors = self._params.risk.max_consecutive_llm_errors
        if max_llm_errors > 0 and self.consecutive_llm_errors >= max_llm_errors:
            return True, (
                f"LLM ardışık hata limiti: {self.consecutive_llm_errors}/{max_llm_errors}"
            )

        # 5. API Rate Limit hataları
        if self.consecutive_rate_limits >= 3:
            return True, f"API Rate Limit ardışık hata limiti aşıldı: {self.consecutive_rate_limits}/3"

        return False, ""

    def record_trade_result(self, pnl: float) -> None:
        """İşlem sonucunu kaydeder."""
        if pnl < 0:
            self.consecutive_losses += 1
            logger.warning("Art arda kayıp sayacı: %d", self.consecutive_losses)
            self._save_state()
        else:
            if self.consecutive_losses > 0:
                logger.info(
                    "Art arda kayıp zinciri kırıldı (%d kayıp sonrası kâr)",
                    self.consecutive_losses,
                )
            self.consecutive_losses = 0
            self._save_state()

    def record_llm_error(self) -> None:
        """LLM hatasını kaydeder."""
        self.consecutive_llm_errors += 1
        logger.warning("Art arda LLM hata sayacı: %d", self.consecutive_llm_errors)
        self._save_state()

    def record_api_rate_limit(self) -> None:
        """API rate limit hatasını kaydeder."""
        self.consecutive_rate_limits += 1
        logger.warning("Art arda Rate Limit hata sayacı: %d", self.consecutive_rate_limits)
        self._save_state()

    def reset_api_rate_limit(self) -> None:
        self.consecutive_rate_limits = 0
        self._save_state()

    def reset_llm_errors(self) -> None:
        """LLM hata sayacını sıfırlar."""
        self.consecutive_llm_errors = 0
        self._save_state()

    def reset_consecutive_losses(self) -> None:
        """Art arda kayıp sayacını sıfırlar."""
        self.consecutive_losses = 0
        self._save_state()

    @staticmethod
    def manual_stop() -> None:
        """Manuel durdurma dosyası oluşturur."""
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
        logger.critical("Manuel durdurma aktif edildi (data/STOP oluşturuldu)")

    def resume(self) -> None:
        """Manuel durdurmayı kaldırır ve sayaçları sıfırlar."""
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        self.consecutive_losses = 0
        self.consecutive_llm_errors = 0
        logger.info("Manuel durdurma kaldırıldı ve sayaçlar sıfırlandı")

    def get_status(self) -> dict:
        """Circuit breaker durumu."""
        halted, reason = self.should_halt(equity=0, daily_pnl=0)
        return {
            "halted": halted or STOP_FILE.exists(),
            "halt_reason": reason if halted else "",
            "consecutive_losses": self.consecutive_losses,
            "consecutive_llm_errors": self.consecutive_llm_errors,
            "stop_file_exists": STOP_FILE.exists(),
        }
