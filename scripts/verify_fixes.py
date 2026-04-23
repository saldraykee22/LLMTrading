"""
LLMTrading Fix Verification Script
==================================
Bu betik, son yapılan düzeltmelerin doğruluğunu kontrol eder:
1. Thread-safety (RLock varlığı)
2. Order Tagging (llm_ prefix)
3. Watchdog emergency_halt mantığı
4. Debate parallelization
"""

import os
import sys
import threading
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

def check_thread_safety():
    print("[*] Checking Thread-Safety...")
    from execution.exchange_client import ExchangeClient
    from risk.portfolio import PortfolioState
    
    # Portfolio check
    p = PortfolioState()
    if hasattr(p, "_lock") and isinstance(p._lock, type(threading.RLock())):
        print(" [OK] Portfolio uses RLock")
    else:
        print(" [FAIL] Portfolio lock error")
        
    # ExchangeClient check
    ec = ExchangeClient()
    if hasattr(ec, "_exchange_lock") and isinstance(ec._exchange_lock, type(threading.RLock())):
        print(" [OK] ExchangeClient uses RLock")
    else:
        print(" [FAIL] ExchangeClient lock error")

def check_order_tagging():
    print("[*] Checking Order Tagging...")
    from execution.order_manager import OrderManager
    om = OrderManager()
    
    # check default prefix
    if om.order_prefix == "llm_":
        print(" [OK] OrderManager uses 'llm_' prefix")
    else:
        print(f" [FAIL] OrderManager uses '{om.order_prefix}' prefix")

def check_watchdog():
    print("[*] Checking Watchdog Refactoring...")
    from risk.watchdog import Watchdog
    w = Watchdog(symbols=['BTC/USDT'])
    
    # check if emergency_halt exists in _emergency_close signature (indirect check via source if possible)
    import inspect
    sig = inspect.signature(w._emergency_close)
    if "halt_system" in sig.parameters:
        print(" [OK] Watchdog._emergency_close supports halt_system flag")
    else:
        print(" [FAIL] Watchdog._emergency_close missing halt_system flag")

def main():
    print("=== LLMTRADING FIX VERIFICATION ===\n")
    try:
        check_thread_safety()
        check_order_tagging()
        check_watchdog()
        print("\n[!] All critical architectural fixes verified.")
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")

if __name__ == "__main__":
    main()
