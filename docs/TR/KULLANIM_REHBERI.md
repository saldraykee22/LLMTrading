# LLM Trading System - Kurulum ve Kullanim Rehberi

## Hizli Baslangic

### 1. Temel Kurulum (Ilk Kullanim)

```bash
# Python 3.10+ yuklu olunca
python --version

# Virtual environment olustur (ilk seferde)
python -m venv venv

# Bagimliliklari yukle (ilk seferde)
pip install -r requirements.txt
```

### 2. API Anahtarlarini Ayarla

```bash
# .env dosyasini olustur
copy .env.example .env

# .env dosyasini duzenle:
# - OPENROUTER_API_KEY=sk-or-v1-...
# - BINANCE_API_KEY=...
# - BINANCE_API_SECRET=...
```

### 3. Baslat!

#### **Windows Kullanicilari:**
```bash
# Cift tikla veya komut satirinda:
.\baslat.bat
```

**Menu gorunecek:**
```
+====================================================================+
|                        MAIN MENU                                   |
+====================================================================+

 1) Health Check
 2) Paper Trading - BTC/USDT (1H candles)
 3) Paper Trading - BTC/USDT (15M candles)
 4) Paper Trading - Custom
 5) Live Trading (CAUTION!)
 6) Run Backtest
 7) Portfolio Status
 8) Test Suite
 9) Show Logs

 0) Exit
```

#### **Komut Satiri (CLI) Kullanicilari:**
```bash
# Saglik kontrolu
python cli.py health

# Paper trading baslat
python cli.py run --symbol BTC/USDT --interval 1h --watchdog

# Portfoy durumu
python cli.py portfolio

# Piyasa taramasi
python cli.py scan

# Tum komutlar:
python cli.py --help
```

---

## Adim Adim Kullanim

### Adim 1: Saglik Kontrolu ✅

**baslat.bat ile:**
- Menu'den `1` secin

**CLI ile:**
```bash
python cli.py health
```

**Beklenen Sonuc:**
```
✅ TU M KONTROLLER BASARILI - Sistem hazir!
```

### Adim 2: Paper Trading Test (24+ saat onerilir) 📊

**baslat.bat ile:**
- Menu'den `2` (BTC/USDT, 1 saatlik mumlar)
- Veya `3` (BTC/USDT, 15 dakikalik mumlar)

**CLI ile:**
```bash
# 1 saatlik mumlar
python cli.py run --symbol BTC/USDT --interval 1h --watchdog

# 15 dakikalik mumlar
python cli.py run --symbol ETH/USDT --interval 15m --watchdog

# Otomatik piyasa taramasi ile
python cli.py run --symbol BTC/USDT --interval 1h --auto-scan --watchdog
```

**Durdurmak icin:** `Ctrl+C`

### Adim 3: Portfoy Durumunu Kontrol Et 💰

**baslat.bat ile:**
- Menu'den `7`

**CLI ile:**
```bash
python cli.py portfolio
```

**Ornek Cikti:**
```
Baslangic Nakit:    $10,000.00
Su Anki Nakit:      $6,650.00
Toplam Ozvarlik:    $10,542.86
Toplam P&L:         $542.86

▶ ACIK POZISYONLAR (1)
  BTC/USDT
    Taraf:      LONG
    Giris:      $67,000.00
    Miktar:     0.050000
    Stop-Loss:  $65,000.00
    Take-Profit:$72,000.00
    P&L:        $542.86 (16.20%)
```

### Adim 4: Backtest (Istege Bagli) 📈

**baslat.bat ile:**
- Menu'den `6`

**CLI ile:**
```bash
python cli.py backtest --symbol BTC/USDT --days 90
```

### Adim 5: Canli Trading (DIKKAT!) ⚠️

**ONCELIKLE:**
- ✅ En az 24 saat paper trading yap
- ✅ .env dosyasinda `TRADING_MODE=live` ayarla
- ✅ .env dosyasinda `CONFIRM_LIVE_TRADE=true` ayarla
- ✅ Kucuk bir miktarla basla
- ✅ API withdraw iznini kapat

**baslat.bat ile:**
- Menu'den `5`
- Uyariyi kabul et
- Sembol ve interval gir

**CLI ile:**
```bash
python cli.py run --symbol BTC/USDT --interval 1h --execute --watchdog
```

---

## Ozellestirme

### Interval Degistirme

```bash
# 5 dakikalik mumlar
python cli.py run --symbol BTC/USDT --interval 5m

# 30 dakikalik mumlar
python cli.py run --symbol ETH/USDT --interval 30m

# 4 saatlik mumlar
python cli.py run --symbol BTC/USDT --interval 4h

# Gunluk mumlar
python cli.py run --symbol BTC/USDT --interval 1d
```

### Farkli Semboller

```bash
# Ethereum
python cli.py run --symbol ETH/USDT --interval 1h

# Solana
python cli.py run --symbol SOL/USDT --interval 1h

# BIST hisseleri (Yahoo Finance)
python cli.py run --symbol BIMAS.IS --interval 1d

# ABD hisseleri
python cli.py run --symbol AAPL --interval 1d
```

### Otomatik Piyasa Taramasi

```bash
# Bot kendi adaylarini bulsun
python cli.py run --symbol BTC/USDT --interval 1h --auto-scan --watchdog
```

### Sinirli Dongu (Test Icin)

```bash
# Sadece 10 dongu yap ve dur
python cli.py run --symbol BTC/USDT --interval 1h --max-cycles 10
```

---

## Sorun Giderme

### "Python bulunamadi"
```bash
# Python 3.10+ yukleyin
https://www.python.org/downloads/

# Yukleme sonrasi yeni terminal acin
```

### "Virtual environment bulunamadi"
```bash
# Manuel olustur
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

### "Bagimlilik hatasi"
```bash
# Yeniden yukle
pip install -r requirements.txt --upgrade
```

### "API anahtari gecersiz"
```bash
# Binance: https://www.binance.com/en/my/settings/api_management
# OpenRouter: https://openrouter.ai/keys

# .env dosyasini kontrol edin
```

### "Portfoy dosyasi okunamadi"
```bash
# Dosyayi sil, yenisi olusur
del data\portfolio_state.json  # Windows
rm data/portfolio_state.json   # Linux/Mac
```

### "Circuit Breaker aktif"
```bash
# Nedenini kontrol et
python cli.py status

# Eger manuel STOP varsa kaldir
del data\STOP  # Windows
rm data/STOP   # Linux/Mac

# Veya
python -c "from risk.circuit_breaker import CircuitBreaker; cb = CircuitBreaker(); cb.resume()"
```

---

## Guvenlik

### API Anahtari Guvenligi

1. **Sadece Spot Trading izni verin**
2. **Withdraw (para cekme) iznini KAPATIN**
3. **2FA aktif edin**
4. **API anahtarlarini gizli tutun**
5. **.env dosyasini koruyun**

```bash
# Linux/Mac'te dosya izinleri
chmod 600 .env
```

### Paper vs Live Trading

**Paper Trading (Onerilen Baslangic):**
- Sanal para
- Gercek risk yok
- Strateji testi icin ideal

**Live Trading (Dikkat!):**
- Gercek para
- Gercek risk
- Kucuk miktarla baslayin

### Acil Durdurma

**Yontem 1: baslat.bat**
- Menu'den `0` (Exit)

**Yontem 2: Ctrl+C**
- Terminal'de `Ctrl+C` basin

**Yontem 3: STOP dosyasi**
```bash
# data/STOP dosyasi olustur
type nul > data\STOP  # Windows
touch data/STOP       # Linux/Mac

# Bot bir sonraki dongude duracak
```

---

## Monitoring

### Loglari Izleme

**baslat.bat ile:**
- Menu'den `9`

**CLI ile:**
```bash
python cli.py logs -n 100  # Son 100 satir
```

### Sistem Durumu

```bash
python cli.py status
```

**Gosterilen Bilgiler:**
- Circuit Breaker durumu
- Art arda kayip sayisi
- LLM hata sayisi
- Portfoy ozeti

### Test Suite

```bash
python cli.py tests
```

**Beklenen:** 15/15 test gecti

---

## Ileri Seviye

### Yapilandirma Dosyalari

**`.env` - API Anahtarlari:**
```bash
OPENROUTER_API_KEY=sk-or-v1-...
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
TRADING_MODE=paper  # paper | live
CONFIRM_LIVE_TRADE=false
```

**`config/trading_params.yaml` - Strateji Parametreleri:**
```yaml
risk:
  max_position_pct: 0.05      # Tek pozisyon max %5
  max_drawdown_pct: 0.15      # Max %15 dusus -> dur
  max_consecutive_losses: 5   # Art arda 5 kayip -> dur

execution:
  mode: paper                 # paper | live
  default_order_type: limit   # limit | market

watchdog:
  enabled: true
  crash_1m_pct: 0.03          # 1 dakikada %3 dusus -> acil cikis
```

### Custom Stratejiler

1. `config/trading_params.yaml` dosyasini duzenle
2. Risk parametrelerini degistir
3. Bot'u yeniden baslat

---

## Yardim ve Destek

### Dokumantasyon
- `HIZLI_BASLANGIC.md` - Hizli baslangic kilavuzu
- `docs/` klasoru - Detayli dokumantasyon
- `README.md` - Proje ozeti

### Komut Yardimi
```bash
# CLI yardim
python cli.py --help
python cli.py run --help
python cli.py backtest --help
```

### Log Dosyalari
```bash
# Trading loglari
logs/trading.log

# Hata loglari
error.log
```

---

## Sonraki Adimlar

1. ✅ **Health Check:** `python cli.py health`
2. ✅ **Paper Trading:** En az 24 saat test
3. ✅ **Backtest:** Gecmis performans analizi
4. ⏳ **Canli Trading:** Kucuk miktarla basla
5. 📊 **Monitoring:** `python cli.py status` ile izle

---

**Iyi Islemler! 🚀**

**Unutmayin:** Trading risk icerir. Sadece kaybetmeyi goze alabileceginiz miktarla islem yapin.
