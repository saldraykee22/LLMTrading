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
import threading
import time

from config.settings import DATA_DIR, get_settings, get_trading_params
from risk.system_status import SystemStatus

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
        self.consecutive_fallbacks = 0  # ✅ YENİ: Fallback sayacı
        self._notified_halt = False
        self._lock = threading.RLock()  # Kilitlenmeyi önlemek için RLock kullanıyoruz
        if self._params.system.reset_counters_on_startup:
            logger.info("Circuit breaker counters reset on startup")
            return
        self._load_state()
    
    def _save_state(self) -> None:
        """Durumu diske kaydet - her sayaç değişiminde çağrılır (caller must hold lock)."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "consecutive_losses": self.consecutive_losses,
                "consecutive_llm_errors": self.consecutive_llm_errors,
                "consecutive_rate_limits": self.consecutive_rate_limits,
                "consecutive_fallbacks": self.consecutive_fallbacks,  # ✅ YENİ
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
            
            with self._lock:
                ttl = self._params.system.circuit_breaker_state_ttl
                if time.time() - last_update < ttl:
                    self.consecutive_losses = data.get("consecutive_losses", 0)
                    self.consecutive_llm_errors = data.get("consecutive_llm_errors", 0)
                    self.consecutive_rate_limits = data.get("consecutive_rate_limits", 0)
                    self.consecutive_fallbacks = data.get("consecutive_fallbacks", 0)  # ✅ YENİ
                    logger.info(
                        "Circuit breaker state loaded (age: %.0f minutes)",
                        (time.time() - last_update) / 60,
                    )
                else:
                    logger.info("Circuit breaker state too old, ignoring")
        except Exception as e:
            logger.warning("State load failed: %s", e)

    def _send_notification(self, title: str, message: str) -> None:
        """Telegram bildirimini gönderir."""
        settings = get_settings()
        bot_token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id

        logger.critical(f"🔔 [BİLDİRİM] {title}: {message}")

        if not bot_token or not chat_id:
            logger.debug("Telegram bildirimleri devre dışı (token veya chat_id eksik)")
            return

        try:
            import httpx
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": f"🚨 *{title}*\n\n{message}",
                "parse_mode": "Markdown",
            }
            # Senkron httpx çağrısı (timeout 5s)
            with httpx.Client(timeout=5.0) as client:
                response = client.post(url, json=payload)
                if response.status_code != 200:
                    logger.error(
                        "Telegram bildirimi gönderilemedi: %s %s",
                        response.status_code,
                        response.text,
                    )
        except Exception as e:
            logger.error("Telegram bildirim hatası: %s", e)

    def should_halt(self, equity: float, daily_pnl: float) -> tuple[bool, str]:
        """
        Durdurma gerekip gerekmediğini kontrol eder ve durum değişirse bildirim gönderir.
        SystemStatus ile entegre çalışır.
        """
        is_halt, reason = self._check_halt_conditions(equity, daily_pnl)

        # SystemStatus ile senkronize et
        system_status = SystemStatus.get_instance()
        if is_halt and system_status.is_running():
            # Circuit breaker tetiklendi → SystemStatus'u güncelle
            system_status.emergency_stop(reason)

        # Thread-safe _notified_halt kontrolü
        with self._lock:
            should_notify = is_halt and not self._notified_halt
            should_reset = not is_halt and self._notified_halt
            if should_notify:
                self._notified_halt = True
            elif should_reset:
                self._notified_halt = False

        if should_notify:
            self._send_notification("CIRCUIT BREAKER DEVREDE", reason)
        elif should_reset:
            # SystemStatus'u da sıfırla
            if system_status.is_emergency():
                system_status.resume()
            self._send_notification("SİSTEM NORMALE DÖNDÜ", "Circuit Breaker kaldırıldı.")

        return is_halt, reason

    def _check_halt_conditions(self, equity: float, daily_pnl: float) -> tuple[bool, str]:
        with self._lock:
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
            effective_equity = equity if equity > 0 else self._params.backtest.initial_cash
            if effective_equity > 0:
                daily_loss = abs(min(daily_pnl, 0))
                daily_loss_pct = daily_loss / effective_equity
                max_daily = self._params.risk.max_daily_loss_pct
                if max_daily > 0 and daily_loss_pct >= max_daily:
                    return True, (
                        f"Günlük kayıp limiti aşıldı: {daily_loss_pct:.2%} >= {max_daily:.2%} (equity={equity:.2f})"
                    )

            # 4. LLM ardışık hataları
            max_llm_errors = self._params.risk.max_consecutive_llm_errors
            if max_llm_errors > 0 and self.consecutive_llm_errors >= max_llm_errors:
                return True, (
                    f"LLM ardışık hata limiti: {self.consecutive_llm_errors}/{max_llm_errors}"
                )

            # 5. API Rate Limit hataları
            max_rate_limits = self._params.system.rate_limit_consecutive_threshold
            if self.consecutive_rate_limits >= max_rate_limits:
                return True, f"API Rate Limit ardışık hata limiti aşıldı: {self.consecutive_rate_limits}/{max_rate_limits}"

            # 6. Fallback limit kontrolü (YENİ)
            max_fallbacks = self._params.system.max_consecutive_fallbacks
            if max_fallbacks > 0 and self.consecutive_fallbacks >= max_fallbacks:
                return True, f"Fallback limiti aşıldı: {self.consecutive_fallbacks}/{max_fallbacks}"

            return False, ""

    def record_trade_result(self, pnl: float) -> None:
        """İşlem sonucunu kaydeder."""
        with self._lock:
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
            self._save_state()

    def record_llm_error(self) -> None:
        """LLM hatasını kaydeder."""
        with self._lock:
            self.consecutive_llm_errors += 1
            logger.warning("Art arda LLM hata sayacı: %d", self.consecutive_llm_errors)
            self._save_state()

    def record_api_rate_limit(self) -> None:
        """API rate limit hatasını kaydeder."""
        with self._lock:
            self.consecutive_rate_limits += 1
            logger.warning("Art arda Rate Limit hata sayacı: %d", self.consecutive_rate_limits)
            self._save_state()

    def reset_api_rate_limit(self) -> None:
        with self._lock:
            self.consecutive_rate_limits = 0
            self._save_state()

    def reset_llm_errors(self) -> None:
        """LLM hata sayacını sıfırlar."""
        with self._lock:
            self.consecutive_llm_errors = 0
            self._save_state()

    def record_fallback(self, agent_name: str = "") -> None:
        """Fallback kullanımını kaydet."""
        with self._lock:
            self.consecutive_fallbacks += 1
            logger.warning(
                "Fallback counter: %d (agent: %s)",
                self.consecutive_fallbacks,
                agent_name,
            )
            self._save_state()

    def reset_fallbacks(self) -> None:
        """Fallback sayacını sıfırlar."""
        with self._lock:
            if self.consecutive_fallbacks > 0:
                logger.info(
                    "Fallback counter reset (%d fallback sonrası başarılı işlem)",
                    self.consecutive_fallbacks,
                )
            self.consecutive_fallbacks = 0
            self._save_state()

    def reset_consecutive_losses(self) -> None:
        """Art arda kayıp sayacını sıfırlar."""
        with self._lock:
            self.consecutive_losses = 0
            self._save_state()

    def manual_stop(self) -> None:
        """Manuel durdurma - SystemStatus ile entegre."""
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
        # SystemStatus'u da güncelle
        system_status = SystemStatus.get_instance()
        system_status.emergency_stop("Manual stop via CircuitBreaker")
        logger.critical("Manuel durdurma aktif edildi (data/STOP oluşturuldu)")

    def resume(self) -> None:
        """Manuel durdurmayı kaldırır ve sayaçları sıfırlar."""
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        self.consecutive_losses = 0
        self.consecutive_llm_errors = 0
        # SystemStatus'u da sıfırla
        system_status = SystemStatus.get_instance()
        if system_status.is_emergency():
            system_status.resume()
        logger.info("Manuel durdurma kaldırıldı ve sayaçlar sıfırlandı")

    def get_status(
        self,
        equity: float | None = None,
        daily_pnl: float | None = None,
    ) -> dict:
        """Circuit breaker durumu."""
        if equity is not None and daily_pnl is not None:
            halted, reason = self.should_halt(equity=equity, daily_pnl=daily_pnl)
        else:
            halted, reason = self._check_halt_conditions(equity=-1, daily_pnl=0)

        system_status = SystemStatus.get_instance()
        system_halted = system_status.is_emergency() or system_status.is_cooldown()
        reason = reason or system_status.get_halt_reason() or ""
        is_halted = halted or STOP_FILE.exists() or system_halted

        return {
            "halted": is_halted,
            "halt_reason": reason if is_halted else "",
            "consecutive_losses": self.consecutive_losses,
            "consecutive_llm_errors": self.consecutive_llm_errors,
            "consecutive_fallbacks": self.consecutive_fallbacks,
            "stop_file_exists": STOP_FILE.exists(),
        }
