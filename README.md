# LLM Otonom Trading Sistemi (Aegis Terminal)

![Versiyon](https://img.shields.io/badge/Versiyon-1.0.0-gold.svg)
![Lisans](https://img.shields.io/badge/Lisans-MIT-blue.svg)
![Python Versiyonu](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Durum](https://img.shields.io/badge/Aşama-Üretim_Hazır-brightgreen.svg)
![Trading](https://img.shields.io/badge/Canlı_İşlem-Aktif-blue.svg)

Aegis Terminal, finansal piyasalarda (Kripto, BIST, ABD Hisse Senetleri) bağımsız kararlar alabilen, **LangGraph tabanlı çoklu ajan (Multi-Agent) mimarisine** sahip yeni nesil bir yapay zeka alım-satım platformudur.

---

## 🚀 Proje Genel Bakış

Bu sistem, geleneksel teknik analizi (MACD, RSI, Bollinger) modern yapay zeka (LLM) yetenekleriyle birleştirir. Sadece rakamlara değil, piyasa haberlerine ve sosyal duyarlılığa da (sentiment) bakarak karar verir. "Halüsinasyon" riskini yönetmek için **Bull vs Bear Tartışma Paneli** ve bağımsız bir **Risk Yönetimi** katmanı kullanır.

### Temel Özellikler
- **Çoklu Ajan İş Akışı:** Coordinator, Research, Debate, Risk ve Trader ajanları arasındaki hiyerarşik iletişim.
- **Duyarlılık Analizi (Sentiment):** Haberler ve sosyal verilerin LLM ile duygu analizi.
- **Paper Trading Modu:** Gerçek para riske atmadan gerçek zamanlı strateji testi.
- **Portföy Optimizasyonu:** Birden fazla varlık arasında dinamik nakit dağılımı (CVaR).
- **Akıllı Koruma (Watchdog):** Ani fiyat düşüşlerinde (Flash Crash) saniyeler içinde acil satış.
- **Maliyet Verimliliği:** Prompt sıkıştırma ve önbellekleme ile %80'e varan API tasarrufu.

---

## 📁 Proje Yapısı

| Klasör / Dosya | Açıklama |
|----------------|----------|
| `agents/` | Tüm AI ajanlarının mantığı (Debate, Risk, Trader vb.) |
| `config/` | Strateji ve borsa yapılandırma dosyaları |
| `dashboard/` | Web tabanlı izleme paneli (P&L ve Portföy görünümü) |
| `data/` | Pazar verileri, bakiye durumları ve geçici önbellekler |
| `docs/` | Kapsamlı dökümantasyon ve platform rehberleri |
| `execution/` | Borsa bağlantısı ve emir iletim sistemleri |
| `scripts/` | Botu çalıştırmak ve test etmek için kullanılan scriptler |
| `tests/` | Entegrasyon ve birim testleri |

---

## 🛠️ Kurulum ve Kullanım

Kısa yoldan başlamak için aşağıdaki komutları izleyin:

```bash
# Sanal ortam oluştur ve aktifleştir
python -m venv venv
venv\Scripts\activate

# Bağımlılıkları yükle
pip install -r requirements.txt

# Çevre değişkenlerini ayarla
cp .env.example .env  # API anahtarlarınızı bu dosyaya ekleyin
```

### Hızlı Çalıştırma
Sistemi en kolay şekilde başlatmak için `scripts/baslat.bat` dosyasını kullanabilir veya doğrudan CLI üzerinden ilerleyebilirsiniz:

```bash
# BTC/USDT için 1 saatlik mumlarla paper trading başlat
python cli.py run --symbol BTC/USDT --interval 1h --watchdog
```

Daha detaylı bilgi için:
- 📖 [**Hızlı Başlangıç Rehberi**](docs/TR/HIZLI_BASLANGIC.md)
- ⚙️ [**Canlı İşlem Kurulumu**](docs/setup/LIVE_TRADING.md)
- 📜 [**CLI Komut Listesi**](docs/TR/CLI_KOMUTLARI.md)

---

## 🛡️ Güvenlik ve Risk Uyarısı

Bu yazılım otonom bir sistemdir. Canlı işlem yapmadan önce **Paper Trading** modunda en az 48 saat test yapılması ve belirlenen risk limitlerinin (`config/trading_params.yaml`) dikkatle incelenmesi şiddetle önerilir.

---

## 📄 Lisans
Bu proje [MIT Lisansı](LICENSE) altında korunmaktadır.
