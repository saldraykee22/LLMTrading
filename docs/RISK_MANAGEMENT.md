# Risk Management Systems (Risk Yonetimi Sistemleri)

Bir ticaret sisteminde kardan cok zarari (drawdown) yonetmek kritiktir. Ajanlarin halusnasyon gormesi muhtemel oldugundan risk mekanizmalari ikiye ayrilmistir: **Algoritmik** (Kodla kati sekilde saglanan) ve **Bilissel** (Risk Ajani ile yonetilen).

> **Son Guncelleme:** 2026-04-05 (Faz 1, 2, 3, 4, 5 tamamlandi)

---

## Risk Katmanlari (Defense in Depth)

```
[Islem Istegi Geldi]
        |
        v
[0. Watchdog]             <- Arka planda flash crash izleme (30sn)
        |
        v
[1. Circuit Breaker]    <- Art arda kayip? Gunluk limit? Manuel STOP?
        |
        v
[2. Regime Filter]      <- VIX kriz? Piyasa volatile? Halt?
        |
        v
[3. Risk Manager]       <- Deterministik kontroller (kod)
        |
        v
[4. Risk Manager LLM]   <- Derin analiz, stop/tp seviyesi
        |
        v
[5. order_manager]      <- Tip dogrulama, ATR fallback stop
        |
        v
[ISLEM GERCEKLESTI]
```

**Prensip:** Her katman birbirinden bagimsizdir. LLM bir onceki katmani asamazsa sonraki katmana hic ulasamazlar.

---

## 0. Watchdog (Flash Crash Korumasi) [FAZ 5 - YENİ]

**Dosya:** `risk/watchdog.py`

Watchdog, ana islem dongusunden bagimsiz bir arka plan thread'inde calisan ve piyasadaki ani dususleri tespit eden bir emniyet mekanizmasidir.

### Neden Watchdog?

Ana pipeline belirli araliklarla (15dk, 1sa vb.) calisir. Bu araliklarda meydana gelen flash crash'ler (ani dususler) pipeline tarafindan yakalanamaz. Watchdog bu boslugu doldurur.

### Acil Satis Kurallari

| Kosul | Aksiyon | Aciklama |
|-------|---------|----------|
| **1 dakikada > %3 dusus** | ACIL SATIS | Tum acik pozisyonlar hemen kapatilir |
| **5 dakikada > %5 dusus** | ACIL SATIS | Tum acik pozisyonlar hemen kapatilir |
| **5 dakikada %2-5 dusus** | Uyari | Log kaydi olusturulur, satis yapilmaz |

### Calisma Prensipleri

- **Thread:** Ana donguden bagimsiz arka plan thread'i
- **Kontrol Araligi:** Varsayilan 30 saniye (`check_interval_seconds`)
- **Referans Noktalari:** Her kontrolde 1dk ve 5dk onceki fiyatlar kaydedilir
- **Kapsam:** `--symbols` ile belirtilen tum semboller izlenir

### Yapilandirma (`config/trading_params.yaml`)

```yaml
watchdog:
  enabled: true
  check_interval_seconds: 30
  flash_crash_1min_pct: 0.03
  flash_crash_5min_pct: 0.05
  alert_5min_pct: 0.02
```

### Kapatma

```bash
# Watchdog olmadan calistir
python scripts/run_live.py --symbols BTC/USDT,ETH/USDT --no-watchdog
```

---

## 1. Circuit Breaker (Acil Durdurma) [FAZ 2 - YENİ]

**Dosya:** `risk/circuit_breaker.py`

Bot'u beklenmedik durumlarda otomatik veya manuel olarak durduran emniyet mekanizmasi.

### Tetikleyiciler

| Tetikleyici | Kosul | Parametre |
|-------------|-------|-----------|
| **Manuel STOP** | `data/STOP` dosyasi varsa | - |
| **Art arda kayip** | Ust uste N kayip | `max_consecutive_losses` (varsayilan: 5) |
| **Gunluk kayip** | daily_loss/equity >= esik | `max_daily_loss_pct` |
| **LLM hata zinciri** | Ust uste N LLM hatasi | `max_consecutive_llm_errors` (varsayilan: 10) |

### Manuel Durdurma

```bash
# Botu durdur
echo. > data/STOP

# Botu yeniden baslat (STOP dosyasini sil)
del data\STOP
```

### Kullanim

```python
cb = CircuitBreaker()
should_halt, reason = cb.should_halt(equity=portfolio.equity, daily_pnl=portfolio.daily_pnl)
if should_halt:
    console.print(f"CIRCUIT BREAKER: {reason}")
    return {"status": "halted", "reason": reason}
```

---

## 2. Regime Filter (Piyasa Rejimi Filtresi) & VIX

**Dosya:** `risk/regime_filter.py`

Yapay zeka modelleri ekstrem kriz kosullarini (Siyah Kugu / Black Swan) ongoremez. Bu yuzden `regime_filter.py` modulu surekli olarak VIX endeksini (Volatility Index) tarar.

- **Isleyis:** VIX'in SMA (Hareket Ortalamasi) deger izlenir.
- Eger VIX anlik olarak belli bir esik degerinin ustune firlarsa veya sabit olarak 40'i gecerse, sistem rejimi `CRISIS` olarak isaretlenir.
- `halt_trading = True` donduruler ve yapay zeka ne derse desin, tum islemler reddedilir.

### Rejim Seviyeleri

| Rejim | VIX Tahmini | Islem |
|-------|-------------|-------|
| `LOW_VOL` | < SMA * 0.8 | Serbest |
| `NORMAL` | SMA * 0.8 - SMA * 1.10 | Serbest |
| `HIGH_VOL` | > SMA * 1.10 | Kisitli |
| `CRISIS` | > 40 | Durduruldu |

---

## 3. Risk Manager - Deterministik Kontroller [FAZ 1 GUNCELLEME]

**Dosya:** `agents/risk_manager.py`

### Mevcut Kontroller

| # | Kontrol | Tip | Aciklama |
|---|---------|-----|----------|
| 1 | Guven skoru | Deterministik | sentiment.confidence < min_confidence |
| 2 | Halusnasyon | Deterministik | debate.hallucinations_detected > 2 |
| 3 | Sentiment-teknik uyum | Deterministik | Bullish sentiment + sell sinyal uyumsuzlugu |
| 4 | Acik pozisyon limiti | Deterministik | >= max_open_positions |
| 5 | **Drawdown limiti** | **Deterministik** | current_drawdown >= max_drawdown_pct **[Faz 1]** |
| 6 | **Gunluk kayip limiti** | **Deterministik** | daily_loss/equity >= max_daily_loss_pct **[Faz 1]** |
| 7 | **Pozisyon boyutu** | **Deterministik** | llm_size > equity * max_position_pct **[Faz 1]** |
| 8 | **Nötr sinyal** | **Deterministik** | Hem tartışma hem duyarlılık nötr ise red **[Faz 4]** |

> **Faz 1 oncesi:** 5, 6, 7 sadece LLM prompt'undaydi, kod tarafindan zorlanmiyordu.
> **Faz 1 sonrasi:** Bu kontroller LLM cagrisindan bagimsiiz sekilde cod tarafindan uygulanir.
> Kontrol 7, LLM ciktisini alip *sonrasinda* uygulanir (once LLM, sonra validate).

### Kontrol Parametreleri (`config/trading_params.yaml`)

```yaml
risk:
  max_drawdown_pct: 0.15        # %15 drawdown limiti
  max_daily_loss_pct: 0.03      # %3 gunluk kayip limiti
  max_position_pct: 0.05        # Equity'nin max %5'i tek pozisyon
  max_open_positions: 5         # Estzamanli max acik pozisyon
  max_consecutive_losses: 5     # Art arda kayip Circuit Breaker esigi
  max_consecutive_llm_errors: 10 # LLM hata Circuit Breaker esigi
```

---

## 4. Trailing Stop Loss (Dinamik/Izleyen Zarar-Kes - ATR Bazli)

**Dosya:** `risk/stop_loss.py`

Ortalama Gercek Aralik (ATR - Average True Range) kullanilir. Yapay zeka statik bir fiyat girerse bu fiyat genellikle piyasa spekulasyonu ile kolay temizlenen volatile bir noktaya denk gelebilir.

- **Dinamik:** Varlik lehe gittiginde, stop price adim adim yukari tasinir (long icin)
- Aleyhe dondugunde stop rakami ASLA geri cekilmez
- `Hard Stop Pct` ozelligi ile her durumda portfoy sermayesinin %x'inden fazlasini tek bir islemde yakmayacak kati bir yuzde sinirlama mevcuttur (Ornegin: %2)

### ATR Bazli Fallback Stop [FAZ 3 - YENİ]

**Dosya:** `execution/order_manager.py`

LLM stop-loss belirtmeyi unutursa `parse_trade_decision()` otomatik hesaplar:

```python
# LLM stop-loss vermezse ATR bazli hesapla
if stop_loss <= 0 and current_price > 0 and atr_value > 0:
    mult = params.stop_loss.atr_multiplier
    if action == "buy":
        stop_loss = current_price - (atr_value * mult)
    else:
        stop_loss = current_price + (atr_value * mult)
```

---

## 5. Conditional Value at Risk (CVaR)

**Dosya:** `risk/cvar_optimizer.py`

Mean-Variance (Markowitz) portfoy teorilerinin yerine daha gelismis bir kuyruk (tail-risk) yonetimi kullanilir.

- **Neden CVaR:** Basit Value at Risk (VaR), yatirimin %95 ihtimalle en fazla kaybedeceyi orani verir ancak o %5'in sonrasinda batisin ne kadar derin oldugunu bilmez. CVaR ise "Eger batarsak, bu dibin ortalamasi ne olacak" sorusunu baz alarak coklu varlik agirlik dagitimlarini gerceklestirir.
- Monte Carlo stres testi de mevcuttur (`stress_test_monte_carlo`)

---

## 6. Portfolio State & Persistence (Portfoy Takibi) [FAZ 1 GUNCELLEME]

**Dosya:** `risk/portfolio.py`

Tum Unrealized PNL ve Equity (Ozvarliy) bilgilerini tutar ve artik **diskde kalici olarak saklar**.

### Yeni Ozellikler [Faz 1]

**JSON Persistence:**
```python
# Bot baslarken
portfolio = PortfolioState.load_from_file()  # varsa dosyadan yukle

# Bot bitisinde
portfolio.save_to_file()  # data/portfolio_state.json'a kaydet
```

**Gunluk PNL Otomatik Sifirlama:**
```python
portfolio.reset_daily_pnl_if_needed()  # Gun degistiyse PNL=0
```

**Short Pozisyon Duzeltme:**
- Equity hesabinda short pozisyonun notional degeri artik dogruca cikartiliyor (eklenmiyordu)
- `close_position()` short kapanisinda dogru nakit akisi uyguluyor

### Kaydedilen Alanlar

```json
{
  "initial_cash": 10000.0,
  "cash": 9850.0,
  "positions": [...],
  "closed_trades": [...],
  "daily_pnl": -32.5,
  "daily_pnl_date": "2026-04-04",
  "total_pnl": 142.0,
  "max_equity": 10250.0,
  "current_drawdown": 0.039
}
```

---

## 7. Paper Trading Engine [FAZ 1 - YENİ]

**Dosya:** `execution/paper_engine.py`

Gercek borsaya hic ulas madan islem simule eder.

### Simulasyon Ozellikleri

| Ozellik | Aciklama |
|---------|----------|
| **Slippage** | Alis: fiyat * 1.001, Satis: fiyat * 0.999 |
| **Komisyon** | %0.1 (ayarlanabilir) |
| **Pozisyon takibi** | Acik pozisyonlar, P&L, drawdown |
| **Trade gecmisi** | Her islemin giris/cikis kaydi |

### Aktivasyon

`.env` dosyasinda:
```
EXECUTION_MODE=paper
```

Veya `config/trading_params.yaml`:
```yaml
execution:
  mode: paper
```

---

## 8. Portfolio Manager Risk Katmani [FAZ 4 - YENİ]

**Dosya:** `agents/portfolio_manager.py`

Portföy yöneticisi, tek varlik riskinin ötesinde **portföy seviyesinde risk yönetimi** yapar.

### Bileşik Skor Filtresi

Her varlik, 4 faktörün agirlikli ortalamasiyla skorlanir:

| Faktör | Agirlik | Açiklama |
|--------|---------|----------|
| Debate Consensus | %35 | Bull vs Bear tartışma sonucu (-1.0 ile 1.0) |
| Sentiment Score | %25 | Haber duyarlilik skoru (-1.0 ile 1.0) |
| Trend Strength | %20 | Teknik trend gücü (-1.0 ile 1.0) |
| RSI (ters) | %20 | Aşiri alim/satim göstergesi |

**Güven çarpani:** Düşük confidence skorlarini düsürür. `(confidence + 0.5) / 1.5`

### CVaR Optimizasyonu

- Tek varlik max agirlik: %40
- Optimizasyon basarisiz olursa skor bazli dagilim fallback
- Getiri matrisi son 90 günlük OHLCV verisinden hesaplanir

### Portföy Seviyesi Kontroller

- Min skor eşigi (`--min-score`): Altindaki varliklar elenir
- Max pozisyon sayisi (`--max-positions`): Portföy çeşitlendirme siniri
- Circuit Breaker: Portföy analizi öncesinde de kontrol edilir

---

## 9. Maliyet Optimizasyonu (Risk Stratejisi) [FAZ 5 - YENİ]

LLM API maliyetlerinin kontrolsuz artmasi, bir ticaret sistemi icin operasyonel risk olusturur. Faz 5 ile cok katmanli maliyet optimizasyonu getirilmistir.

### Prompt Sikistirma

Tum 5 prompt dosyasi ~%40-50 oraninda kucultulmustur:
- Gereksiz aciklamalar ve tekrarlar kaldirildi
- "be concise" kurali eklendi
- "ONLY return JSON" kurali eklendi

**Etki:** %30-40 input token azalma

### Sentiment Cache

`SentimentAnalyzer.analyze()` metodu LLM cagrisindan ONCE cache kontrolu yapar:
- Son analiz `sentiment_cache_minutes` (varsayilan 30) dakika icinde ise cache'den doner
- `SentimentRecord.price` alani ile piyasa degisim tespiti mumkun

**Etki:** %30-50 daha az LLM cagrisi

### max_tokens Sinirlari

Her ajanin maksimum cikti token siniri vardir:

| Ajan | max_tokens |
|------|-----------|
| Sentiment | 300 |
| Research | 500 |
| Debate | 400 |
| Moderator | 400 |
| Risk | 400 |
| Trader | 250 |

**Etki:** Runaway cikti maliyetleri onlenir

### JSON Mode

Tum LLM cagrilar `response_format={"type": "json_object"}` kullanir:
- Cikti format garantisi
- Parse hatasi azalmasi
- Daha tutarli ajan davranisi

### Prompt Caching (OpenRouter/DeepSeek)

Ayni prompt tekrar kullanildiginda, provider tarafindan cache isabeti saglanir:

**Etki:** %75-90 cached input indirimi

### Toplam Tasarruf

| Bilesen | Etki |
|---------|------|
| Prompt sikistirma | %30-40 input token azalma |
| Prompt caching | %75-90 cached input indirimi |
| Sentiment cache | %30-50 daha az LLM cagrisi |
| max_tokens sinirlari | Runaway onleme |
| **TOPLAM** | **~%72-88 API maliyet azalmasi** |
