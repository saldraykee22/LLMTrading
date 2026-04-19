# 🚀 Canlı İşlem Kurulum Rehberi (Live Trading Setup)

Bu rehber, LLMTrading sistemini gerçek zamanlı piyasa verileri ve borsa entegrasyonu ile nasıl çalıştıracağınızı anlatır.

## ⚠️ ÖNEMLİ RİSK UYARISI
Canlı işlem yapmak sermaye kaybı riski içerir. Botu gerçek parayla çalıştırmadan önce en az 2 hafta **Paper Trading** modunda test etmeniz ve [docs/RISK_MANAGEMENT.md](docs/RISK_MANAGEMENT.md) dokümanını tam olarak okumanız ŞİDDETLE önerilir.

---

## 🛠️ Kurulum Adımları

### 1. API Anahtarlarının Yapılandırılması
`.env` dosyanıza borsa ve (opsiyonel) bildirim anahtarlarınızı ekleyin:

```env
# Borsa Anahtarları
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET=false

# Telegram Bildirimleri (Kritik hatalar için önerilir)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 2. Yapılandırma Kontrolü
`config/trading_params.yaml` dosyasında canlı işlem ayarlarını doğrulayın:

```yaml
execution:
  mode: live
  exchange: binance
  retry_count: 3
  
watchdog:
  enabled: true  # Flash crash ve SL/TP koruması için AÇIK tutun
```

### 3. Çalıştırma
Sistemi canlı modda (emir gönderimi aktif) başlatmak için:

```bash
python scripts/run_live.py --symbol BTC/USDT --execute --watchdog
```

---

## 🛡️ Güvenlik ve Dayanıklılık Protokolleri

1. **Borsa Senkronizasyonu:** Bot başladığında yerel portföy durumunu otomatik olarak borsa bakiyesiyle eşler. Senkronizasyon hatası durumunda bot güvenlik gereği çalışmaz.
2. **Anlık Bildirimler:** Circuit Breaker tetiklendiğinde veya Watchdog acil durdurma yaptığında Telegram üzerinden anlık mesaj gönderilir.
3. **Flash Crash Koruması:** `--watchdog` bayrağı ile çalışan Watchdog, piyasadaki ani düşüşleri izler ve gerekirse tüm pozisyonları kapatıp sistemi durdurur (data/STOP).
4. **SL/TP Yönetimi:** Zarar durdurma ve kar alma kontrolleri arka planda (Watchdog) saniyelik olarak yapılır.
5. **IP Restriction:** Borsa tarafında API anahtarlarınızı sadece botun çalıştığı IP adresi ile sınırlandırın.
6. **Withdrawal Disabled:** API anahtarınızın "Withdraw" (Para Çekme) yetkisinin KAPALI olduğundan emin olun.

## 📊 İzleme ve Loglama (Monitoring)

- **Logs:** `logs/trading.log` dosyasını takip edin. Loglar günlük olarak rotasyona uğrar ve 30 gün saklanır.
- **Acil Durdurma:** Sistemi manuel durdurmak için `data/` klasörü içinde boş bir `STOP` dosyası oluşturun.
- **Restart:** Botu durdurup tekrar başlattığınızda, kaldığı yerden borsa ile senkronize şekilde devam eder.

---
> **Not:** Emoji kodlamaları ve Türkçe karakter uyumu UTF-8 olarak optimize edilmiştir.
