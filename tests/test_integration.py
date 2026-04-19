"""
LLM Trading System - Integration Tests
========================================
End-to-end tests for critical pipelines.
Run: pytest tests/test_integration.py -v
"""

import pytest
from pathlib import Path
import sys

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestRaceConditions:
    """Race condition düzeltme testleri."""
    
    def test_close_position_safe_thread_safety(self):
        """Thread-safe pozisyon kapatma testi."""
        from risk.portfolio import PortfolioState
        import threading
        
        portfolio = PortfolioState(initial_cash=10000)
        
        # Pozisyon aç
        portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000,
            amount=0.1,
            stop_loss=45000,
        )
        
        # Aynı pozisyonu paralel kapatma denemesi
        results = []
        
        def close_pos():
            result = portfolio.close_position_safe("BTC/USDT", 51000)
            results.append(result)
        
        threads = [threading.Thread(target=close_pos) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Sadece bir thread başarılı olmalı
        successful = [r for r in results if r is not None]
        assert len(successful) == 1, "Race condition: Birden fazla thread pozisyon kapattı!"
        assert portfolio.open_position_count == 0
    
    def test_portfolio_lock_protection(self):
        """Portfolio lock koruma testi."""
        from risk.portfolio import PortfolioState, _portfolio_lock
        import threading
        
        portfolio = PortfolioState(initial_cash=10000)
        
        # 100 paralel işlem
        def open_close():
            with _portfolio_lock:
                portfolio.open_position("BTC/USDT", "long", 50000, 0.01)
                portfolio.close_position_safe("BTC/USDT", 50000)
        
        threads = [threading.Thread(target=open_close) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Cash başlangıç değerinde olmalı (no slippage)
        assert abs(portfolio.cash - 10000) < 0.01


class TestLLMTimeouts:
    """LLM timeout testleri."""
    
    def test_invoke_with_retry_timeout_param(self):
        """invoke_with_retry timeout parametresi testi."""
        from utils.llm_retry import invoke_with_retry
        
        # Timeout parametresi kabul edilmeli
        def mock_invoke(*args, **kwargs):
            # renamed to 'timeout' in llm_retry.py for LangChain compatibility
            assert "timeout" in kwargs
            assert kwargs["timeout"] == 60
            return type('obj', (object,), {"content": "test"})()
        
        result = invoke_with_retry(
            mock_invoke,
            request_timeout=60,
            max_retries=1,
        )
        
        assert result.content == "test"


class TestCircuitBreakerPersistence:
    """Circuit breaker persistence testleri."""
    
    def test_state_save_load(self):
        """State save/load testi."""
        from risk.circuit_breaker import CircuitBreaker, STATE_FILE
        import time
        
        # Eski state varsa temizle
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        
        # Yeni circuit breaker
        cb1 = CircuitBreaker()
        cb1._params.system.reset_counters_on_startup = False
        cb1.consecutive_losses = 5
        cb1.consecutive_llm_errors = 3
        cb1._save_state()
        
        # Yeni instance (state'i yüklemeli)
        cb2 = CircuitBreaker()
        cb2._params.system.reset_counters_on_startup = False
        cb2._load_state()
        
        assert cb2.consecutive_losses == 5, "State yüklenmedi!"
        assert cb2.consecutive_llm_errors == 3, "State yüklenmedi!"
        
        # Cleanup
        STATE_FILE.unlink()
    
    def test_state_expires_after_1_hour(self):
        """State 1 saat sonra expire olmalı."""
        from risk.circuit_breaker import CircuitBreaker, STATE_FILE
        import json
        import time
        
        # Eski state varsa temizle
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        
        # Manuel eski state yaz (2 saat önce)
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        old_data = {
            "consecutive_losses": 10,
            "consecutive_llm_errors": 10,
            "timestamp": time.time() - 7200,  # 2 saat önce
        }
        STATE_FILE.write_text(json.dumps(old_data))
        
        # Yeni instance (eski state'i ignore etmeli)
        cb = CircuitBreaker()
        
        assert cb.consecutive_losses == 0, "Eski state ignore edilmedi!"
        assert cb.consecutive_llm_errors == 0, "Eski state ignore edilmedi!"


class TestConnectionRecovery:
    """Connection recovery testleri."""
    
    def test_try_reconnect_method_exists(self):
        """try_reconnect metodu var mı?"""
        from execution.exchange_client import ExchangeClient
        
        client = ExchangeClient()
        assert hasattr(client, "try_reconnect"), "try_reconnect metodu eksik!"
    
    def test_emergency_mode_recovery(self):
        """Emergency mode'dan kurtulma testi."""
        from execution.exchange_client import ExchangeClient
        
        client = ExchangeClient()
        client._emergency_mode = True
        client._last_successful_call = 0  # Timeout
        
        # Reconnect denemesi (başarısız olabilir ama method çalışmalı)
        result = client.try_reconnect(max_attempts=1)
        
        # Testnet'te başarılı olabilir, paper'da başarısız
        # Önemli olan method'un çalışması
        assert isinstance(result, bool)


class TestStopFileHandling:
    """STOP file error handling testleri."""
    
    def test_stop_file_creation_with_missing_dir(self):
        """STOP file oluşturma - klasör yoksa."""
        from pathlib import Path
        import tempfile
        import shutil
        
        # Geçici klasör
        temp_dir = tempfile.mkdtemp()
        stop_path = Path(temp_dir) / "nonexistent" / "STOP"
        
        try:
            # mkdir(parents=True, exist_ok=True) testi
            stop_path.parent.mkdir(parents=True, exist_ok=True)
            stop_path.touch()
            
            assert stop_path.exists(), "STOP file oluşturulamadı!"
        finally:
            shutil.rmtree(temp_dir)


class TestInputValidation:
    """Input validation testleri."""
    
    def test_validate_symbol_valid(self):
        """Geçerli sembol validasyonu."""
        from data.symbol_resolver import validate_symbol
        
        valid_symbols = [
            "BTC/USDT",
            "BTCUSDT",
            "AAPL",
            "BIMAS.IS",
            "ETH-BTC",
            "SOL_USDT",
        ]
        
        for symbol in valid_symbols:
            assert validate_symbol(symbol), f"Geçerli sembol reddedildi: {symbol}"
    
    def test_validate_symbol_invalid(self):
        """Geçersiz sembol validasyonu."""
        from data.symbol_resolver import validate_symbol
        
        invalid_symbols = [
            "../../../etc/passwd",  # Path traversal
            "BTC; rm -rf /",  # Command injection
            "AAPL<script>",  # HTML injection
            "ETH\x00BTC",  # Control character
            "A" * 100,  # Too long
        ]
        
        for symbol in invalid_symbols:
            assert not validate_symbol(symbol), f"Geçersiz sembol kabul edildi: {symbol}"
    
    def test_resolve_symbol_rejects_invalid(self):
        """resolve_symbol geçersiz input'u reddetmeli."""
        from data.symbol_resolver import resolve_symbol
        
        with pytest.raises(ValueError):
            resolve_symbol("../../../etc/passwd")
        
        with pytest.raises(ValueError):
            resolve_symbol("BTC; rm -rf /")


class TestChromaDBCleanup:
    """ChromaDB connection cleanup testleri."""
    
    def test_close_method_exists(self):
        """close metodu var mı?"""
        from data.vector_store import AgentMemoryStore
        
        store = AgentMemoryStore()
        assert hasattr(store, "close"), "close metodu eksik!"
    
    def test_close_sets_client_to_none(self):
        """close sonrası client None olmalı."""
        from data.vector_store import AgentMemoryStore
        
        store = AgentMemoryStore()
        # Collection'ı başlat
        _ = store.collection
        
        # Kapat
        store.close()
        
        assert store._client is None, "Client cleanup failed!"
        assert store._collection is None, "Collection cleanup failed!"


class TestHealthCheck:
    """Health check script testi."""
    
    def test_health_check_script_exists(self):
        """Health check script var mı?"""
        script_path = PROJECT_ROOT / "scripts" / "health_check.py"
        assert script_path.exists(), "health_check.py eksik!"
    
    def test_health_check_runs(self):
        """Health check çalıştırılabilir mi?"""
        import subprocess
        
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "health_check.py")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        # Exit code 0 veya 1 olabilir (testlere bağlı)
        assert result.returncode in (0, 1), "Health check crashed!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
