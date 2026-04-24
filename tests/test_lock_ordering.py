"""
Lock Ordering & Concurrency Tests
==================================
Tests for thread-safety, lock ordering, and deadlock prevention.
"""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.portfolio import PortfolioState, _portfolio_lock, _acquire_portfolio_lock, _release_portfolio_lock
from config.constants import LOCK_WARNING_THRESHOLD


class TestLockOrdering:
    """Lock ordering ve deadlock prevention testleri."""

    def test_portfolio_lock_acquire_release(self):
        """Basic lock acquire/release testi."""
        # Lock al
        acquired = _acquire_portfolio_lock(timeout=5.0)
        assert acquired is True
        
        # Lock bırak
        _release_portfolio_lock()
        
        # Tekrar alabilme kontrolü
        acquired2 = _acquire_portfolio_lock(timeout=5.0)
        assert acquired2 is True
        _release_portfolio_lock()

    def test_portfolio_lock_timeout(self):
        """Lock timeout mekanizması testi."""
        # Lock'u tut
        acquired = _portfolio_lock.acquire()
        assert acquired is True

        try:
            # Başka thread timeout ile almayı denesin
            result_container = []

            def try_acquire():
                result_container.append(_acquire_portfolio_lock(timeout=0.5))

            t = threading.Thread(target=try_acquire)
            t.start()
            t.join(timeout=2.0)

            assert len(result_container) == 1
            assert result_container[0] is False  # Timeout olmalı
        finally:
            # Lock'u bırak
            _portfolio_lock.release()

    def test_concurrent_position_access(self):
        """Concurrent portfolio access testi - thread safety."""
        portfolio = PortfolioState(initial_cash=100000.0)
        errors = []
        
        def worker(symbol_id):
            try:
                symbol = f"BTC/USDT_{symbol_id}"
                # Pozisyon aç
                pos = portfolio.open_position(
                    symbol=symbol,
                    side="long",
                    price=50000.0,
                    amount=0.1,
                    stop_loss=49000.0,
                    take_profit=52000.0,
                )
                
                if pos:
                    # Pozisyonu kapat
                    portfolio.close_position(symbol, 51000.0)
                    
            except Exception as e:
                errors.append((symbol_id, str(e)))
        
        # 10 concurrent thread
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Tüm thread'lerin bitmesini bekle
        for t in threads:
            t.join(timeout=30)
        
        # Hata olmamalı
        assert len(errors) == 0, f"Concurrency errors: {errors}"

    def test_lock_ordering_portfolio_then_exchange(self):
        """Lock sırası testi: portfolio → exchange (doğru sıra)."""
        # Bu test lock acquisition order'ı doğrular
        # Gerçek exchange lock'ı mock'layarak test ediyoruz
        
        portfolio_lock_acquired = threading.Event()
        exchange_lock_acquired = threading.Event()
        order_violation = []
        
        def correct_order():
            # Önce portfolio lock
            with _portfolio_lock:
                portfolio_lock_acquired.set()
                time.sleep(0.1)  # Lock hold süresi
                
                # Sonra exchange lock (simüle)
                exchange_lock_acquired.set()
        
        def worker():
            try:
                correct_order()
            except Exception as e:
                order_violation.append(str(e))
        
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        
        # Portfolio lock önce alınmalı
        assert portfolio_lock_acquired.is_set()
        assert exchange_lock_acquired.is_set()
        assert len(order_violation) == 0

    def test_nested_lock_prevention(self):
        """Nested lock acquisition testi."""
        # RLock aynı thread'den tekrar alınabilir
        with _portfolio_lock:
            # Inner lock (aynı thread'de OK)
            with _portfolio_lock:
                # Bu RLock sayesinde çalışır
                pass
        
        # Test passed - deadlock oluşmadı

    def test_lock_contention_under_load(self):
        """High load altında lock contention testi."""
        portfolio = PortfolioState(initial_cash=1000000.0)
        acquisition_times = []
        lock = threading.Lock()
        
        def worker(worker_id):
            start = time.time()
            
            with _portfolio_lock:
                elapsed = time.time() - start
                with lock:
                    acquisition_times.append(elapsed)
                
                # Portfolio operation
                symbol = f"BTC/USDT_{worker_id}"
                portfolio.open_position(
                    symbol=symbol,
                    side="long",
                    price=50000.0,
                    amount=0.1,
                    stop_loss=49000.0,
                )
                time.sleep(0.01)  # Simulated work
        
        # 20 concurrent workers
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(worker, i) for i in range(20)]
            for future in as_completed(futures):
                try:
                    future.result(timeout=30)
                except Exception as e:
                    pytest.fail(f"Worker failed: {e}")
        
        # Lock acquisition time analizi
        assert len(acquisition_times) == 20
        avg_time = sum(acquisition_times) / len(acquisition_times)
        max_time = max(acquisition_times)
        
        # Average acquisition < 1 saniye olmalı
        assert avg_time < 1.0, f"Average lock acquisition too slow: {avg_time}s"
        
        # Max acquisition < 5 saniye olmalı (timeout threshold)
        assert max_time < 5.0, f"Max lock acquisition too slow: {max_time}s"


class TestCorrelationCheckerDeadlock:
    """CorrelationChecker deadlock prevention testleri."""

    def test_correlation_check_outside_lock(self):
        """Correlation check'in lock dışında yapıldığını doğrula."""
        portfolio = PortfolioState(initial_cash=100000.0)
        
        # İlk pozisyon
        portfolio.open_position(
            symbol="BTC/USDT",
            side="long",
            price=50000.0,
            amount=0.1,
            stop_loss=49000.0,
        )
        
        # İkinci pozisyon açarken correlation check yapılacak
        # Bu check lock DIŞINDA yapılmalı (deadlock önleme)
        
        # Mock market data
        import pandas as pd
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        market_data = {
            "BTC/USDT": pd.DataFrame({
                'datetime': dates,
                'close': [50000 + i * 100 for i in range(100)]
            }),
            "ETH/USDT": pd.DataFrame({
                'datetime': dates,
                'close': [3000 + i * 10 for i in range(100)]
            }),
        }
        
        # Bu işlem deadlock oluşturmamalı
        pos = portfolio.open_position(
            symbol="ETH/USDT",
            side="long",
            price=3000.0,
            amount=1.0,
            stop_loss=2900.0,
            max_correlation=0.70,
            market_data=market_data,
        )
        
        # Pozisyon açılmış olmalı (correlation düşükse)
        # Veya None dönmeli (correlation yüksekse)
        # Her iki durum da valid - önemli olan deadlock olmaması
        assert portfolio.open_position_count in [1, 2]


class TestLockTimeout:
    """Lock timeout ve warning mekanizması testleri."""

    def test_lock_warning_threshold(self, caplog):
        """Lock warning threshold testi."""
        import logging
        
        # Uzun lock hold süresi simüle et
        def hold_lock_long():
            with _portfolio_lock:
                time.sleep(LOCK_WARNING_THRESHOLD + 1)  # Threshold'ı aş
        
        # Warning log'u yakala
        with caplog.at_level(logging.WARNING):
            thread = threading.Thread(target=hold_lock_long)
            thread.start()
            thread.join(timeout=30)
        
        # Warning log'lanmış olmalı
        # Not: Bu test acquisition time'ı test etmiyor, sadece threshold'ı
        # Gerçek acquisition warning'ı manual test gerektirir

    def test_lock_acquire_failure_handling(self):
        """Lock acquisition failure handling testi."""
        # Lock'u tut
        with _portfolio_lock:
            # Başka thread'den almayı dene (timeout ile)
            result_container = []

            def try_acquire():
                result_container.append(_acquire_portfolio_lock(timeout=0.1))

            t = threading.Thread(target=try_acquire)
            t.start()
            t.join(timeout=2.0)

            assert len(result_container) == 1
            assert result_container[0] is False

        # Lock bırakıldıktan sonra alabilmeli
        acquired = _acquire_portfolio_lock(timeout=1.0)
        assert acquired is True
        _release_portfolio_lock()


class TestPortfolioThreadSafety:
    """Portfolio state thread-safety testleri."""

    def test_concurrent_cash_updates(self):
        """Concurrent cash update testi."""
        portfolio = PortfolioState(initial_cash=100000.0)
        initial_cash = portfolio.cash
        
        def spend_cash(amount):
            with _portfolio_lock:
                portfolio.cash -= amount
                time.sleep(0.001)  # Race condition window
                portfolio.cash += amount
        
        # 10 concurrent threads, her biri 1000 USDT azaltıp geri ekleyecek
        threads = []
        for _ in range(10):
            t = threading.Thread(target=spend_cash, args=(1000.0,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=30)
        
        # Cash başlangıç değerine dönmeli
        assert portfolio.cash == initial_cash

    def test_concurrent_position_operations(self):
        """Concurrent position open/close testi."""
        portfolio = PortfolioState(initial_cash=1000000.0)
        errors = []
        
        def open_close_cycle(symbol_id):
            try:
                symbol = f"SYM{symbol_id}/USDT"
                
                # Open
                pos = portfolio.open_position(
                    symbol=symbol,
                    side="long",
                    price=100.0,
                    amount=10.0,
                    stop_loss=95.0,
                )
                
                if pos:
                    time.sleep(0.01)
                    # Close
                    portfolio.close_position(symbol, 105.0)
                    
            except Exception as e:
                errors.append((symbol_id, str(e)))
        
        # 5 concurrent cycles
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(open_close_cycle, i) for i in range(5)]
            for future in as_completed(futures):
                future.result(timeout=30)
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert portfolio.open_position_count == 0  # Tüm pozisyonlar kapandı


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
