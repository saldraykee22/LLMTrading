# LLM Autonomous Trading System

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Status](https://img.shields.io/badge/Durum-Production%20Ready-brightgreen.svg)

## Proje Ozeti

Bu proje, finansal piyasalarda (Kripto, BIST, ABD Hisse Senetleri) bagimsiz (otonom) kararlar alabilen, **LangGraph tabanli coklu ajan (Multi-Agent) mimarisine** sahip bir yapay zeka alim-satim (trading) sistemidir.

Proje saf nicel (quantitative) veya saf duygusal (sentiment) analiz yerine, her iki disiplini birlestiren tam otonom bir islem masasi (trading desk) gibi calismaktadir. **Modellerin uydurma (halusnasyon) riskini en aza indirmek** icin *Bull vs Bear Tartisma (Debate)* filtresi ve bagimsiz bir Risk Yoneticisi kullanir.

### Temel Ozellikler

- **Coklu Ajan Mimarisi:** Coordinator, Research, Debate, Risk, Trader ajanlari LangGraph uzerinden sirasyla calisir
- **Halusnasyon Filtresi:** Bull vs Bear tartisma mekanizmasi ile LLM kararlarinin dogrulanmasi
- **Deterministik Risk Korumalari:** Drawdown, gunluk kayip ve pozisyon limitleri LLM'den bagimsiz olarak uygulanir
- **Portfoy Kaliciligi (Persistence):** JSON tabanli kayit sistemi ile bot restart sonrasi durum korunur
- **Paper Trading:** Gercek borsaya hic ulas madan slippage ve komisyon simule eden test modu
- **Circuit Breaker:** Art arda kayip, gunluk limit veya manuel STOP ile otomatik durma
- **Walk-Forward Backtest:** Overfitting tespiti icin kayan pencere validasyonu

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

```bash
# Paper trading modu (gercek emir gitmez)
python scripts/run_live.py --symbol BTC/USDT

# Emri gercekten gonder (--execute bayragi)
python scripts/run_live.py --symbol BTC/USDT --execute

# Farkli semboller
python scripts/run_live.py --symbol AAPL
python scripts/run_live.py --symbol BIMAS

# Farkli LLM saglayici
python scripts/run_live.py --symbol BTC/USDT --provider deepseek
python scripts/run_live.py --symbol BTC/USDT --provider ollama
```

### 4. Backtest

```bash
# Basit backtest (son 180 gun, gunluk mum)
python scripts/run_backtest.py --symbol BTC/USDT --days 180

# Farkli timeframe
python scripts/run_backtest.py --symbol BTC/USDT --days 90 --timeframe 1h

# Walk-forward validasyon (overfitting tespiti)
python scripts/run_backtest.py --symbol AAPL --days 365 --mode walk-forward
```

### 5. Circuit Breaker - Manuel Durdurma

```bash
# Botu hemen durdur (pipeline baslangicinda kontrol edilir)
echo. > data\STOP

# Devam ettir
del data\STOP
```

---

## Dashboard (Izleme Paneli)

`dashboard/index.html` dosyasini bir tarayicide acin. Eger `dashboard/server.py` calisiyorsa:
- Portfolio durumu, P&L, drawdown gercek zamanli guncellenir (5 saniyelik polling)
- Kapanmis islemler tablosu otomatik yenilenir
- Ajan iletisim gecmisi izlenebilir

API olmadan: Dashboard demo veri ile calisir, hata vermez.

---

## Proje Gecmisi & Degisiklik Ozeti

| Faz | Durum | Icerik |
|-----|-------|--------|
| Faz 0 | Tamamlandi | Temel mimari, LangGraph kurulumu, CCXT, yfinance entegrasyonu |
| **Faz 1** | **Tamamlandi** | Portfolio persistence, Paper Trading Engine, deterministik risk kontrolleri, retry loop kaldirildi |
| **Faz 2** | **Tamamlandi** | Circuit Breaker, Dashboard API polling, gunluk PNL sifirlama, LLM timeout/retry |
| **Faz 3** | **Tamamlandi** | Walk-forward backtest, MACD/BB kolon guvenlik, sentiment deduplication, ATR fallback stop-loss |
