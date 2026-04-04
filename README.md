# LLM Autonomous Trading System

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)

## 📌 Project Overview
Bu proje, finansal piyasalarda (Kripto, BIST, ABD Hisse Senetleri) bağımsız (otonom) kararlar alabilen, **LangGraph tabanlı çoklu ajan (Multi-Agent) mimarisine** sahip bir yapay zeka alım-satım (trading) sistemidir.

Proje saf nicel (quantitative) veya saf duygusal (sentiment) analiz yerine, her iki disiplini birleştiren tam otonom bir işlem masası (trading desk) gibi çalışmaktadır. **Modellerin uydurma (halüsinasyon) riskini en aza indirmek** için *Bull vs Bear (Boğa vs Ayı) tartışma (debate)* filtresi ve bağımsız bir Risk Yöneticisi kullanır.

## 🗂️ Documentation (Dokümantasyon)

Geliştiricilerin ve AI ajanlarının sisteme hızlı entegrasyon sağlaması için aşağıdaki detaylı belgelere başvurun:

1. [Mimari Genel Bakış (ARCHITECTURE.md)](docs/ARCHITECTURE.md) - Sistem veri akışı, klasör yapısı ve modüler tasarım prensipleri.
2. [Ajan Sistemi (AGENTS.md)](docs/AGENTS.md) - Çoklu ajan (LangGraph) yapısındaki her bir ajanın giriş/çıkış (I/O) yapısı, görevleri ve kısıtları.
3. [Risk Yönetimi (RISK_MANAGEMENT.md)](docs/RISK_MANAGEMENT.md) - CVaR optimizasyonu, VIX rejim filtresi, Stop-Loss ve sermaye koruma politikaları.

## 🚀 Quick Start (Hızlı Başlangıç)

### 1. Kurulum (Installation)
```bash
# Bağımlılıkları yükleyin
pip install -r requirements.txt
```

### 2. Yapılandırma (Configuration)
Proje kök dizinindeki `.env.example` dosyasını `cp .env.example .env` şeklinde kopyalayarak kendi API anahtarlarınızı girin.
* Gerekli Anahtarlar: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `OPENROUTER_API_KEY`, `FINNHUB_API_KEY`

### 3. Kullanım (Usage)
```bash
# Canlı verilerle paper trading (Risk kontrolünden geçerse kararı ekrana basar)
python scripts/run_live.py --symbol BTC/USDT

# Gerçek veya testnet'te doğrudan borsa emri göndermek için
python scripts/run_live.py --symbol BTC/USDT --execute

# Farklı bir model (örn: Ollama) ile çalıştırma
python scripts/run_live.py --symbol AAPL --provider ollama

# Geriye Dönük Test (Backtest)
python scripts/run_backtest.py --symbol BTC/USDT --days 180
```

## 📊 Dashboard (İzleme Paneli)
Sistemin çalıştığı süreçte `dashboard/index.html` sayfasını herhangi bir modern tarayıcı ile açarak portföy durumunu, ajanların canlı tartışma (log) verilerini, VIX ve duyarlılık göstergelerini reel zamanlıya yakın bir şekilde izleyebilirsiniz.
