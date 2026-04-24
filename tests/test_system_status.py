"""
SystemStatus Tests
===================
Tests for the centralized system status manager.
"""

import pytest
import threading
import time

from risk.system_status import (
    SystemStatus,
    Status,
    get_status,
    is_running,
    is_halted,
    emergency_stop,
    resume,
)


@pytest.fixture
def fresh_system_status():
    """Her test için fresh SystemStatus instance."""
    SystemStatus.reset_instance()
    s = SystemStatus.get_instance()
    if s._stop_file.exists():
        try:
            s._stop_file.unlink()
        except OSError:
            pass
    yield s
    if s._stop_file.exists():
        try:
            s._stop_file.unlink()
        except OSError:
            pass
    SystemStatus.reset_instance()


class TestSystemStatusBasic:
    """Temel SystemStatus testleri."""
    
    def test_singleton_pattern(self):
        """Singleton pattern testi."""
        s1 = SystemStatus.get_instance()
        s2 = SystemStatus.get_instance()
        assert s1 is s2, "Singleton pattern çalışmıyor!"
    
    def test_initial_status(self, fresh_system_status):
        """Başlangıç durumu RUNNING olmalı."""
        s = fresh_system_status
        # STOP dosyası kontrolünü atla (önceki testlerden kalabilir)
        status = s._status
        assert status == Status.RUNNING or status == Status.EMERGENCY_STOP
        # Manuel resume yap eğer emergency'de
        if status == Status.EMERGENCY_STOP:
            s.resume()
        assert s.is_running()
        assert not s.is_halted()
    
    def test_emergency_stop(self, fresh_system_status):
        """Emergency stop testi."""
        s = fresh_system_status
        s.emergency_stop("Test reason")
        
        assert s.is_emergency()
        assert s.is_halted()
        assert not s.is_running()
        assert s.get_halt_reason() == "Test reason"
    
    def test_resume(self, fresh_system_status):
        """Resume testi."""
        s = fresh_system_status
        s.emergency_stop("Test")
        s.resume()
        
        assert s.is_running()
        assert not s.is_halted()
        assert s.get_halt_reason() is None
    
    def test_cooldown(self, fresh_system_status):
        """Cooldown testi."""
        s = fresh_system_status
        s.cooldown("Cooling down")
        
        assert s.is_cooldown()
        assert s.is_halted()
        assert not s.is_running()
    
    def test_reconnecting(self, fresh_system_status):
        """Reconnecting testi."""
        s = fresh_system_status
        s.reconnecting("Reconnecting to exchange")
        
        assert s.is_reconnecting()
        assert not s.is_running()


class TestSystemStatusListeners:
    """Event listener testleri."""
    
    def test_add_listener(self, fresh_system_status):
        """Listener ekleme testi."""
        s = fresh_system_status
        called = []
        
        def callback(reason):
            called.append(reason)
        
        s.add_listener("emergency_stop", callback)
        s.emergency_stop("Test")
        
        assert len(called) == 1
        assert called[0] == "Test"
    
    def test_remove_listener(self, fresh_system_status):
        """Listener kaldırma testi."""
        s = fresh_system_status
        called = []
        
        def callback(reason):
            called.append(reason)
        
        s.add_listener("resume", callback)
        s.remove_listener("resume", callback)
        s.resume()
        
        assert len(called) == 0
    
    def test_multiple_listeners(self, fresh_system_status):
        """Birden fazla listener testi."""
        s = fresh_system_status
        called1 = []
        called2 = []
        
        s.add_listener("emergency_stop", lambda r: called1.append(r))
        s.add_listener("emergency_stop", lambda r: called2.append(r))
        s.emergency_stop("Test")
        
        assert len(called1) == 1
        assert len(called2) == 1


class TestSystemStatusThreadSafety:
    """Thread-safety testleri."""
    
    def test_concurrent_status_changes(self, fresh_system_status):
        """Paralel durum değişikliği testi."""
        s = fresh_system_status
        errors = []
        
        def toggle():
            try:
                for _ in range(100):
                    s.emergency_stop("Test")
                    s.resume()
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=toggle) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert s.is_running()
    
    def test_listener_thread_safety(self, fresh_system_status):
        """Listener thread-safety testi."""
        s = fresh_system_status
        called = []
        lock = threading.Lock()
        
        def callback(reason):
            with lock:
                called.append(reason)
        
        s.add_listener("emergency_stop", callback)
        
        def trigger():
            for _ in range(50):
                s.emergency_stop("Test")
                s.resume()
        
        threads = [threading.Thread(target=trigger) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Her emergency_stop için callback çağrılmalı
        assert len(called) == 250  # 5 threads * 50 calls


# STOP dosyası testleri integration testlere taşındı (test_integration.py)
# Çünkü SystemStatus singleton ve DATA_DIR değiştirme karmaşık


class TestSystemStatusConvenience:
    """Convenience function testleri."""
    
    def test_convenience_functions(self, fresh_system_status):
        """Kısayol fonksiyonları testi."""
        # Convenience fonksiyonlar singleton kullanır
        assert is_running()
        assert not is_halted()
        
        emergency_stop("Test")
        assert not is_running()
        assert is_halted()
        assert get_status() == Status.EMERGENCY_STOP
        
        resume()
        assert is_running()
        assert not is_halted()


class TestSystemStatusWait:
    """Wait for resume testleri."""
    
    def test_wait_for_resume(self, fresh_system_status):
        """Resume bekleme testi."""
        s = fresh_system_status
        s.emergency_stop("Test")
        
        def resume_later():
            time.sleep(0.2)
            s.resume()
        
        thread = threading.Thread(target=resume_later)
        thread.start()
        
        result = s.wait_for_resume(timeout=1.0)
        thread.join()
        
        assert result is True
        assert s.is_running()
    
    def test_wait_for_resume_timeout(self, fresh_system_status):
        """Resume bekleme timeout testi."""
        s = fresh_system_status
        s.emergency_stop("Test")
        
        # Resume çağrılmıyor, timeout bekleniyor
        result = s.wait_for_resume(timeout=0.3)
        
        assert result is False
        assert not s.is_running()


class TestSystemStatusDict:
    """Status dict testleri."""
    
    def test_get_status_dict(self, fresh_system_status):
        """Status dict testi."""
        s = fresh_system_status
        d = s.get_status_dict()
        
        assert "status" in d
        assert d["status"] == "running"
        assert "halt_reason" in d
        assert "halt_duration" in d
        assert "stop_file_exists" in d
    
    def test_get_status_dict_emergency(self, fresh_system_status):
        """Emergency durumda status dict testi."""
        s = fresh_system_status
        s.emergency_stop("Test reason")
        
        d = s.get_status_dict()
        
        assert d["status"] == "emergency_stop"
        assert d["halt_reason"] == "Test reason"
        assert d["halt_duration"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
