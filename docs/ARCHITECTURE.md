# System Architecture & Data Flow (Mimari ve Veri Akışı)

Bu belge, diğer yazılımların ve LLM Temsilcilerinin sistemi kavrayabilmesi için yüksek seviye mimariyi ve dosya dökümünü listeler.

## 🏗️ Yüksek Seviye Mimari (High-Level Architecture)

Sistem 5 Katmanlı (5-Tier) bir yapı üzerinden inşa edilmiştir:

1. **Extraction / Data Layer (`data/`):** Piyasadan sembollerin geçmiş ve güncel OHLCV verileri, sipariş defterleri (opsiyonel) ve haber başlıkları, anlambilimsel verileri çekilir. Standardize edilir.
2. **Analysis / Logic Layer (`models/`):** Veriler Pandas-TA ile matematiksel indikatörlere çevrilirken eş zamanlı olarak Haberler LLM bazlı `SentimentAnalyzer` üzerinden okunarak nötralize edilir.
3. **Execution / Agentic Layer (`agents/`):** LangGraph altyapısıyla State, node'lar (Analyst, Debate, Risk, Trader) arasında dolaşarak nihai JSON Trade emrini oluşturur.
4. **Risk & Backtest Layer (`risk/`, `backtest/`):** Portföy sermayesini korumak. CVaR limitleri ve Walk-Forward kronolojik validasyonları bu aşamada kodla korunur.
5. **Execution & UI Layer (`execution/`, `dashboard/`):** Karar alan işlemler CCXT ile Binance (MOCK veya CANLI) sistemine gönderilirken tüm veriler Dashboard'a aktarılır.

## 📂 Dizini (Directory Structure)

```text
LLMTrading/
├── .env.example               # Örnek çevre değişkenleri
├── requirements.txt           # Python kütüphaneleri
├── config/                    # Genel Yapılandırma Klasörü
│   ├── settings.py            # Pydantic v2 tabanlı Secret/Token konfigürasyonu
│   └── trading_params.yaml    # SL/TP, max_positions, limit risk konfigürasyonları
├── data/                      # Veri Boru Hattı Katmanı
│   ├── market_data.py         # CCXT/yfinance OHLCV çekici
│   ├── news_data.py           # Finnhub/CryptoPanic entegrasyonu
│   ├── sentiment_store.py     # Önceden işlenen haber duyarlılığı kayıt (JSONL) veritabanı
│   └── symbol_resolver.py     # AAPL vs BTC/USDT otomatik borsa tespiti aracı
├── models/                    # Düşünme Motorları
│   ├── sentiment_analyzer.py  # LLM Destekli CoT Haber Analisti
│   ├── technical_analyzer.py  # Pandas-TA göstergeleri analizcisi
│   └── prompts/               # .txt halinde sistem (System) promptları yönergeleri
├── agents/                    # LangGraph Node Yöneticileri
│   ├── __init__.py
│   ├── state.py               # StateGraph (TypedDict) hafızası
│   ├── graph.py               # Node'ların birleştiği Compiler dosyası
│   ├── coordinator.py
│   ├── research_analyst.py
│   ├── debate.py              # Bull vs Bear
│   ├── risk_manager.py
│   └── trader.py              # Nihai Karar verici
├── risk/                      # Deterministik Risk Koruyucuları
│   ├── portfolio.py           # P&L, Drawdown, Hisse senedi takibi
│   ├── cvar_optimizer.py      # CVaR (Conditional Value at Risk) 
│   ├── regime_filter.py       # VIX endeks filtresi (Kriz anında ticareti durdurur)
│   └── stop_loss.py           # ATR bazlı dinamik/trailing stop loss
├── backtest/                  # Geçmiş Test Araçları
│   └── walk_forward.py        # Walk-forward validasyon ve trade log analizörü
├── execution/                 # Ticaret Yürütmesi
│   ├── exchange_client.py     # CCXT ile Borsaya emir yollama sistemi
│   └── order_manager.py       # Agent çıktısı olan JSON'u Validate etme
├── scripts/                   # Kullanıcı çalıştırılabilir scriptleri
│   ├── run_live.py            # Tam sistemi kağıt üzerinde veya gerçek süren kod
│   └── run_backtest.py        # Geçmiş zaman testi
└── dashboard/                 # Monitör Arayüzü
    ├── index.html             # Web arayüzü dosyası
    ├── style.css              # Glassmorphism dizaynı
    └── app.js                 # Local file okuyucu/mock sistem arayüz tetikleyicisi
```
