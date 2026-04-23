# LLMTrading - Lock Ordering & Concurrency Guide

## 📋 Özet

Bu doküman, LLMTrading sistemindeki thread-safety ve lock management best practices'lerini açıklar.

---

## 🔒 Lock Hierarchy (Öncelik Sırası)

Deadlock'ları önlemek için **TÜM** modüllerde şu lock sırası kullanılır:

```
1. _portfolio_lock (risk/portfolio.py)
   ↓
2. _exchange_lock (execution/exchange_client.py)
   ↓
3. _exchange_public_lock / _exchange_private_lock (data/market_data.py)
   ↓
4. Diğer modül-specific lock'lar
```

### ⚠️ KURALLAR

1. **Her zaman yukarıdaki sırayla lock al**
2. **Nested lock'larda üst seviye lock'ı önce al**
3. **Lock tutulurken network call yapma** (deadlock riski)
4. **Lock timeout kullan** (30 saniye default)

---

## 📁 Modül Bazlı Lock Stratejileri

### `risk/portfolio.py`

```python
from risk.portfolio import _portfolio_lock

# DOĞRU - Lock ile korunmuş işlem
with _portfolio_lock:
    portfolio.cash -= cost
    portfolio.positions.append(position)
    portfolio.save_to_file()

# DOĞRU - Lock DIŞINDA correlation check (deadlock önleme)
with _portfolio_lock:
    positions_copy = [p.symbol for p in self.positions]
    market_data_copy = {...}

# Lock DIŞINDA
checker = CorrelationChecker(positions_copy, market_data_copy)
result = checker.check_positions(...)

# Tekrar lock al
with _portfolio_lock:
    if not result["is_safe"]:
        return None
```

### `execution/exchange_client.py`

```python
from risk.portfolio import _portfolio_lock

# DOĞRU - Lock sırası: portfolio → exchange
with _portfolio_lock:
    # Portfolio state read/write
    if not self._check_connection():
        return error
    
    with self._exchange_lock:
        # Exchange operations
        result = exchange.create_order(...)

# YANLIŞ - Ters lock sırası (deadlock riski!)
with self._exchange_lock:
    with _portfolio_lock:  # ❌ DEADLOCK!
        ...
```

### `data/market_data.py`

```python
# Thread-safe exchange instance kullanımı
class MarketDataClient:
    def __init__(self):
        self._exchange_public_lock = threading.RLock()
    
    def fetch_tickers(self):
        exchange = self._get_public_exchange()
        with self._exchange_public_lock:
            return exchange.fetch_tickers()
```

---

## 🛡️ Security Best Practices

### Dynamic Rules Sanitization

`agents/trader.py`'de dynamic rules injection koruması:

```python
from agents.trader import _sanitize_dynamic_rules

# Tüm dynamic rules sanitize edilmeli
sanitized_rules = _sanitize_dynamic_rules(user_provided_rules)

# Security layers:
# 1. Max length enforcement (2000 chars)
# 2. Unicode normalization (NFKC)
# 3. Template injection blocking ({{}}, {%}, {#})
# 4. Code injection blocking (eval, exec, __import__)
# 5. HTML/JS injection blocking
# 6. Path traversal blocking
# 7. Base64 payload detection
# 8. Control character removal
```

### API Key Protection

```python
# DOĞRU - API key masking before logging
from config.settings import mask_api_key

logger.info("Binance API Key: %s", mask_api_key(settings.binance_api_key))
# Output: "Binance API Key: sk1234****5678"

# YANLIŞ - API key'ı loglama
logger.info("Binance API Key: %s", settings.binance_api_key)  # ❌
```

---

## 🧪 Testing Guidelines

### Concurrency Test Örneği

```python
import threading
from risk.portfolio import PortfolioState

def test_concurrent_position_access():
    portfolio = PortfolioState()
    errors = []
    
    def worker(i):
        try:
            portfolio.open_position(...)
            portfolio.close_position(...)
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(errors) == 0, f"Concurrency errors: {errors}"
```

---

## 📊 Monitoring

### Lock Acquisition Logging

```python
# portfolio.py'de otomatik logging
with _portfolio_lock:  # 5 saniyeden uzun sürerse uyarı
    # long operation
    pass

# Output: "⚠️  Portfolio lock acquisition took 7.2s (threshold: 5s)"
```

### Deadlock Detection

Eğer lock acquisition 30 saniyeyi aşarsa:
1. Timeout exception fırlat
2. Stack trace logla
3. Circuit breaker tetikle

---

## 🚨 Common Pitfalls

### ❌ YANLIŞ: Lock içinde network call

```python
with _portfolio_lock:
    tickers = market_client.fetch_tickers()  # ❌ Network call!
```

### ✅ DOĞRU: Network call lock dışında

```python
tickers = market_client.fetch_tickers()  # Lock DIŞINDA
with _portfolio_lock:
    # Process tickers
    pass
```

### ❌ YANLIŞ: Ters lock sırası

```python
with exchange_lock:
    with portfolio_lock:  # ❌ Deadlock riski!
        pass
```

### ✅ DOĞRU: Tutarlı lock sırası

```python
with portfolio_lock:
    with exchange_lock:  # ✓ Doğru sıra
        pass
```

---

## 📚 Referanslar

- Python threading documentation: https://docs.python.org/3/library/threading.html
- CCXT thread-safety: https://github.com/ccxt/ccxt/wiki/Manual#thread-safety
- Deadlock prevention patterns: https://en.wikipedia.org/wiki/Deadlock#Prevention

---

**Son Güncelleme:** 2026-04-22
**Yazar:** LLMTrading Code Review Team
