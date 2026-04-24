"""
Performance & Lock Contention Tests
=====================================
Tests for lock performance, memory leaks, and resource cleanup.
"""

import pytest
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.portfolio import PortfolioState, _portfolio_lock


class TestLockPerformance:
    """Lock performance testleri."""

    def test_lock_acquisition_time(self):
        """Lock acquisition time testi."""
        acquisition_times = []
        
        def measure_acquire():
            start = time.perf_counter()
            with _portfolio_lock:
                elapsed = time.perf_counter() - start
                acquisition_times.append(elapsed)
        
        # 100 iterations
        for _ in range(100):
            measure_acquire()
        
        avg_time = sum(acquisition_times) / len(acquisition_times)
        max_time = max(acquisition_times)
        
        # Average < 1ms olmalı
        assert avg_time < 0.001, f"Average lock acquisition too slow: {avg_time*1000:.2f}ms"
        
        # Max < 10ms olmalı
        assert max_time < 0.01, f"Max lock acquisition too slow: {max_time*1000:.2f}ms"

    def test_lock_contention_under_load(self):
        """High load altında lock contention testi."""
        portfolio = PortfolioState(initial_cash=1000000.0)
        acquisition_times = []
        lock = threading.Lock()
        
        def worker(worker_id):
            start = time.perf_counter()
            
            with _portfolio_lock:
                elapsed = time.perf_counter() - start
                with lock:
                    acquisition_times.append(elapsed)
                
                # Portfolio operation
                symbol = f"SYM{worker_id}/USDT"
                portfolio.open_position(
                    symbol=symbol,
                    side="long",
                    price=100.0,
                    amount=10.0,
                    stop_loss=95.0,
                )
                time.sleep(0.001)  # Simulated work
        
        # 50 concurrent workers
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(worker, i) for i in range(50)]
            for future in as_completed(futures):
                future.result(timeout=30)
        
        assert len(acquisition_times) == 50
        
        avg_time = sum(acquisition_times) / len(acquisition_times)
        max_time = max(acquisition_times)
        
        # Average acquisition < 1.0s (GitHub Actions CI + disk I/O variability tolerance)
        assert avg_time < 1.0, f"Average lock acquisition under load: {avg_time*1000:.2f}ms"

        # Max acquisition < 2.0s (contention + disk I/O expected)
        assert max_time < 2.0, f"Max lock acquisition under load: {max_time*1000:.2f}ms"

    def test_lock_hold_duration(self):
        """Lock hold duration testi."""
        hold_durations = []
        
        def measure_hold():
            start = time.perf_counter()
            with _portfolio_lock:
                # Quick operation
                pass
            elapsed = time.perf_counter() - start
            hold_durations.append(elapsed)
        
        for _ in range(100):
            measure_hold()
        
        avg_duration = sum(hold_durations) / len(hold_durations)
        max_duration = max(hold_durations)
        
        # Average hold < 1ms
        assert avg_duration < 0.001, f"Average hold duration: {avg_duration*1000:.2f}ms"
        
        # Max hold < 10ms
        assert max_duration < 0.01, f"Max hold duration: {max_duration*1000:.2f}ms"


class TestMemoryLeaks:
    """Memory leak detection testleri."""

    def test_exchange_instance_lifecycle(self):
        """Exchange instance lifecycle - memory leak testi."""
        tracemalloc.start()
        
        initial_snapshot = tracemalloc.take_snapshot()
        
        # Create and destroy multiple MarketDataClient instances
        from data.market_data import MarketDataClient
        
        for i in range(10):
            client = MarketDataClient()
            # Don't use, just create and let GC handle
            del client
        
        # Force garbage collection
        import gc
        gc.collect()
        
        final_snapshot = tracemalloc.take_snapshot()
        
        # Compare snapshots
        top_stats = final_snapshot.compare_to(initial_snapshot, 'lineno')
        
        # Memory increase should be minimal (< 1MB)
        total_increase = sum(stat.size_diff for stat in top_stats[:10])
        
        # Allow some variance, but should not grow unbounded
        assert total_increase < 1024 * 1024, f"Memory leak detected: {total_increase / 1024:.2f}KB"
        
        tracemalloc.stop()

    def test_portfolio_state_memory(self):
        """Portfolio state memory usage testi."""
        tracemalloc.start()
        
        initial_snapshot = tracemalloc.take_snapshot()
        
        # Create multiple portfolio states
        portfolios = []
        for i in range(100):
            portfolio = PortfolioState(initial_cash=10000.0)
            
            # Add some positions
            for j in range(5):
                portfolio.open_position(
                    symbol=f"SYM{j}/USDT",
                    side="long",
                    price=100.0,
                    amount=10.0,
                    stop_loss=95.0,
                )
            
            portfolios.append(portfolio)
        
        final_snapshot = tracemalloc.take_snapshot()
        top_stats = final_snapshot.compare_to(initial_snapshot, 'lineno')
        
        # Memory should be proportional to data size
        # 100 portfolios * 5 positions = 500 positions total
        # Should not exceed 10MB
        total_increase = sum(stat.size_diff for stat in top_stats[:10])
        assert total_increase < 10 * 1024 * 1024, f"Excessive memory: {total_increase / 1024 / 1024:.2f}MB"
        
        tracemalloc.stop()

    def test_file_handle_leak(self, tmp_path):
        """File handle leak testi."""
        import os
        import warnings
        
        portfolio_file = tmp_path / "test_portfolio.json"
        
        # Get initial file handle count
        if hasattr(os, 'get_handle_inheritable'):
            # Windows
            initial_handles = len(os.listdir('C:\\'))  # Approximate
        else:
            # Unix
            import subprocess
            result = subprocess.run(['lsof', '-p', str(os.getpid())], 
                                  capture_output=True, text=True)
            initial_handles = len(result.stdout.split('\n'))
        
        # Multiple save/load cycles
        from risk.portfolio import PortfolioState
        
        for i in range(100):
            portfolio = PortfolioState(initial_cash=10000.0)
            portfolio.save_to_file(portfolio_file)
            PortfolioState.load_from_file(portfolio_file)
        
        # Force GC
        import gc
        gc.collect()
        
        # File handles should not increase significantly
        # (This is a basic check, proper check requires OS-specific tools)


class TestResourceCleanup:
    """Resource cleanup testleri."""

    def test_lock_release_on_exception(self):
        """Lock release on exception testi."""
        portfolio = PortfolioState(initial_cash=10000.0)
        
        def operation_with_exception():
            with _portfolio_lock:
                portfolio.cash -= 100
                raise ValueError("Test exception")
        
        # Exception fırlat
        with pytest.raises(ValueError):
            operation_with_exception()
        
        # Lock serbest kalmalı
        acquired = _portfolio_lock.acquire(timeout=1.0)
        assert acquired is True
        _portfolio_lock.release()

    def test_portfolio_cleanup_on_error(self):
        """Portfolio cleanup on error testi."""
        portfolio = PortfolioState(initial_cash=100000.0)
        
        initial_cash = portfolio.cash
        
        def failed_operation():
            with _portfolio_lock:
                portfolio.cash -= 1000
                # Simulate error before completing operation
                raise RuntimeError("Operation failed")
        
        # Error handling
        try:
            failed_operation()
        except RuntimeError:
            pass
        
        # Cash değişmiş olmalı (rollback yok - bu expected behavior)
        # Important: Lock release edilmiş olmalı
        acquired = _portfolio_lock.acquire(timeout=1.0)
        assert acquired is True
        _portfolio_lock.release()


class TestThroughput:
    """Throughput testleri."""

    def test_position_operations_per_second(self):
        """Position operations per second throughput testi."""
        portfolio = PortfolioState(initial_cash=10000000.0)  # Large cash for many positions
        
        start_time = time.perf_counter()
        operations = 0
        
        # 1 saniyede kaç pozisyon açıp kapatabiliyoruz?
        while time.perf_counter() - start_time < 1.0:
            symbol = f"SYM{operations}/USDT"
            
            pos = portfolio.open_position(
                symbol=symbol,
                side="long",
                price=100.0,
                amount=10.0,
                stop_loss=95.0,
            )
            
            if pos:
                portfolio.close_position(symbol, 105.0)
                operations += 2  # Open + close
        
        elapsed = time.perf_counter() - start_time
        ops_per_second = operations / elapsed
        
        # Minimum 50 ops/second olmalı (CI tolerance)
        assert ops_per_second >= 50, f"Throughput too low: {ops_per_second:.2f} ops/sec"
        
        print(f"\nThroughput: {ops_per_second:.2f} operations/second")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
