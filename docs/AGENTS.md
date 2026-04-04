# Agent Architecture (Ajan Mimarisi)

Bu proje **LangGraph** kullanilarak gelistirilmis bir Durum Grafigi (StateGraph) mekanizmasina dayanir. Ajanlar sirasyla calisir. Her bir ajan, bir onceki ajanin urettigi durum nesnesini okuyup gunceller.

Durum nesnesi (State), `agents/state.py` icinde tanimlanan `TradingState` adli bir `TypedDict` sinifidir.

> **Son Guncelleme:** 2026-04-04 (Faz 1, 2, 3 tamamlandi)

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
- **Not:** Veriler eksik veya limitin altindaysa sistemi bir sonraki adima aktarir ya da hatayla sonlandirir

---

## 2. Research Analyst (Arastirmaci Ajan)

**Dosya:** `agents/research_analyst.py`

**Gorevi:** Teknik verileri ve son 24 saatin haber ozetlerini isleyerek duyarlilik (sentiment) analizi yapmak.

**Mimari Notu:** Bu ajan icerisinde ekstra bir `SentimentAnalyzer` modulu calisir (Chain-of-Thought - CoT kullanilarak). Puanlari ve teknik verileri LLM uzerinden gecirerek varlik hakkinda "genel tavsiye", "risk" ve "trend gucu" iceren kapsamli bir arastirma raporu derler.

**Cikti (Payload):** `research_report` dict, `sentiment` dict

**Faz 3 guncellemes:** `extract_json` artik `utils.json_utils`'ten import ediliyor (merkezi ayristirici)

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

> Kontrol 5, 6, 7 Faz 1'de eklendi. LLM prompt'unda var olan bu kurallar artik kodla da zorlanir.
> Kontrol 7, LLM cagrisindan *sonra* calisir (once LLM, sonra dogrula).

### LLM Degerlendirmesi

System prompt'u `prompts/risk_manager.txt`'ten okunur. Deterministik kontrol sonuclari LLM'e bildirilir, LLM derinlemesine bir risk analizi yapip stop-loss/take-profit/pozisyon boyutu onerir.

### Yonlendirme

- `checks_failed` listesi doluysa -> `final_decision = "rejected"` (LLM ne derse desin)
- Bos ise -> LLM'in `decision` alani esas alinir
- `risk_approved=True` -> `trader`
- `risk_approved=False` -> `hold_decision` -> END

**Cikti (Payload):** `risk_assessment`, `risk_approved`

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
| `phase` | str | Mevcut asama (analysis/trade/completed) |
| `iteration` | int | Iterasyon sayaci (artik sadece referans) |
