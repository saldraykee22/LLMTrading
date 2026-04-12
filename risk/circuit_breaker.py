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

import logging
from pathlib import Path

from config.settings import DATA_DIR, get_trading_params

logger = logging.getLogger(__name__)

STOP_FILE = DATA_DIR / "STOP"


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

    def should_halt(self, equity: float, daily_pnl: float) -> tuple[bool, str]:
        """
        Durdurma gerekip gerekmediğini kontrol eder.

        Args:
            equity: Güncel özvarlık
            daily_pnl: Günlük P&L

        Returns:
            (durdurulsun_mu, sebep)
        """
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

        return False, ""

    def record_trade_result(self, pnl: float) -> None:
        """İşlem sonucunu kaydeder."""
        if pnl < 0:
            self.consecutive_losses += 1
            logger.warning("Art arda kayıp sayacı: %d", self.consecutive_losses)
        else:
            if self.consecutive_losses > 0:
                logger.info(
                    "Art arda kayıp zinciri kırıldı (%d kayıp sonrası kâr)",
                    self.consecutive_losses,
                )
            self.consecutive_losses = 0

    def record_llm_error(self) -> None:
        """LLM hatasını kaydeder."""
        self.consecutive_llm_errors += 1
        logger.warning("Art arda LLM hata sayacı: %d", self.consecutive_llm_errors)

    def reset_llm_errors(self) -> None:
        """LLM hata sayacını sıfırlar."""
        self.consecutive_llm_errors = 0

    def reset_consecutive_losses(self) -> None:
        """Art arda kayıp sayacını sıfırlar."""
        self.consecutive_losses = 0

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
