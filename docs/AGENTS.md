# Agent Architecture (Ajan Mimarisi)

Bu proje **LangGraph** kullanilarak gelistirilmis bir Durum Grafigi (StateGraph) mekanizmasina dayanir. Ajanlar sirasyla calisir. Her bir ajan, bir onceki ajanin urettigi durum nesnesini okuyup gunceller.

Durum nesnesi (State), `agents/state.py` icinde tanimlanan `TradingState` adli bir `TypedDict` sinifidir.

> **Son Guncelleme:** 2026-04-05 (Faz 1, 2, 3, 4, 5, 6 tamamlandi)

---

## Graf Akisi

```
coordinator
    |
    v
research_analyst  (SentimentAnalyzer + LLM raporu)
    |
    v
debate            (Bull vs Bear + Moderator)
    |
    v
risk_manager      (Deterministik kontroller + LLM degerlendirmesi)
    |
    +-- risk_approved=True  --> trader --> [ExchangeClient] --> END
    |
    `-- risk_approved=False --> hold_decision --> END
```

**Faz 1 oncesi:** Risk red -> Coordinator'a donup tekrar analiz (ayni veriyle, anlamsiz)
**Faz 1 sonrasi:** Risk red -> `hold_decision` dugumu -> direkt END (loop yok, maliyet yok)

---

## 1. Coordinator Node (Koordinator)

**Dosya:** `agents/coordinator.py`

**Gorevi:** Sistemin ana orkestra sefi. Ilk asamada toparlanmis olan piyasa verileri, haber verileri ve teknik indikasyonlarin butunlugunu kontrol eder.

- **Input:** Islem yapilacak sembol ve toplanmis raw data
- **Output:** Surec baslangic onay/ret, iterasyon sayaci
- **Not:** Veriler eksikse loglar ve bir sonraki adıma geçer, sistemi bloklamaz

---

## 2. Research Analyst (Arastirmaci Ajan)

**Dosya:** `agents/research_analyst.py`

**Gorevi:** Teknik verileri ve son 24 saatin haber ozetlerini isleyerek duyarlilik (sentiment) analizi yapmak.

**Mimari Notu:** Bu ajan icerisinde ekstra bir `SentimentAnalyzer` modulu calisir (Chain-of-Thought - CoT kullanilarak). Puanlari ve teknik verileri LLM uzerinden gecirerek varlik hakkinda "genel tavsiye", "risk" ve "trend gucu" iceren kapsamli bir arastirma raporu derler.

**Cikti (Payload):** `research_report` dict, `sentiment` dict

**Faz 3 guncellemes:** `extract_json` artik `utils.json_utils`'ten import ediliyor (merkezi ayristirici)

**Faz 4 guncellemesi:** `provider` parametresi state'ten okunuyor, paralel analiz destekleniyor

**Faz 5 guncellemesi:** Prompt sikistirildi (~%40 kuculme), max_tokens=300, JSON mode aktif, cache kontrolu LLM oncesi yapiliyor

**Faz 6 guncellemesi:** RAG hafiza sorgusu eklendi — `query_similar_conditions()` ile geçmiş benzer durumlar LLM prompt'una dahil ediliyor. LLM retry/backoff (`invoke_with_retry`, max_retries=3).

---

## 3. Bull vs Bear Debate (Tartisma / Halusinasyon Filtresi)

**Dosya:** `agents/debate.py`

**Gorevi:** Modelin koru koruya haberlerin etkisinde kalarak halusnasyon gormesini (hallucination/confirmation bias) engellemek.

**Tur 1 - Ilk Argumanlar:**
- **Bull Agent:** Varligin kesinlikle yukselt ecegini kanitlamaya calisan karsit gorus argumani hazirlar (sistem istemi ona zorla bullish olmasini soyler)
- **Bear Agent:** Varligin kesinlikle dusecegini veya tehlikeli oldugunu kanitlamaya calisan karsit arguman

**Tur 2 - Karsiliklarli Yanit (max_rounds >= 2 ise):**
- Bull, Bear'in argumanlarina yanit verir ve yukselis tezini pekistirir
- Bear, Bull'un argumanlarina yanit verir ve dusus risklerini pekistirir

**Moderator:** Iki argumani degerlendirir, hangi argumanlarin veri (teknik/temel) ile ortustugunu ve hangilerinin uydurma (halusnasyon) oldugunu tespit edip bir *Konsensus Skoru (Consensus Score) cikarir.

**Cikti (Payload):** `debate_result` (Kim kazandi, guven skoru, halusnasyon listesi)

---

## 4. Risk Manager (Risk Yoneticisi)

**Dosya:** `agents/risk_manager.py`

**Gorevi:** Tum raporlari inceler. Algoritmik/Deterministik kurallar ile Bilissel/LLM kurallarini carpistir.

### Deterministik Kontroller (Kod - LLM'den bagimsiz)

| # | Kontrol | Aciklamasi |
|---|---------|------------|
| 1 | **Guven skoru** | Sentiment confidence < min_confidence ise red |
| 2 | **Halusnasyon sayisi** | debate.hallucinations_detected > 2 ise red |
| 3 | **Sentiment-teknik uyum** | Sentiment bullish, teknik sell ise uyari |
| 4 | **Acik pozisyon limiti** | open_positions >= max_open_positions ise red |
| 5 | **Drawdown limiti** | current_drawdown >= max_drawdown_pct ise red [FAZ 1] |
| 6 | **Gunluk kayip limiti** | daily_loss/equity >= max_daily_loss_pct ise red [FAZ 1] |
| 7 | **Pozisyon boyutu** | LLM'in onerdigi boyut equity * max_position_pct'i asiyorsa red [FAZ 1] |
| 8 | **LLM Drift Kontrolu** | Ajan isabet orani < %40 ise red, < %60 ise uyari [FAZ 6] |

> Kontrol 5, 6, 7 Faz 1'de eklendi. LLM prompt'unda var olan bu kurallar artik kodla da zorlanir.
> Kontrol 7, LLM cagrisindan *sonra* calisir (once LLM, sonra dogrula).

### LLM Degerlendirmesi

System prompt'u `prompts/risk_manager.txt`'ten okunur. Deterministik kontrol sonuclari, arastirma raporu ve LLM'e bildirilir, LLM derinlemesine bir risk analizi yapip stop-loss/take-profit/pozisyon boyutu onerir.

**Faz 4 guncellemesi:** `research_report` artik LLM prompt'una dahil ediliyor — risk manager arastirma raporunu da degerlendiriyor.

### Yonlendirme

- `checks_failed` listesi doluysa -> `final_decision = "rejected"` (LLM ne derse desin)
- Bos ise -> LLM'in `decision` alani esas alinir
- `risk_approved=True` -> `trader`
- `risk_approved=False` -> `hold_decision` -> END

**Cikti (Payload):** `risk_assessment`, `risk_approved`

**Faz 5 guncellemesi:** Prompt sikistirildi (~%40 kuculme), max_tokens=400, JSON mode aktif

**Faz 6 guncellemesi:** DriftMonitor entegrasyonu — LLM isabet oranı kontrolü eklendi. LLM retry/backoff (max_retries=3).

**Faz 6 guncellemesi:** LLM retry/backoff (5 cagriya uygulandi, max_retries=2).

---

## 5. Trader (Islemci / Yurutucuajan)

**Dosya:** `agents/trader.py`

**Gorevi:** Risk Yoneticisi ve diger tum birimlerin kararlarini standart, borsalarin (CEX) anlayacagi formatta bir JSON aksiyon emrine (Action Order) cevirmek.

**Cikti Formati:**
```json
{
    "action": "buy|sell|hold",
    "symbol": "BTC/USDT",
    "order_type": "market",
    "amount": 0.035,
    "entry_price": 84000,
    "stop_loss": 82000,
    "take_profit": 88000,
    "confidence": 0.75,
    "reasoning": "Teknik ve sentiment uyumlu, RSI 45, trend bullish",
    "time_horizon": "swing"
}
```

Bu cikti LangGraph dongusu disina cikarak `execution/order_manager.py` modulu uzerinden `ExchangeClient.execute_order()`'a beslenir.

**Faz 5 guncellemesi:** Prompt sikistirildi (~%40 kuculme), max_tokens=250, JSON mode aktif

**Faz 6 guncellemesi:** LLM retry/backoff (`invoke_with_retry`, max_retries=3).

---

## 6. hold_decision Node [FAZ 1 - YENİ]

**Dosya:** `agents/graph.py` - `_hold_decision_node()`

**Gorevi:** Risk manager reddettiginde retry loop'a girmek yerine temiz bir HOLD karari olusturup grafigi sonlandirmak.

**Neden:** Ayni piyasa verisiyle tekrar analiz yapmanin anlami yok; veri degismez, karar degismez, sadece LLM maliyeti olusur.

**Cikti:**
```python
{
    "action": "hold",
    "symbol": "BTC/USDT",
    "reason": "Risk yonetimi tarafindan reddedildi",
    "risk_checks_failed": ["Drawdown limiti asildi: 12.00% >= 10.00%"],
    "risk_warnings": []
}
```

---

## 7. Portfolio Manager (Portföy Yöneticisi) [FAZ 4 - YENİ]

**Dosya:** `agents/portfolio_manager.py`

**Gorevi:** Birden fazla varligi paralel olarak analiz eder, her biri icin bileşik skor hesaplar ve CVaR optimizasyonu ile optimal portföy dagilimini belirler.

**Akış:**
```
Sembol Havuzu
    |
    v
[Paralel Analiz — ThreadPoolExecutor]
    |
    +-- BTC/USDT  → run_analysis() → SymbolAnalysis
    +-- ETH/USDT  → run_analysis() → SymbolAnalysis
    +-- SOL/USDT  → run_analysis() → SymbolAnalysis
    |
    v
[Bileşik Skorlama]
    |  Debate Consensus:  %35
    |  Sentiment Score:   %25
    |  Trend Strength:    %20
    |  RSI (ters):        %20
    |  Confidence Factor: çarpan
    v
[CVaR Optimizasyonu] → Optimal Agirliklar
    |
    v
Portföy Dagilimi (JSON)
```

**Bileşik Skor Formülü:**
```
composite_score = (
    debate_consensus * 0.35 +
    sentiment_score * 0.25 +
    trend_strength * 0.20 +
    rsi_normalized * 0.20
) * confidence_factor
```

- `rsi_normalized`: RSI < 30 → +0.5 (firsat), RSI > 70 → -0.5 (risk), arasi → (RSI-50)/40
- `confidence_factor`: (sentiment_confidence + 0.5) / 1.5 — düşük güven skoru düsürür

**Kullanim:**
```bash
# 3 coin icin portföy analizi (paralel, 2 worker)
python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --workers 2

# Max 3 pozisyon, min skor 0.2
python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT,SOL/USDT,AVAX/USDT --max-positions 3 --min-score 0.2
```

**Cikti (Payload):**
```json
{
    "status": "success",
    "allocations": {"BTC/USDT": 0.50, "ETH/USDT": 0.50},
    "asset_details": {
        "BTC/USDT": {
            "allocation_pct": 50.0,
            "composite_score": 0.187,
            "sentiment_score": -0.30,
            "debate_consensus": 0.40,
            "trend": "bullish",
            "rsi": 63.6
        }
    },
    "cvar_info": {"cvar": -0.0156, "var": -0.0098, "expected_return": -0.037}
}
```

---

## 8. RAG Hafiza Sistemi (AgentMemoryStore) [FAZ 6 - YENİ]

**Dosya:** `data/vector_store.py`

**Gorevi:** ChromaDB tabanlı vektör veritabanı ile ajanın verdiği kararları ve o anki piyasa durumunu saklar. Gelecekte benzer piyasa koşulları oluştuğunda geçmiş deneyimleri sorgulayarak LLM'e bağlam sağlar.

**Akış:**
```
[Pipeline Tamamlandı]
        |
        v
AgentMemoryStore.store_decision()
  - Piyasa durumu (fiyat, VIX, MACD, haberler) → embedding
  - Metadata: {symbol, action, accuracy, timestamp}
  - ChromaDB'ye kaydet
        |
        v
[Sonraki Analizde]
        |
        v
AgentMemoryStore.query_similar_conditions()
  - Mevcut piyasa durumu → embedding
  - En benzer 3 geçmiş durum sorgulanır
  - Geçmiş aksiyonlar ve başarı oranları döndürülür
        |
        v
Research Analyst prompt'una dahil edilir
```

**Kullanim:**
```python
from data.vector_store import AgentMemoryStore

# Karar kaydet
memory = AgentMemoryStore()
memory.store_decision(state, accuracy_score=0.75)

# Benzer durumları sorgula
history = memory.query_similar_conditions(state, n_results=3)
# → [{"past_action": "buy", "past_accuracy": 0.75, "market_context": "..."}]
```

**Not:** `chromadb` `requirements.txt`'de bulunmalıdır. ChromaDB başlatılamazsa graceful fallback (işlem sessizce atlanır).

---

## 9. Concept Drift Monitor (DriftMonitor) [FAZ 6 - YENİ]

**Dosya:** `evaluation/drift_monitor.py`

**Gorevi:** LLM'in sentiment tahminlerinin zaman içinde bozulup bozulmadığını (concept drift) tespit eder. Sentiment skorunun yönü ile fiyatın yönünü karşılaştırarak ajan isabet oranını hesaplar.

**Hesaplama Mantığı:**
```
Son 5 sentiment kaydı alınır
Her kayıt için:
  - sentiment_score > 0 → bullish bekleniyor
  - sentiment_score < 0 → bearish bekleniyor
  - Fiyat değişimi yönü ile karşılaştır
  - Yönler eşleşirse → doğru tahmin

accuracy = doğru / toplam
```

**Risk Manager Entegrasyonu:**
| Accuracy | Aksiyon |
|----------|---------|
| >= %60 | Normal — check passed |
| %40 - %60 | Uyarı — "LLM isabet oranı düşüyor" |
| < %40 | RED — "LLM İsabet Oranı Çok Düşük (Drift)" |

**Accuracy Cache:**
- `data/agent_accuracy.json` dosyasında sembol bazlı saklanır
- `get_agent_accuracy(symbol)` ile okunur
- Varsayılan: 1.0 (güvenli kabul — veri yoksa)

---

## Ajan Spesifikasyonlari [FAZ 6 GUNCELLEME]

### max_tokens ve JSON Mode

Tum LLM cagrilar artik `max_tokens` siniri ve `response_format={"type": "json_object"}` ile yapilir.

| Ajan | max_tokens | JSON Mode | Aciklama |
|------|-----------|-----------|----------|
| Sentiment | 300 | Evet | Haber duyarlilik analizi |
| Research | 500 | Evet | Kapsamli arastirma raporu |
| Debate (Bull/Bear) | 400 | Evet | Karsit argumanlar |
| Moderator | 400 | Evet | Konsensus degerlendirmesi |
| Risk Manager | 400 | Evet | Risk analizi ve oneriler |
| Trader | 250 | Evet | Nihai islem emri |

### Prompt Sikistirma

Tum prompt dosyalari ~%40-50 oraninda kucultulmustur:
- Gereksiz aciklamalar kaldirildi
- "be concise" kurali eklendi
- "ONLY return JSON" kurali eklendi
- Ornek ciktilar korundu, aciklamalar kisaltildi

### Yapilandirma (`config/trading_params.yaml`)

```yaml
limits:
  sentiment_max_tokens: 300
  research_max_tokens: 500
  debate_max_tokens: 400
  moderator_max_tokens: 400
  risk_max_tokens: 400
  trader_max_tokens: 250
  sentiment_cache_minutes: 30
```

---

## State Nesnesi (TradingState)

`agents/state.py` icerisindeki `TradingState` TypedDict alanlari:

| Alan | Tip | Aciklama |
|------|-----|----------|
| `symbol` | str | Islem sembolu (ornek: BTC/USDT) |
| `market_data` | dict | OHLCV ozet, fiyat degisimi |
| `news_data` | list | Son 20 haber (baslik, ozet, kaynak) |
| `technical_signals` | dict | RSI, MACD, BB, EMA, ATR |
| `portfolio_state` | dict | Equity, acik pozisyonlar, PNL, drawdown |
| `sentiment` | dict | Skor, sinyal, guven, risk, faktorler |
| `research_report` | dict | Tavsiye, trend, risk seviyesi |
| `debate_result` | dict | Konsensus skoru, kazanan taraf, halusnasyonlar |
| `risk_assessment` | dict | Karar, aciklama, kontrol listesi |
| `risk_approved` | bool | True ise trader'a git |
| `trade_decision` | dict | Nihai islem emri |
| `messages` | list | Tum ajan mesaj gecmisi |
| `phase` | str | Mevcut asama (init/research/debate/risk/trade/complete) |
| `iteration` | int | Iterasyon sayaci (artik sadece referans) |
| `provider` | str | LLM saglayici override (openrouter, deepseek, ollama) |
| `historical_context` | list | [FAZ 6] RAG sorgusu sonucu — geçmiş benzer durumlar |
| `agent_accuracy` | float | [FAZ 6] DriftMonitor isabet oranı (varsayılan: 1.0) |

---

## LLM Retry/Backoff [FAZ 6]

Tüm ajan LLM çağrıları artık `utils/llm_retry.py::invoke_with_retry()` ile korunmaktadır.

### Retry Parametreleri

| Ajan | max_retries | base_delay | Açıklama |
|------|-------------|------------|----------|
| Sentiment | LLM kendi retry | - | `ChatOpenAI(max_retries=2)` |
| Research | 3 | 2.0s | Exponential: 2s → 4s → 8s |
| Debate (Bull/Bear/Mod) | 2 | 2.0s | Exponential: 2s → 4s |
| Risk Manager | 3 | 2.0s | Exponential: 2s → 4s → 8s |
| Trader | 3 | 2.0s | Exponential: 2s → 4s → 8s |

### Davranış

1. LLM çağrısı başarısız olursa → `base_delay * 2^attempt` saniye bekle
2. Maksimum deneme sayısına ulaşılırsa → exception yukarı fırlatılır
3. Ajan try/except bloğu ile fallback değer döner
