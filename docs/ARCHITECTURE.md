# System Architecture & Data Flow (Mimari ve Veri Akisi)

Bu belge, diger yazilimlarin ve LLM Temsilcilerinin sistemi kavrayabilmesi icin yuksek seviye mimariyi ve dosya dokumunu listeler.

> **Son Guncelleme:** 2026-04-04 (Faz 1, 2, 3 tamamlandi)

## Yuksek Seviye Mimari (High-Level Architecture)

Sistem 5 Katmanli (5-Tier) bir yapi uzerinden insa edilmistir:

1. **Extraction / Data Layer (`data/`):** Piyasadan sembollerin gecmis ve guncel OHLCV verileri, siparis defterleri (opsiyonel) ve haber basliklari, anlambilimsel verileri cekilir. Standardize edilir.
2. **Analysis / Logic Layer (`models/`):** Veriler Pandas-TA ile matematiksel indiktorlere cevirilirken es zamanli olarak Haberler LLM bazli `SentimentAnalyzer` uzerinden okunarak noralize edilir.
3. **Execution / Agentic Layer (`agents/`):** LangGraph altyapiyla State, node'lar (Analyst, Debate, Risk, Trader) arasinda dolasarak nihai JSON Trade emrini olusturur.
4. **Risk & Backtest Layer (`risk/`, `backtest/`):** Portfoy sermayesini korumak. CVaR limitleri ve Walk-Forward kronolojik validasyonlari bu asamada kodla korunur.
5. **Execution & UI Layer (`execution/`, `dashboard/`):** Karar alan islemler CCXT ile Binance (MOCK veya CANLI) sistemine gonderilirken tum veriler Dashboard'a aktarilir.

---

## Dizin Yapisi (Directory Structure)

```
LLMTrading/
|-- .env.example               # Ornek cevre degiskenleri
|-- requirements.txt           # Python kutuphaneleri
|-- config/
|   |-- settings.py            # Pydantic v2 tabanli Secret/Token konfigurasyonu
|   `-- trading_params.yaml    # SL/TP, max_positions, limit risk konfigurasyonlari
|                                [YENİ] Merkezi LLM model isimleri (llm.default_model)
|                                [YENİ] max_consecutive_losses, max_consecutive_llm_errors
|-- data/
|   |-- market_data.py         # CCXT/yfinance OHLCV cetici
|   |-- news_data.py           # HTTP tabanli haber entegrasyonu (httpx)
|   |-- sentiment_store.py     # Onceden islenen haber duyarliligi kayit (JSONL) veritabani
|   |                            [GUNCELLEME] Duplicate kontrolu (min_interval_minutes) eklendi
|   `-- symbol_resolver.py     # AAPL vs BTC/USDT otomatik borsa tespiti araci
|-- models/
|   |-- sentiment_analyzer.py  # LLM Destekli CoT Haber Analisti
|   |                            [GUNCELLEME] request_timeout ve max_retries eklendi
|   |                            [GUNCELLEME] _extract_json utils.json_utils'e tasindi
|   |-- technical_analyzer.py  # Pandas-TA gostergeleri analizcisi
|   |                            [GUNCELLEME] MACD/BBands kolon isimleri guvenli hale getirildi
|   `-- prompts/               # .txt halinde sistem promptlari
|-- agents/
|   |-- state.py               # StateGraph (TypedDict) hafizasi
|   |-- graph.py               # Node'larin birlestigi Compiler dosyasi
|   |                            [GUNCELLEME] Retry loop kaldirildi
|   |                            [YENİ] hold_decision dugumu: risk red -> direkt sonlanma
|   |-- coordinator.py
|   |-- research_analyst.py
|   |-- debate.py              # Bull vs Bear tartisma
|   |-- risk_manager.py
|   |                            [YENİ] Deterministik: Drawdown limiti kontrolu
|   |                            [YENİ] Deterministik: Gunluk kayip limiti kontrolu
|   |                            [YENİ] Deterministik: Pozisyon boyutu limiti (LLM sonrasi)
|   `-- trader.py              # Nihai Karar verici
|-- risk/
|   |-- portfolio.py           # P&L, Drawdown, Hisse senedi takibi
|   |                            [YENİ] JSON persistence: save_to_file / load_from_file
|   |                            [YENİ] Gunluk P&L otomatik sifirlama (reset_daily_pnl_if_needed)
|   |                            [YENİ] daily_pnl_date alani eklendi
|   |                            [DUZELTME] Short pozisyon equity ve close_position hesabi duzeltildi
|   |-- circuit_breaker.py     # [YENİ] Kill switch mekanizmasi
|   |                            Art arda kayip, gunluk limit, manuel STOP dosyasi
|   |-- cvar_optimizer.py      # CVaR (Conditional Value at Risk)
|   |-- regime_filter.py       # VIX endeks filtresi
|   `-- stop_loss.py           # ATR bazli dinamik/trailing stop loss
|-- backtest/
|   `-- walk_forward.py        # Walk-forward validasyon ve trade log analizozu
|-- execution/
|   |-- exchange_client.py     # CCXT ile Borsaya emir yollama sistemi
|   |                            [GUNCELLEME] Paper/Live mod ayrimi implemente edildi
|   |                            [YENİ] _get_paper_engine() lazy baslatic
|   |-- paper_engine.py        # [YENİ] Simule emir motoru (slippage, komisyon, P&L)
|   `-- order_manager.py       # Agent ciktisi olan JSON'u dogrulama ve parse etme
|                                [YENİ] Guvenli tip donusumleri (try/except)
|                                [YENİ] ATR bazli fallback stop-loss hesaplama
|                                [YENİ] current_price ve atr_value parametreleri
|-- utils/
|   |-- json_utils.py          # [YENİ] extract_json - tum ajanlar icin merkezi JSON ayristirici
|   `-- cost_tracker.py        # LLM API maliyet takipcisi
|-- scripts/
|   |-- run_live.py            # Tam sistemi kagit uzerinde veya gercek suren kod
|   |                            [YENİ] PortfolioState.load_from_file() ile basla
|   |                            [YENİ] PortfolioState.save_to_file() ile bitir
|   |                            [YENİ] CircuitBreaker baslangic kontrolu
|   |                            [YENİ] current_price ve atr_value parse_trade_decision'a geciliyor
|   `-- run_backtest.py        # Gecmis zaman testi
|                                [YENİ] --timeframe secenegi (1m, 5m, 15m, 1h, 4h, 1d, 1w)
|                                [YENİ] run_walkforward_backtest() implement edildi
|                                [KALDIRILDI] Short backtest pozisyonu (spot'ta desteklenmez)
`-- dashboard/
    |-- index.html             # Web arayuzu dosyasi
    |-- style.css              # Glassmorphism dizayni
    `-- app.js                 # [GUNCELLEME] Gercek API polling (/api/portfolio, /api/trades)
                                 [YENİ] updateTradesTable() fonksiyonu
                                 [YENİ] setInterval 5 saniyelik otomatik yenileme
```

---

## Sistem Veri Akisi

```
[run_live.py baslar]
        |
        v
PortfolioState.load_from_file()   <- JSON'dan devam et (persistence)
reset_daily_pnl_if_needed()       <- Gun degistiyse PNL sifirla
        |
        v
CircuitBreaker.should_halt()      <- Art arda kayip / gunluk limit / STOP dosyasi
        | (gecerse)
        v
RegimeFilter (VIX kontrolu)       <- Kriz rejiminde ticareti durdur
        |
        v
MarketDataClient -> TechnicalAnalyzer -> NewsClient
        |
        v
LangGraph Pipeline:
  coordinator -> research_analyst -> debate -> risk_manager
                                                   |
                                       +-----------+-----------+
                                    approved               rejected
                                       |                       |
                                     trader            hold_decision -> END
                                       |
                                       v
                              ExchangeClient.execute_order(order, current_price)
                                |  PAPER mod      |  LIVE mod
                                v                 v
                          PaperTradingEngine    CCXT/Binance
        |
        v
PortfolioState.save_to_file()     <- JSON'a kaydet
```

---

## Onemli Tasarim Kararlari

| Karar | Aciklama |
|-------|----------|
| **Retry loop kaldirildi** | Ayni veriyle tekrar analiz anlamsiz. Risk red -> `hold_decision` -> END |
| **Deterministic-first risk** | Drawdown, gunluk kayip, pozisyon limiti LLM'den bagimsiz kod olarak uygulanir |
| **JSON persistence** | Bot restart sonrasi pozisyonlar, PNL ve drawdown bilgisi korunur |
| **Paper Trading Engine** | `TradingMode.PAPER` ile gercek borsaya hic emir gitmez, slippage simule edilir |
| **Circuit Breaker** | `data/STOP` dosyasi olustururak manuel durdurma, art arda kayip ve LLM hata limiti |
| **Merkezi JSON ayristirici** | `utils/json_utils.py::extract_json` tum aganlarda kullanilir, tekrar yok |
