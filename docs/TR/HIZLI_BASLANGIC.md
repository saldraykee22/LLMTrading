# LLM Trading System - Hızlı Başlangıç Kılavuzu

## 🚀 Hızlı Başlangıç

### 1. Temel Kurulum

```bash
# Python 3.10+ yüklü olmalı
python --version

# Virtual environment oluştur
python -m venv venv

# Aktif et (Windows)
venv\Scripts\activate

# Aktif et (Linux/Mac)
source venv/bin/activate

# Bağımlılıkları yükle
pip install -r requirements.txt
```

### 2. API Anahtarlarını Ayarla

```bash
# .env.example dosyasını kopyala
copy .env.example .env  # Windows
cp .env.example .env    # Linux/Mac

# .env dosyasını düzenle ve API anahtarlarını ekle
# - OpenRouter API key
# - Binance API key & secret
```

### 3. Sistem Başlat

#### **Yöntem A: Kolay Başlatma (Önerilen)**

```bash
# Windows
baslat.bat

# Linux/Mac
chmod +x baslat.sh
./baslat.sh
```

Bu size interaktif bir menü gösterecek.

#### **Yöntem B: Komut Satırı (CLI)**

```bash
# Sağlık kontrolü
python cli.py health

# Paper trading başlat (BTC/USDT, 1 saatlik mumlar)
python cli.py run --symbol BTC/USDT --interval 1h --watchdog

# Paper trading (15 dakikalık mumlar)
python cli.py run --symbol ETH/USDT --interval 15m

# Piyasa taraması
python cli.py scan

# Portföy durumu
python cli.py portfolio

# Sistem durumu
python cli.py status

# Logları göster
python cli.py logs -n 100

# Test suite
python cli.py tests
```

#### **Yöntem C: Doğrudan Script**

```bash
# Paper trading
python scripts/run_live.py --symbol BTC/USDT --interval 1h --watchdog

# Canlı trading (DİKKAT!)
python scripts/run_live.py --symbol BTC/USDT --interval 1h --execute --watchdog

# Backtest
python scripts/run_backtest.py --symbol BTC/USDT --days 90
```

---

## 📋 CLI Komut Referansı

### `python cli.py health`

Sistem sağlık kontrolü yapar:
- Python versiyonu
- Kritik kütüphaneler
- API anahtarları
- Klasör izinleri
- ChromaDB bağlantısı
- Borsa bağlantısı

**Çıktı:**
```
✅ TÜM KONTROLLER BAŞARILI - Sistem hazır!
```

---

### `python cli.py run`

Trading bot'u çalıştırır.

**Parametreler:**
- `--symbol, -s`: Varlık sembolü (zorunlu)
- `--interval, -i`: Mum aralığı (varsayılan: 1h)
- `--watchdog, -w`: Flash crash koruması (önerilir)
- `--execute, -x`: Canlı işlem (DİKKAT!)
- `--auto-scan`: Otomatik piyasa taraması
- `--max-cycles`: Maksimum döngü sayısı (0=sınırsız)

**Örnekler:**
```bash
# Paper trading, BTC/USDT, 1 saatlik mumlar
python cli.py run --symbol BTC/USDT --interval 1h --watchdog

# Paper trading, ETH/USDT, 15 dakikalık mumlar, otomatik tarama
python cli.py run --symbol ETH/USDT --interval 15m --auto-scan

# Canlı trading (DİKKAT!)
python cli.py run --symbol BTC/USDT --interval 1h --execute --watchdog

# Sınırlı döngü (test için)
python cli.py run --symbol BTC/USDT --interval 1h --max-cycles 10
```

---

### `python cli.py backtest`

Geçmiş verilerle backtest yapar.

**Parametreler:**
- `--symbol, -s`: Varlık sembolü (zorunlu)
- `--days, -d`: Geçmiş gün sayısı (varsayılan: 90)

**Örnek:**
```bash
python cli.py backtest --symbol BTC/USDT --days 90
```

---

### `python cli.py portfolio`

Mevcut portföy durumunu gösterir.

**Gösterilen Bilgiler:**
- Başlangıç nakit
- Şu anki nakit
- Toplam özvarlık
- Toplam P&L
- Günlük P&L
- Maksimum drawdown
- Alpha (benchmark'e göre performans)
- Açık pozisyonlar (detaylı)

**Örnek:**
```bash
python cli.py portfolio
```

---

### `python cli.py scan`

Piyasayı tarar ve fırsatları bulur.

**Özellikler:**
- 24 saatlik hacim taraması
- Fiyat değişimi analizi
- Lead Scout AI ile skorlama
- En iyi 10 adayı gösterir

**Örnek:**
```bash
python cli.py scan
```

---

### `python cli.py status`

Sistem durumunu gösterir:
- Circuit Breaker durumu
- Art arda kayıp sayısı
- LLM hata sayısı
- Portföy özeti

**Örnek:**
```bash
python cli.py status
```

---

### `python cli.py logs`

Son log satırlarını gösterir.

**Parametreler:**
- `--lines, -n`: Gösterilecek satır sayısı (varsayılan: 50)

**Örnek:**
```bash
python cli.py logs -n 100
```

---

### `python cli.py tests`

Integration test suite'ini çalıştırır.

**Parametreler:**
- `--verbose, -v`: Detaylı çıktı

**Örnek:**
```bash
python cli.py tests
python cli.py tests -v  # Detaylı
```

---

## ⚙️ Yapılandırma

### `.env` Dosyası

```bash
# LLM Providers
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx
OPENROUTER_DEFAULT_MODEL=deepseek/deepseek-chat-v3-0324

# Binance
BINANCE_API_KEY=xxxxxxxx
BINANCE_API_SECRET=xxxxxxxx
BINANCE_TESTNET=true  # Testnet için

# Trading Mode
TRADING_MODE=paper     # paper | live
CONFIRM_LIVE_TRADE=false  # Canlı işlem için true yapın
```

### `config/trading_params.yaml`

Strateji parametrelerini buradan yönetin:

```yaml
risk:
  max_position_pct: 0.05      # Tek pozisyon max %5
  max_drawdown_pct: 0.15      # Max %15 drawdown
  max_consecutive_losses: 5   # Art arda 5 kayıp → dur

execution:
  mode: paper                 # paper | live
  default_order_type: limit   # limit | market

watchdog:
  enabled: true
  crash_1m_pct: 0.03          # 1 dakikada %3 düşüş → acil çıkış
```

---

## 🛡️ Güvenlik

### Paper Trading (Önerilen Başlangıç)

```bash
# .env dosyasında:
TRADING_MODE=paper
```

- Sanal para ile işlem
- Gerçek risk yok
- Strateji testi için ideal

### Live Trading (DİKKAT!)

```bash
# .env dosyasında:
TRADING_MODE=live
CONFIRM_LIVE_TRADE=true
```

**Güvenlik Kontrolleri:**
1. ✅ Küçük miktarla başlayın
2. ✅ API withdraw iznini kapatın
3. ✅ Sadece spot trading izni verin
4. ✅ 2FA aktif edin
5. ✅ API anahtarlarını gizli tutun
6. ✅ .env dosyasını korumaya alın (`chmod 600 .env`)

---

## 📊 Monitoring

### Circuit Breaker

Sistem otomatik olarak durur:
- Art arda 5 kayıp işlem
- Günlük %3 kayıp
- Art arda 10 LLM hatası
- Manuel STOP dosyası (`data/STOP`)

**Manuel Durdurma:**
```bash
# data/STOP dosyası oluştur
type nul > data\STOP  # Windows
touch data/STOP       # Linux/Mac

# Veya CLI ile
python -c "from risk.circuit_breaker import CircuitBreaker; CircuitBreaker.manual_stop()"
```

**Yeniden Başlatma:**
```bash
# STOP dosyasını sil
del data\STOP  # Windows
rm data/STOP   # Linux/Mac

# Veya CLI ile
python -c "from risk.circuit_breaker import CircuitBreaker; cb = CircuitBreaker(); cb.resume()"
```

---

## 🧪 Test

```bash
# Integration testleri
python cli.py tests

# Health check
python cli.py health

# Paper trading (en az 24 saat önerilir)
python cli.py run --symbol BTC/USDT --interval 1h --watchdog
```

---

## 🆘 Sorun Giderme

### "Python bulunamadı"
```bash
# Python 3.10+ yükleyin
https://www.python.org/downloads/
```

### "API anahtarı hatalı"
```bash
# .env dosyasını kontrol edin
# Binance: https://www.binance.com/en/my/settings/api-management
# OpenRouter: https://openrouter.ai/keys
```

### "Bağımlılık hatası"
```bash
# Bağımlılıkları yeniden yükle
pip install -r requirements.txt --upgrade
```

### "Portföy dosyası okunamadı"
```bash
# Dosyayı sil, yeni oluşturulacak
del data\portfolio_state.json
```

---

## 📈 Sonraki Adımlar

1. **Health Check:** `python cli.py health` ✅
2. **Paper Trading:** En az 24 saat test
3. **Backtest:** Geçmiş performans analizi
4. **Canlı Trading:** Küçük miktarla başla
5. **Monitoring:** `python cli.py status` ile izle

---

## 📞 Yardım

- **Dokümantasyon:** `docs/` klasörü
- **Testler:** `tests/` klasörü
- **Örnekler:** `scripts/` klasörü

**İyi işlemler! 🚀**
