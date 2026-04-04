# System Architecture & Data Flow (Mimari ve Veri Akisi)

Bu belge, diger yazilimlarin ve LLM Temsilcilerinin sistemi kavrayabilmesi icin yuksek seviye mimariyi ve dosya dokumunu listeler.

> **Son Guncelleme:** 2026-04-05 (Faz 1, 2, 3, 4, 5 tamamlandi)

## Yuksek Seviye Mimari (High-Level Architecture)

Sistem 6 Katmanli (6-Tier) bir yapi uzerinden insa edilmistir:

1. **Extraction / Data Layer (`data/`):** Piyasadan sembollerin gecmis ve guncel OHLCV verileri, siparis defterleri (opsiyonel) ve haber basliklari, anlambilimsel verileri cekilir. Standardize edilir.
2. **Analysis / Logic Layer (`models/`):** Veriler Pandas-TA ile matematiksel indiktorlere cevirilirken es zamanli olarak Haberler LLM bazli `SentimentAnalyzer` uzerinden okunarak noralize edilir.
3. **Execution / Agentic Layer (`agents/`):** LangGraph altyapiyla State, node'lar (Analyst, Debate, Risk, Trader) arasinda dolasarak nihai JSON Trade emrini olusturur.
4. **Portfolio Layer (`agents/portfolio_manager.py`):** [FAZ 4] Birden fazla varligi paralel analiz eder, bileşik skor ve CVaR ile portföy dagilimi yapar.
5. **Risk & Backtest Layer (`risk/`, `backtest/`):** Portfoy sermayesini korumak. CVaR limitleri ve Walk-Forward kronolojik validasyonlari bu asamada kodla korunur.
   - **[FAZ 5] Watchdog (`risk/watchdog.py`):** Ayri thread'de flash crash korumasi, 30 saniyede bir fiyat kontrolu
6. **Execution & UI Layer (`execution/`, `dashboard/`):** Karar alan islemler CCXT ile Binance (MOCK veya CANLI) sistemine gonderilirken tum veriler Dashboard'a aktarilir.
7. **[FAZ 5] Cost Optimization Layer:** Prompt sikistirma (~%40-50), sentiment cache, max_tokens sinirlari, JSON mode ile API maliyetlerinde ~%72-88 azalma.

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
|   |                            [FAZ 4] `_create_llm` → `create_llm` (public)
|   |                            [FAZ 5] Cache kontrolu LLM oncesi yapiliyor
|   |                            [FAZ 5] SentimentRecord'a price alani eklendi
|   |                            [FAZ 5] Prompt sikistirildi (~%40 kuculme)
|   |                            [FAZ 5] max_tokens=300, JSON mode aktif
|   |-- technical_analyzer.py  # Pandas-TA gostergeleri analizcisi
|   |                            [GUNCELLEME] MACD/BBands kolon isimleri guvenli hale getirildi
|   |-- llm_fallback.py        # Provider fallback zinciri
|   |                            [FAZ 4] `_create_llm` → `create_llm` import güncellendi
|   |                            [FAZ 5] max_tokens parametresi desteklendi
|   |                            [FAZ 5] response_format={"type": "json_object"} eklendi
|   `-- prompts/               # .txt halinde sistem promptlari
|       |-- sentiment_system.txt    # [FAZ 5] Sikistirildi, max_tokens=300
|       |-- research_analyst.txt    # [FAZ 5] Sikistirildi, max_tokens=500
|       |-- risk_manager.txt        # [FAZ 5] Sikistirildi, max_tokens=400
|       |-- trader.txt              # [FAZ 5] Sikistirildi, max_tokens=250
|       `-- portfolio_manager.txt   # [FAZ 5] Sikistirildi
|-- agents/
|   |-- state.py               # StateGraph (TypedDict) hafizasi
|   |                            [FAZ 4] `provider` alani eklendi
|   |-- graph.py               # Node'larin birlestigi Compiler dosyasi
|   |                            [GUNCELLEME] Retry loop kaldirildi
|   |                            [YENİ] hold_decision dugumu: risk red -> direkt sonlanma
|   |                            [FAZ 4] Phase isimleri standartlastirildi ("complete")
|   |                            [FAZ 4] `run_analysis()` provider parametresi aliyor
|   |-- coordinator.py
|   |-- research_analyst.py    # [FAZ 4] provider state'ten okunuyor
|   |-- debate.py              # Bull vs Bear tartisma
|   |                            [FAZ 4] provider state'ten okunuyor
|   |-- risk_manager.py        # [FAZ 4] research_report prompt'a eklendi
|   |                            [FAZ 4] provider state'ten okunuyor
|   |                            [YENİ] Deterministik: Drawdown limiti kontrolu
|   |                            [YENİ] Deterministik: Gunluk kayip limiti kontrolu
|   |                            [YENİ] Deterministik: Pozisyon boyutu limiti (LLM sonrasi)
|   |-- trader.py              # Nihai Karar verici
|   |                            [FAZ 4] provider state'ten okunuyor
|   `-- portfolio_manager.py   # [FAZ 4] Multi-asset portföy yöneticisi
|                                Paralel analiz (ThreadPoolExecutor)
|                                Bileşik skorlama (debate+sentiment+trend+RSI)
|                                CVaR optimizasyonu entegrasyonu
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
|   |-- stop_loss.py           # ATR bazli dinamik/trailing stop loss
|   `-- watchdog.py            # [FAZ 5] Flash crash korumasi (ayri thread)
|                                30 saniyede bir fiyat kontrolu
|                                1dk > %3 dusus -> acil satis
|                                5dk > %5 dusus -> acil satis
|                                5dk %2-5 dusus -> uyari
|-- backtest/
|   `-- walk_forward.py        # Walk-forward validasyon ve trade log analizozu
|-- execution/
|   |-- exchange_client.py     # CCXT ile Borsaya emir yollama sistemi
|   |                            [GUNCELLEME] Paper/Live mod ayrimi implemente edildi
|   |                            [YENİ] _get_paper_engine() lazy baslatic
|   |                            [FAZ 4] get_paper_status() public method eklendi
|   |-- paper_engine.py        # [YENİ] Simule emir motoru (slippage, komisyon, P&L)
|   `-- order_manager.py       # Agent ciktisi olan JSON'u dogrulama ve parse etme
|                                [YENİ] Guvenli tip donusumleri (try/except)
|                                [YENİ] ATR bazli fallback stop-loss hesaplama
|                                [YENİ] current_price ve atr_value parametreleri
|-- utils/
|   |-- json_utils.py          # [YENİ] extract_json - tum ajanlar icin merkezi JSON ayristirici
|   `-- cost_tracker.py        # LLM API maliyet takipcisi
|-- config/
|   `-- trading_params.yaml    # [FAZ 5] watchdog bolumu eklendi
|                                [FAZ 5] limits bolumu eklendi (max_tokens degerleri)
|                                [FAZ 5] sentiment_cache_minutes parametresi
|-- scripts/
|   |-- run_live.py            # Tam sistemi kagit uzerinde veya gercek suren kod
|   |                            [FAZ 5] Daemon mode: surekli dongu
|   |                            [FAZ 5] CLI: --symbols, --interval, --watchdog, --max-cycles, --dry-run
|   |                            [FAZ 5] SIGINT/SIGTERM handler ile guvenli kapanis
|   |                            [YENİ] PortfolioState.load_from_file() ile basla
|   |                            [YENİ] PortfolioState.save_to_file() ile bitir
|   |                            [YENİ] CircuitBreaker baslangic kontrolu
|   |                            [FAZ 4] TradingMode import duzeltildi
|   |                            [FAZ 4] provider parametresi run_analysis'a geciliyor
|   |-- run_backtest.py        # Gecmis zaman testi
|   |                            [YENİ] --timeframe secenegi (1m, 5m, 15m, 1h, 4h, 1d, 1w)
|   |                            [YENİ] run_walkforward_backtest() implement edildi
|   |                            [KALDIRILDI] Short backtest pozisyonu (spot'ta desteklenmez)
|   |                            [FAZ 4] calculate_metrics period parametresi aliyor
|   `-- run_portfolio.py       # [FAZ 4] Portföy yöneticisi CLI
|                                Multi-asset paralel analiz
|                                --workers, --max-positions, --min-score
`-- dashboard/
    |-- index.html             # Web arayuzu dosyasi
    |                            [FAZ 4] Portföy dağılımı kartı eklendi
    |-- style.css              # Glassmorphism dizayni
    |                            [FAZ 4] Allocation stilleri eklendi
    |-- app.js                 # [GUNCELLEME] Gercek API polling (/api/portfolio, /api/trades)
    |                            [YENİ] updateTradesTable() fonksiyonu
    |                            [YENİ] setInterval 5 saniyelik otomatik yenileme
    |                            [FAZ 4] updatePortfolioAllocation() fonksiyonu
    |                            [FAZ 4] /api/portfolio_allocation polling
    `-- server.py              # FastAPI backend
                                 [FAZ 4] /api/portfolio_allocation endpoint
                                 [FAZ 4] Güvenlik middleware (.py, .env, .yaml engelleme)
```

---

## Sistem Veri Akisi

### Tek Sembol Analizi (run_live.py)

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
[FAZ 5] Watchdog Thread Baslat    <- Arka planda fiyat izleme (30sn interval)
        |
        v
RegimeFilter (VIX kontrolu)       <- Kriz rejiminde ticareti durdur
        |
        v
MarketDataClient -> TechnicalAnalyzer -> NewsClient
        |
        v
[FAZ 5] Sentiment Cache Kontrolu  <- Son analiz < cache_minutes ise cache'den don
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
        |
        v
[FAZ 5] Dongu -> bir sonraki interval (Ctrl+C ile guvenli kapanis)
```

### Portföy Analizi (run_portfolio.py) [FAZ 4]

```
[run_portfolio.py baslar]
        |
        v
Sembol Havuzu: [BTC/USDT, ETH/USDT, SOL/USDT, ...]
        |
        v
ThreadPoolExecutor (parallel, --workers N)
        |
        +--> BTC/USDT:  fetch_data -> run_analysis() -> SymbolAnalysis
        +--> ETH/USDT:  fetch_data -> run_analysis() -> SymbolAnalysis
        +--> SOL/USDT:  fetch_data -> run_analysis() -> SymbolAnalysis
        |
        v
Bileşik Skorlama (her sembol icin):
  composite = debate*0.35 + sentiment*0.25 + trend*0.20 + rsi*0.20
  composite *= confidence_factor
        |
        v
Min skor eşiği filtreleme
        |
        v
CVaR Optimizasyonu (getiri matrisi -> optimal agirliklar)
  |  (tek varlik veya optimizasyon basarisiz -> skor bazli dagilim)
        v
Portföy Dağılımı JSON -> dashboard + file export
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
| **Merkezi JSON ayristirici** | `utils/json_utils.py::extract_json` tum ajanlarda kullanilir, tekrar yok |
| **Paralel analiz** | Portfolio Manager `ThreadPoolExecutor` ile sembolleri ayni anda analiz eder |
| **LLM factory public** | `models/sentiment_analyzer.py::create_llm` tum modüller tarafindan kullanilir |
| **Dashboard güvenlik** | `.py`, `.env`, `.yaml` dosyalarina erisim middleware ile engellenir |
| **Daemon mode** | `run_live.py` dongu icinde calisir, SIGINT/SIGTERM ile guvenli kapanis |
| **Watchdog thread** | Arka planda fiyat izler, flash crash durumunda acil satis yapar |
| **Sentiment cache** | Son analiz cache_minutes icinde ise LLM cagirmadan cache'den doner |
| **Prompt sikistirma** | Tum promptlar ~%40-50 kucultuldu, "be concise" ve "ONLY return JSON" kurallari eklendi |
| **JSON mode + max_tokens** | Tum LLM cagrilar `response_format=json_object` ve cikti token siniri ile yapilir |

---

## Daemon Mode Mimarisi [FAZ 5]

`run_live.py` artik tek seferlik degil, surekli calisan bir dongu olarak tasarlanmistir.

### Dongu Akisi

```
[basla]
   |
   v
[--max-cycles] kontrolu
   |  (ulasildiysa -> cik)
   v
CircuitBreaker.should_halt()
   |  (halt -> cik)
   v
Pipeline calistir (sembol analizi)
   |
   v
Interval kadar bekle (--interval: 5m, 15m, 30m, 1h, 4h, 1d)
   |
   v
Dongu basa don
```

### Guvenli Kapanis

SIGINT (Ctrl+C) ve SIGTERM sinyalleri yakalanir:
1. Dongu bayragi `running = False` olarak isaretlenir
2. Watchdog thread durdurulur
3. PortfolioState.save_to_file() ile tum pozisyonlar kaydedilir
4. Temiz cikis

### Geriye Uyumluluk

- `--symbol` parametresi hala calisir
- `--max-cycles 1` ile tek seferlik calistirma mumkundur
- Varsayilan: `--max-cycles` sinirsiz (daemon mode)

---

## Watchdog Mimarisi [FAZ 5]

**Dosya:** `risk/watchdog.py`

Watchdog, ana pipeline'dan bagimsiz bir arka plan thread'i olarak calisir.

### Thread Yonetimi

```
[Ana Thread: run_live.py]          [Watchdog Thread]
        |                                  |
        v                                  v
Pipeline dongusu                    Fiyat izleme dongusu
        |                           (check_interval_seconds)
        |                                  |
        v                                  v
Pozisyon ac/kapat                   Flash crash kontrolu
        |                                  |
        v                                  v
Ctrl+C -> temiz kapanis             1dk > %3 -> acil satis
                                    5dk > %5 -> acil satis
                                    5dk %2-5 -> uyari
```

### Acil Satis Mantigi

Watchdog her `check_interval_seconds` (varsayilan 30) saniyede bir:
1. Tum izlenen sembollerin guncel fiyatlarini ceker
2. 1 dakikalik ve 5 dakikalik dusus yuzdelerini hesaplar
3. Esik asildiysa acil satis emri gonderir (pozisyon varsa)

### Yapilandirma

```yaml
watchdog:
  enabled: true
  check_interval_seconds: 30
  flash_crash_1min_pct: 0.03
  flash_crash_5min_pct: 0.05
  alert_5min_pct: 0.02
```

---

## Sentiment Cache Akisi [FAZ 5]

`SentimentAnalyzer.analyze()` metodunda cache mekanizmasi LLM cagrisindan ONCE calisir.

### Cache Akisi

```
[SentimentAnalyzer.analyze()]
        |
        v
Cache kontrolu:
  last_analysis varsa VE
  (simdiki_zaman - last_analysis.zaman) < cache_minutes
        |
   +----+----+
   |         |
  EVET      HAYIR
   |         |
   v         v
Cache'den   LLM cagrisi yap
sonuc don   (prompt sikistirilmis,
             max_tokens=300,
             JSON mode)
   |         |
   v         v
[SentimentRecord]  <- price alani ile kaydet
                     (market change detection icin)
```

### Cache Avantajlari

- Varsayilan `sentiment_cache_minutes`: 30 dakika
- Ayni sembol icin 30 dakika icinde tekrar analiz yapilmaz
- ~%30-50 daha az LLM cagrisi
- `SentimentRecord.price` alani ile piyasa degisim tespiti mumkun

---

## Maliyet Optimizasyonu [FAZ 5]

### Prompt Sikistirma

Tum 5 prompt dosyasi ~%40-50 oraninda kucultulmustur:
- Gereksiz aciklamalar kaldirildi
- "be concise" kurali eklendi
- "ONLY return JSON" kurali eklendi
- Ornek ciktilar korundu, aciklamalar kisaltildi

### max_tokens Sinirlari

| Ajan | max_tokens |
|------|-----------|
| Sentiment | 300 |
| Research | 500 |
| Debate | 400 |
| Moderator | 400 |
| Risk | 400 |
| Trader | 250 |

### JSON Mode

Tum LLM cagrilar `response_format={"type": "json_object"}` kullanir:
- Cikti format garantisi
- Parse hatasi azalmasi
- Daha tutarli ajan davranisi

### Toplam Tasarruf

| Bilesen | Etki |
|---------|------|
| Prompt sikistirma | %30-40 input token azalma |
| Prompt caching (OpenRouter/DeepSeek) | %75-90 cached input indirimi |
| Sentiment cache | %30-50 daha az LLM cagrisi |
| max_tokens sinirlari | Runaway cikti onleme |
| **TOPLAM** | **~%72-88 API maliyet azalmasi** |
