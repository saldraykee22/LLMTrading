# LLM Autonomous Trading System

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Status](https://img.shields.io/badge/Durum-Development-yellow.svg)

## Proje Ozeti

Bu proje, finansal piyasalarda (Kripto, BIST, ABD Hisse Senetleri) bagimsiz (otonom) kararlar alabilen, **LangGraph tabanli coklu ajan (Multi-Agent) mimarisine** sahip bir yapay zeka alim-satim (trading) sistemidir.

Proje saf nicel (quantitative) veya saf duygusal (sentiment) analiz yerine, her iki disiplini birlestiren tam otonom bir islem masasi (trading desk) gibi calismaktadir. **Modellerin uydurma (halusnasyon) riskini en aza indirmek** icin *Bull vs Bear Tartisma (Debate)* filtresi ve bagimsiz bir Risk Yoneticisi kullanir.

### Temel Ozellikler

- **Coklu Ajan Mimarisi:** Coordinator, Research, Debate, Risk, Trader ajanlari LangGraph uzerinden sirasyla calisir
- **Portföy Yöneticisi:** Birden fazla varligi paralel analiz eder, bileşik skor ve CVaR ile optimal dagilim yapar
- **Halusnasyon Filtresi:** Bull vs Bear tartisma mekanizmasi ile LLM kararlarinin dogrulanmasi
- **Deterministik Risk Korumalari:** Drawdown, gunluk kayip ve pozisyon limitleri LLM'den bagimsiz olarak uygulanir
- **Portfoy Kaliciligi (Persistence):** JSON tabanli kayit sistemi ile bot restart sonrasi durum korunur
- **Paper Trading:** Gercek borsaya hic ulas madan slippage ve komisyon simule eden test modu
- **Circuit Breaker:** Art arda kayip, gunluk limit veya manuel STOP ile otomatik durma
- **Walk-Forward Backtest:** Overfitting tespiti icin kayan pencere validasyonu
- **Daemon Mode:** Surekli calisan dongu, Ctrl+C ile guvenli kapanis, sembol ve interval secenekleri
- **Watchdog (Flash Crash Korumasi):** Arka planda fiyat izleme, ani dususlerde acil satis
- **Maliyet Optimizasyonu:** Prompt sikistirma, LLM cache, max_tokens sinirlari ile %72-88 API tasarrufu

---

## Dokumantasyon

Gelistiricilerin ve AI ajanlarinin sisteme hizli entegrasyon saglamasi icin asagidaki belgelere basvurun:

| Belge | Aciklama |
|-------|----------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Sistem veri akisi, klasor yapisi, modul aciklamalari |
| [AGENTS.md](docs/AGENTS.md) | LangGraph ajan grafigi, her ajanin I/O, yeni hold_decision dugumu |
| [RISK_MANAGEMENT.md](docs/RISK_MANAGEMENT.md) | Katlmali risk korumasi: Circuit Breaker, Regime, deterministik kontroller, CVaR |

---

## Hizli Baslangic (Quick Start)

### 1. Kurulum

```bash
# Virtual environment olustur
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# Bagimliliklari yukle
pip install -r requirements.txt
```

### 2. Yapilandirma

```bash
# Ornek env dosyasini kopyala
copy .env.example .env
```

`.env` icinde doldurulan anahtarlar:

```
OPENROUTER_API_KEY=sk-or-...     # Zorunlu (birincil LLM)
BINANCE_API_KEY=...              # Canli islem icin
BINANCE_API_SECRET=...
EXECUTION_MODE=paper             # paper veya live
```

### 3. Calistirma

#### Daemon Modu (Surekli Calisma)

```bash
# Varsayilan: BTC/USDT, 15m interval, watchdog aktif
python scripts/run_live.py

# Birden fazla sembol, 30m interval
python scripts/run_live.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --interval 30m

# Tek sembol, 1 saatlik mumlar, watchdog kapali
python scripts/run_live.py --symbol BTC/USDT --interval 1h --no-watchdog

# Maksimum 10 dongu sonra dur (dry-run, emir gitmez)
python scripts/run_live.py --symbols BTC/USDT,ETH/USDT --max-cycles 10 --dry-run

# Ctrl+C ile guvenli kapanis (tumu pozisyonlar kaydedilir)
```

#### Tek Seferlik Calistirma (Geriye Uyumluluk)

```bash
# Paper trading modu (gercek emir gitmez)
python scripts/run_live.py --symbol BTC/USDT --max-cycles 1

# Emri gercekten gonder (--execute bayragi)
python scripts/run_live.py --symbol BTC/USDT --max-cycles 1 --execute

# Farkli semboller
python scripts/run_live.py --symbol AAPL --max-cycles 1
python scripts/run_live.py --symbol BIMAS --max-cycles 1

# Farkli LLM saglayici
python scripts/run_live.py --symbol BTC/USDT --provider deepseek --max-cycles 1
python scripts/run_live.py --symbol BTC/USDT --provider ollama --max-cycles 1
```

#### CLI Parametreleri

| Parametre | Varsayilan | Aciklama |
|-----------|-----------|----------|
| `--symbols` | BTC/USDT | Izlenecek semboller (virgulle ayrilmis) |
| `--symbol` | - | Tek sembol (geriye uyumlu) |
| `--interval` | 15m | Mum araligi (5m, 15m, 30m, 1h, 4h, 1d) |
| `--watchdog` | aktif | Flash crash korumasini acar/kapatir |
| `--max-cycles` | sinirsiz | Maksimum dongu sayisi |
| `--dry-run` | kapali | Emir gondermez, sadece analiz yapar |

### 4. Portföy Yönetimi (Multi-Asset)

```bash
# 3 coin için portföy analizi ve dağılım
python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT,SOL/USDT

# Max 3 pozisyon, min skor 0.2
python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT,SOL/USDT,AVAX/USDT --max-positions 3 --min-score 0.2

# Farklı LLM sağlayıcı ile
python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT --provider deepseek
```

Portföy yöneticisi:
- Her sembol için tam analiz pipeline'ı çalıştırır (Coordinator → Research → Debate → Risk)
- Bileşik skor hesaplar (sentiment %25, debate %35, trend %20, RSI %20)
- CVaR optimizasyonu ile optimal ağırlıkları belirler
- Nakıt dağılımını gösterir

### 5. Backtest

```bash
# Basit backtest (son 180 gun, gunluk mum)
python scripts/run_backtest.py --symbol BTC/USDT --days 180

# Farkli timeframe
python scripts/run_backtest.py --symbol BTC/USDT --days 90 --timeframe 1h

# Walk-forward validasyon (overfitting tespiti)
python scripts/run_backtest.py --symbol AAPL --days 365 --mode walk-forward
```

### 6. Circuit Breaker - Manuel Durdurma

```bash
# Botu hemen durdur (pipeline baslangicinda kontrol edilir)
echo. > data\STOP

# Devam ettir
del data\STOP
```

---

## Dashboard (Izleme Paneli)

`dashboard/index.html` dosyasini bir tarayicide acin. Eger `dashboard/server.py` calisiyorsa:
- Portföy durumu, P&L, drawdown gercek zamanli guncellenir (5 saniyelik polling)
- **Portföy dağılımı** tablosu (run_portfolio.py çıktısı) otomatik gösterilir
- Kapanmis islemler tablosu otomatik yenilenir
- Ajan iletisim gecmisi izlenebilir

API olmadan: Dashboard demo veri ile calisir, hata vermez.

---

## Watchdog (Flash Crash Korumasi)

Watchdog, arka planda ayri bir thread'de calisan ve fiyatlar surekli izleyen bir guvenlik mekanizmasidir.

### Acil Satis Kurallari

| Kosul | Aksiyon |
|-------|---------|
| 1 dakikada > %3 dusus | Hemen satis |
| 5 dakikada > %5 dusus | Hemen satis |
| 5 dakikada %2-5 dusus | Uyari gonder |

### Yapilandirma (`config/trading_params.yaml`)

```yaml
watchdog:
  enabled: true
  check_interval_seconds: 30
  flash_crash_1min_pct: 0.03
  flash_crash_5min_pct: 0.05
  alert_5min_pct: 0.02
```

---

## Maliyet Optimizasyonu

LLM API maliyetlerini dusurmek icin cok katmanli optimizasyon uygulanmistir.

### Tasarruf Yontemleri

| Yontem | Tasarruf | Aciklama |
|--------|----------|----------|
| **Prompt sikistirma** | %30-40 input token | Tum promptlar %40-50 kucultuldu |
| **Prompt cache** | %75-90 cached input | OpenRouter/DeepSeek cache isabetleri |
| **Sentiment cache** | %30-50 daha az LLM cagrisi | Son analiz cache'den dondurulur |
| **max_tokens sinirlari** | Runaway onleme | Her ajan icin cikti siniri belirlenmis |

### Toplam Tasarruf: ~%72-88 API maliyet azalmasi

### max_tokens Degerleri

| Ajan | max_tokens |
|------|-----------|
| Sentiment | 300 |
| Research | 500 |
| Debate | 400 |
| Moderator | 400 |
| Risk | 400 |
| Trader | 250 |

### JSON Mode

Tum LLM cagrilar `response_format={"type": "json_object"}` kullanir. Bu, cikti formatini garanti eder ve parse hatalarini azaltir.

---

## Proje Gecmisi & Degisiklik Ozeti

| Faz | Durum | Icerik |
|-----|-------|--------|
| Faz 0 | Tamamlandi | Temel mimari, LangGraph kurulumu, CCXT, yfinance entegrasyonu |
| **Faz 1** | **Tamamlandi** | Portfolio persistence, Paper Trading Engine, deterministik risk kontrolleri, retry loop kaldirildi |
| **Faz 2** | **Tamamlandi** | Circuit Breaker, Dashboard API polling, gunluk PNL sifirlama, LLM timeout/retry |
| **Faz 3** | **Tamamlandi** | Walk-forward backtest, MACD/BB kolon guvenlik, sentiment deduplication, ATR fallback stop-loss |
| **Faz 4** | **Tamamlandi** | **Portfolio Manager**: Multi-asset paralel analiz, bileşik skorlama, CVaR optimizasyonu, dashboard portföy görünümü |
| **Faz 4 Düzeltmeleri** | **Tamamlandi** | TradingMode import, phase tutarsizligi, _create_llm public, provider parametresi, dashboard güvenlik, dead variable'lar |
| **Faz 5** | **Tamamlandi** | **Daemon Mode**: Surekli calisan dongu, CLI arglari, guvenli kapanis, **Watchdog**: Flash crash korumasi, **Prompt Sikistirma**: %40-50 kucultme, **max_tokens + JSON Mode**: Tum LLM cagrilarina sinir, **Sentiment Cache**: LLM oncesi cache kontrolu, **Maliyet Optimizasyonu**: %72-88 API tasarrufu |
