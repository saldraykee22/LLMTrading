# 🚀 LLMTrading - Deployment Guide

**Version:** 2.0.0  
**Last Updated:** 2026-04-22  
**Status:** ✅ Production Ready

---

## 📋 İçindekiler

1. [Önkoşullar](#önkoşullar)
2. [Kurulum](#kurulum)
3. [Konfigürasyon](#konfigürasyon)
4. [Test](#test)
5. [Deployment](#deployment)
6. [Monitoring](#monitoring)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 Önkoşullar

### Sistem Gereksinimleri

- **Python:** 3.10+ (Tested: 3.13.5)
- **OS:** Windows 10/11, Linux (Ubuntu 20.04+), macOS 12+
- **RAM:** Min 4GB, Önerilen: 8GB
- **Disk:** Min 1GB free space
- **Network:** Binance API erişimi

### Bağımlılıklar

```bash
# Python packages
pip install -r requirements.txt

# Ana paketler:
# - ccxt>=4.0.0
# - pandas>=2.0.0
# - numpy>=1.24.0
# - pydantic>=2.0.0
# - langchain>=0.1.0
# - yfinance>=0.2.0
```

---

## 🔧 Kurulum

### 1. Repository Clone

```bash
git clone https://github.com/your-org/LLMTrading.git
cd LLMTrading
```

### 2. Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Bağımlılıkları Yükle

```bash
pip install -r requirements.txt
```

### 4. Konfigürasyon

```bash
# .env dosyasını oluştur
cp .env.example .env

# Düzenle
notepad .env  # Windows
nano .env     # Linux/macOS
```

---

## ⚙️ Konfigürasyon

### .env Dosyası

```ini
# OpenRouter API
OPENROUTER_API_KEY=your_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Binance (Testnet)
BINANCE_API_KEY=your_binance_key
BINANCE_API_SECRET=your_binance_secret
BINANCE_TESTNET=true

# Trading Mode
TRADING_MODE=paper  # paper | live
LOG_LEVEL=INFO

# Telegram (Opsiyonel)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### trading_params.yaml

```yaml
risk:
  max_position_pct: 0.05  # %5
  max_portfolio_risk_pct: 0.20  # %20
  max_drawdown_pct: 0.15  # %15
  max_open_positions: 5

execution:
  mode: paper  # paper | live
  default_order_type: limit
  slippage_pct: 0.001
```

---

## 🧪 Test

### Health Check

```bash
python scripts/health_check.py
```

**Beklenen Çıktı:**
```
✅ PASSED:
  ✓ Python Version: 3.13.5
  ✓ Dependencies: 8 packages checked
  ✓ Config Files: All required files present
  ✓ Circuit Breaker: Circuit CLOSED
  ✓ System Status: RUNNING
```

### Security Audit

```bash
python scripts/security_audit.py
```

**Beklenen Çıktı:**
```
✅ Security audit PASSED
Issues: 0
Warnings: 0
```

### Unit Tests

```bash
# Tüm testler
pytest tests/ -v

# Spesifik test grupları
pytest tests/test_lock_ordering.py -v
pytest tests/test_injection_prevention.py -v
pytest tests/test_validation.py -v
pytest tests/test_e2e_trading.py -v
pytest tests/test_performance.py -v
```

**Test Coverage Hedef:** >80%

---

## 🚀 Deployment

### Paper Trading (Önerilen Başlangıç)

```bash
# Paper trading başlat
python scripts/run_live.py --paper --symbol BTC/USDT

# Paper trading durumu
python scripts/run_live.py --paper --status
```

### Live Trading (Dikkat!)

```bash
# 1. Önce testnet'te test et
export BINANCE_TESTNET=true
python scripts/run_live.py --live --symbol BTC/USDT

# 2. Küçük pozisyonlarla başla
# trading_params.yaml: max_position_pct: 0.01 (%1)

# 3. Canlı moda geç
export BINANCE_TESTNET=false
python scripts/run_live.py --live --symbol BTC/USDT --confirm
```

### Production Checklist

- [ ] Health check passed
- [ ] Security audit passed
- [ ] All tests passed
- [ ] .env permissions secure (chmod 600)
- [ ] API keys rotated (production-specific)
- [ ] Stop file path verified
- [ ] Emergency contacts documented
- [ ] Monitoring alerts configured

---

## 📊 Monitoring

### Real-time Dashboard

```bash
# Dashboard başlat (eğer varsa)
python dashboard/server.py

# Browser'da aç
http://localhost:8000
```

### Metrics

**Ölçümler:**
- Trade execution latency (p50, p95, p99)
- Lock acquisition time
- Error rates by component
- Fallback usage frequency
- Portfolio P&L (real-time)
- API rate limit headroom

### Logs

```bash
# Real-time log viewing
tail -f logs/trading.log

# Error logs only
grep ERROR logs/trading.log | tail -50

# Today's trades
grep "Pozisyon" logs/trading.log | grep $(date +%Y-%m-%d)
```

### Alerts

**Slack/Telegram Entegrasyonu:**
```yaml
# .env dosyasına ekle
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Alert tetikleyiciler:
# - Error rate > 1% (5 min)
# - Drawdown > 10%
# - Circuit breaker open
# - API connection lost > 5 min
```

---

## 🔧 Troubleshooting

### Common Issues

#### 1. "ModuleNotFoundError: No module named 'risk'"

**Çözüm:**
```bash
# PYTHONPATH ayarla
export PYTHONPATH=$PYTHONPATH:$(pwd)  # Linux/macOS
set PYTHONPATH=%PYTHONPATH%;%cd%      # Windows

# Veya script içinden çalıştır
python -c "import sys; sys.path.insert(0, '.'); from scripts.health_check import *"
```

#### 2. "Circuit breaker is OPEN"

**Çözüm:**
```bash
# Circuit breaker durumunu kontrol et
python -c "from risk.circuit_breaker import CircuitBreaker; cb = CircuitBreaker(); print(cb.get_state())"

# Reset (eğer timeout geçtiyse otomatik reset olur)
# Manuel reset için sistemi yeniden başlat
```

#### 3. "API bağlantı kesildi"

**Çözüm:**
```bash
# Network bağlantısını kontrol et
ping api.binance.com

# Firewall/proxy ayarlarını kontrol et
# API key geçerliliğini kontrol et
python scripts/test_exchange_config.py
```

#### 4. "Portfolio state corrupted"

**Çözüm:**
```bash
# Backup al
cp data/portfolio_state.json data/portfolio_state.json.bak

# State'i sıfırla (dikkatli!)
rm data/portfolio_state.json

# Sistem yeniden başlatıldığında yeni state oluşur
```

#### 5. "Lock timeout"

**Çözüm:**
```bash
# Lock contention log'larını incele
grep "lock acquisition" logs/trading.log

# Performance test çalıştır
pytest tests/test_performance.py::TestLockPerformance -v

# Eğer persistent issue ise, uzman desteği al
```

### Emergency Procedures

#### Emergency Stop

```bash
# 1. STOP dosyası oluştur
touch data/STOP  # Linux/macOS
type nul > data/STOP  # Windows

# 2. Tüm pozisyonları kapat
python scripts/close_all_positions.py

# 3. Sistemi durdur
# Ctrl+C (running process'te)
```

#### Emergency Restart

```bash
# 1. STOP dosyasını kaldır
rm data/STOP  # Linux/macOS
del data/STOP  # Windows

# 2. State'i kontrol et
python scripts/health_check.py

# 3. Sistemi yeniden başlat
python scripts/run_live.py --paper
```

---

## 📞 Support

### Documentation

- [Architecture Guide](docs/ARCHITECTURE.md)
- [Lock Ordering Guide](docs/LOCK_ORDERING_GUIDE.md)
- [API Reference](docs/API_REFERENCE.md)

### Contacts

- **Technical Lead:** [email]
- **Security Team:** [email]
- **On-Call:** [phone]

### Resources

- GitHub Issues: https://github.com/your-org/LLMTrading/issues
- Status Page: https://status.your-domain.com
- Runbook: [Internal Wiki Link]

---

## ✅ Deployment Verification

Post-deployment checklist:

```bash
# 1. Health check
python scripts/health_check.py
# Expected: PASSED

# 2. Security audit
python scripts/security_audit.py
# Expected: PASSED

# 3. Test suite
pytest tests/ -x -v
# Expected: 100% pass rate

# 4. Paper trading (1 hour)
python scripts/run_live.py --paper --duration 1h
# Expected: Zero errors

# 5. Monitoring check
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

---

**Son Güncelleme:** 2026-04-22  
**Versiyon:** 2.0.0  
**Durum:** ✅ Production Ready
