"""
System Status Manager
======================
Merkezi durum yönetimi ve event-driven sistem kontrolü.

Status States:
- RUNNING: Normal operasyon
- EMERGENCY_STOP: Acil durdurma (flash crash, bağlantı kaybı vb.)
- COOLDOWN: Recovery sonrası bekleme
- RECONNECTING: Borsa bağlantısı yeniden kuruluyor

Kullanım:
    from risk.system_status import SystemStatus, Status
    
    status = SystemStatus.get_instance()
    
    # Durum kontrolü
    if status.is_halted():
        logger.warning("Sistem durduruldu")
        return
    
    # Durum değiştirme
    status.emergency_stop(reason="Flash crash detected")
    
    # Listener ekleme (event-driven)
    status.add_listener("emergency_stop", my_callback)
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)


class Status(str, Enum):
    """Sistem durumları."""
    RUNNING = "running"
    EMERGENCY_STOP = "emergency_stop"
    COOLDOWN = "cooldown"
    RECONNECTING = "reconnecting"


class SystemStatus:
    """
    Thread-safe singleton sistem durum yöneticisi.
    
    Özellikler:
    - Singleton pattern (thread-safe)
    - In-memory event bus (threading.Event)
    - Status getters/setters
    - Listener registration (callback'ler)
    - STOP dosyası ile entegre (geriye uyumluluk)
    """
    
    _instance: SystemStatus | None = None
    _lock = threading.Lock()
    
    def __new__(cls) -> SystemStatus:
        """Singleton instance oluştur (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize sistem durumu."""
        # Double-check locking pattern
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._status = Status.RUNNING
        self._status_lock = threading.RLock()
        self._halt_reason: str | None = None
        self._halt_timestamp: float | None = None
        self._listeners: dict[str, list[Callable]] = {
            "emergency_stop": [],
            "resume": [],
            "cooldown": [],
        }
        self._stop_file = DATA_DIR / "STOP"
        self._last_file_check = 0.0
        self._file_check_interval = 1.0  # saniye
        self._initialized = True
        
        logger.info("SystemStatus initialized")
    
    @classmethod
    def get_instance(cls) -> SystemStatus:
        """Thread-safe instance erişimi."""
        return cls()
    
    @classmethod
    def reset_instance(cls) -> None:
        """Singleton'ı sıfırla (testler için)."""
        with cls._lock:
            cls._instance = None
    
    # ── Status Getters ──────────────────────────────────────
    
    def get_status(self) -> Status:
        """Mevcut durumu döndür."""
        with self._status_lock:
            # STOP dosyasını periyodik kontrol et
            self._check_stop_file()
            return self._status
    
    def is_running(self) -> bool:
        """Sistem çalışıyor mu?"""
        return self.get_status() == Status.RUNNING
    
    def is_halted(self) -> bool:
        """Sistem durduruldu mu? (emergency stop veya cooldown)"""
        status = self.get_status()
        return status in (Status.EMERGENCY_STOP, Status.COOLDOWN)
    
    def is_emergency(self) -> bool:
        """Acil durum modu mu?"""
        return self.get_status() == Status.EMERGENCY_STOP
    
    def is_cooldown(self) -> bool:
        """Bekleme modu mu?"""
        return self.get_status() == Status.COOLDOWN
    
    def is_reconnecting(self) -> bool:
        """Yeniden bağlanma modu mu?"""
        return self.get_status() == Status.RECONNECTING
    
    def get_halt_reason(self) -> str | None:
        """Durdurma nedenini döndür."""
        with self._status_lock:
            return self._halt_reason
    
    def get_halt_duration(self) -> float:
        """Durdurma süresini döndür (saniye)."""
        with self._status_lock:
            if self._halt_timestamp is None:
                return 0.0
            return time.time() - self._halt_timestamp
    
    # ── Status Setters ──────────────────────────────────────
    
    def set_status(self, status: Status, reason: str | None = None) -> None:
        """
        Durumu değiştir ve listener'lara haber ver.
        
        Args:
            status: Yeni durum
            reason: Durum değişikliği nedeni (opsiyonel)
        """
        with self._status_lock:
            old_status = self._status
            self._status = status
            
            if status == Status.EMERGENCY_STOP:
                self._halt_reason = reason
                self._halt_timestamp = time.time()
                self._trigger_event("emergency_stop", reason)
                self._create_stop_file()
                logger.critical("🚨 SYSTEM EMERGENCY STOP: %s", reason)
                
            elif status == Status.COOLDOWN:
                self._halt_reason = reason
                self._halt_timestamp = time.time()
                self._trigger_event("cooldown", reason)
                logger.warning("⏸️ SYSTEM COOLDOWN: %s", reason)
                
            elif status == Status.RECONNECTING:
                logger.warning("🔄 SYSTEM RECONNECTING: %s", reason or "Reconnecting to exchange")
                
            elif status == Status.RUNNING:
                old_halt = self._halt_reason
                self._halt_reason = None
                self._halt_timestamp = None
                self._delete_stop_file()
                if old_status in (Status.EMERGENCY_STOP, Status.COOLDOWN):
                    self._trigger_event("resume", old_halt)
                    logger.info("✅ SYSTEM RESUMED (was: %s)", old_status)
        
        # Status değişimini logla
        if old_status != status:
            logger.debug("System status: %s → %s", old_status.value, status.value)
    
    def emergency_stop(self, reason: str) -> None:
        """Acil durdurma."""
        self.set_status(Status.EMERGENCY_STOP, reason)
    
    def resume(self) -> None:
        """Sistemi devam ettir."""
        self.set_status(Status.RUNNING)
    
    def cooldown(self, reason: str = "Cooling down") -> None:
        """Bekleme moduna geç."""
        self.set_status(Status.COOLDOWN, reason)
    
    def reconnecting(self, reason: str | None = None) -> None:
        """Yeniden bağlanma modu."""
        self.set_status(Status.RECONNECTING, reason)
    
    # ── Event Bus (Listeners) ───────────────────────────────
    
    def add_listener(self, event: str, callback: Callable) -> None:
        """
        Event listener ekle.
        
        Args:
            event: Event adı ("emergency_stop", "resume", "cooldown")
            callback: Callback fonksiyonu (reason: str) -> None
        """
        if event not in self._listeners:
            self._listeners[event] = []
        
        with self._status_lock:
            self._listeners[event].append(callback)
        
        logger.debug("Listener added for event: %s", event)
    
    def remove_listener(self, event: str, callback: Callable) -> None:
        """Event listener kaldır."""
        if event in self._listeners:
            with self._status_lock:
                if callback in self._listeners[event]:
                    self._listeners[event].remove(callback)
    
    def _trigger_event(self, event: str, reason: str | None = None) -> None:
        """Event listener'lara haber ver (thread-safe)."""
        callbacks = []
        with self._status_lock:
            if event in self._listeners:
                callbacks = self._listeners[event].copy()
        
        for callback in callbacks:
            try:
                callback(reason)
            except Exception as e:
                logger.error("Event listener error (%s): %s", event, e)
    
    # ── STOP File Integration ───────────────────────────────
    
    def _check_stop_file(self) -> None:
        """STOP dosyasını periyodik kontrol et (polling azaltma)."""
        current_time = time.time()
        if current_time - self._last_file_check < self._file_check_interval:
            return
        
        self._last_file_check = current_time
        
        if self._stop_file.exists() and self._status != Status.EMERGENCY_STOP:
            logger.warning("STOP file detected, setting emergency stop")
            self._status = Status.EMERGENCY_STOP
            self._halt_reason = "Manual stop via STOP file"
            self._halt_timestamp = time.time()
    
    def _create_stop_file(self) -> None:
        """STOP dosyası oluştur."""
        try:
            self._stop_file.parent.mkdir(parents=True, exist_ok=True)
            self._stop_file.touch()
            logger.debug("STOP file created")
        except Exception as e:
            logger.error("Failed to create STOP file: %s", e)
    
    def _delete_stop_file(self) -> None:
        """STOP dosyasını sil."""
        try:
            if self._stop_file.exists():
                self._stop_file.unlink()
                logger.debug("STOP file deleted")
        except Exception as e:
            logger.error("Failed to delete STOP file: %s", e)
    
    # ── Utility Methods ─────────────────────────────────────
    
    def manual_stop(self) -> None:
        """Manuel durdurma (CircuitBreaker ile uyumluluk)."""
        self.emergency_stop("Manual stop requested")
    
    def wait_for_resume(self, timeout: float | None = None) -> bool:
        """
        Sistem RUNNING olana kadar bekle.
        
        Args:
            timeout: Maksimum bekleme süresi (saniye), None = sonsuz
            
        Returns:
            True if resumed, False if timeout
        """
        start_time = time.time()
        while not self.is_running():
            if timeout is not None and (time.time() - start_time) > timeout:
                return False
            time.sleep(0.1)
        return True
    
    def get_status_dict(self) -> dict:
        """Durum bilgisi dict olarak döndür (dashboard için)."""
        with self._status_lock:
            return {
                "status": self._status.value,
                "halt_reason": self._halt_reason,
                "halt_duration": self.get_halt_duration(),
                "halt_timestamp": (
                    datetime.fromtimestamp(self._halt_timestamp, tz=timezone.utc).isoformat()
                    if self._halt_timestamp else None
                ),
                "stop_file_exists": self._stop_file.exists(),
            }
    
    def __repr__(self) -> str:
        return f"SystemStatus(status={self.get_status().value}, reason={self._halt_reason})"


# ── Convenience Functions ──────────────────────────────────

def get_status() -> Status:
    """Kısayol: Sistem durumunu al."""
    return SystemStatus.get_instance().get_status()

def is_running() -> bool:
    """Kısayol: Sistem çalışıyor mu?"""
    return SystemStatus.get_instance().is_running()

def is_halted() -> bool:
    """Kısayol: Sistem durduruldu mu?"""
    return SystemStatus.get_instance().is_halted()

def emergency_stop(reason: str) -> None:
    """Kısayol: Acil durdurma."""
    SystemStatus.get_instance().emergency_stop(reason)

def resume() -> None:
    """Kısayol: Sistemi devam ettir."""
    SystemStatus.get_instance().resume()
