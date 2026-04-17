# CLI Komut Referansı (Türkçe)

## Hızlı Başlangıç

### Tüm Komutları Görüntüle
```bash
python cli.py --help
```

### Sağlık Kontrolü
```bash
python cli.py saglik
```
Sistemin sağlıklı olup olmadığını kontrol eder.

### Trading Bot'u Başlat
```bash
# Paper trading (sanal para)
python cli.py calistir --sembol BTC/USDT --aralik 1h --bekci

# Canlı trading (GERÇEK para - DİKKAT!)
python cli.py calistir --sembol BTC/USDT --aralik 1h --bekci --yurut

# Otomatik piyasa taraması ile
python cli.py calistir --sembol BTC/USDT --aralik 1h --oto-tarama --bekci

# Sınırlı döngü (test için)
python cli.py calistir --sembol BTC/USDT --aralik 1h --maks-dongu 10
```

### Portföy Durumu
```bash
python cli.py portfoy
```
Açık pozisyonları ve toplam durumu gösterir.

### Sistem Durumu
```bash
python cli.py durum
```
Circuit Breaker ve portföy özetini gösterir.

### Piyasa Taraması
```bash
python cli.py tarama
```
Piyasayı tarar ve fırsatları bulur.

### Geriye Dönük Test
```bash
python cli.py geriye-donuk-test --sembol BTC/USDT --gun 90
```
Geçmiş verilerle test yapar.

### Kayıtları (Log) Göster
```bash
python cli.py kayitlar --satir 100
```
Son 100 kayıt satırını gösterir.

### Test Paketi
```bash
python cli.py testler
python cli.py testler --ayrintili  # Detaylı çıktı
```
Integration testlerini çalıştırır.

---

## Parametreler

### `calistir` Komutu Parametreleri

| Parametre | Kısa | Açıklama | Varsayılan |
|-----------|------|----------|------------|
| `--sembol` | `-s` | Sembol (örn: BTC/USDT) | **Zorunlu** |
| `--aralik` | `-a` | Mum aralığı (5m, 15m, 30m, 1h, 4h) | `1h` |
| `--bekci` | `-b` | Flash crash koruması aktif et | Kapalı |
| `--yurut` | `-y` | Canlı işlem (DİKKAT!) | Kapalı |
| `--oto-tarama` | - | Otomatik piyasa taraması | Kapalı |
| `--maks-dongu` | - | Maksimum döngü sayısı (0=sınırsız) | `0` |

### `geriye-donuk-test` Komutu Parametreleri

| Parametre | Kısa | Açıklama | Varsayılan |
|-----------|------|----------|------------|
| `--sembol` | `-s` | Sembol | **Zorunlu** |
| `--gun` | `-g` | Geçmiş gün sayısı | `90` |

### `kayitlar` Komutu Parametreleri

| Parametre | Kısa | Açıklama | Varsayılan |
|-----------|------|----------|------------|
| `--satir` | `-n` | Gösterilecek satır sayısı | `50` |

### `testler` Komutu Parametreleri

| Parametre | Kısa | Açıklama | Varsayılan |
|-----------|------|----------|------------|
| `--ayrintili` | `-a` | Detaylı çıktı | Kapalı |

---

## Örnek Kullanımlar

### 1. İlk Başlangıç
```bash
# Önce sağlık kontrolü yap
python cli.py saglik

# Paper trading başlat (BTC/USDT, 1 saatlik mumlar)
python cli.py calistir --sembol BTC/USDT --aralik 1h --bekci
```

### 2. Günlük Kullanım
```bash
# Portföy durumunu kontrol et
python cli.py portfoy

# Sistem durumunu kontrol et
python cli.py durum

# Bot'u başlat
python cli.py calistir --sembol ETH/USDT --aralik 15m --bekci
```

### 3. Gelişmiş Kullanım
```bash
# Otomatik piyasa taraması ile en iyi adayları bul
python cli.py tarama

# Bulunan adaylardan biri ile trading
python cli.py calistir --sembol SOL/USDT --aralik 30m --bekci --oto-tarama

# Arka planda çalıştır (Windows)
start /B python cli.py calistir --sembol BTC/USDT --aralik 1h --bekci
```

### 4. Test ve Analiz
```bash
# Geriye dönük test
python cli.py geriye-donuk-test --sembol BTC/USDT --gun 180

# Test paketini çalıştır
python cli.py testler

# Son kayıtları incele
python cli.py kayitlar --satir 200
```

---

## Hata Kodları

| Kod | Açıklama |
|-----|----------|
| `0` | Başarılı |
| `1` | Hata oluştu |

---

## İpuçları

### 1. Güvenlik
- İlk defa kullanıyorsanız `--yurut` parametresini kullanmayın (paper trading ile başlayın)
- `--bekci` parametresini her zaman kullanın (flash crash koruması)
- Canlı trading için `.env` dosyasında `TRADING_MODE=live` ve `CONFIRM_LIVE_TRADE=true` ayarlayın

### 2. Performans
- Kısa aralıklar (5m, 15m) daha fazla işlem yapar ama daha riskli
- Uzun aralıklar (1h, 4h) daha az işlem yapar ama daha güvenli
- `--maks-dongu` ile test amaçlı sınırlı döngü çalıştırın

### 3. Monitoring
- Bot çalışırken başka terminal'de `python cli.py durum` çalıştırın
- Kayıtları izlemek için: `python cli.py kayitlar -n 50`
- Portföyü kontrol için: `python cli.py portfoy`

---

## Sık Kullanılan Komutlar

```bash
# En sık kullanılan: Paper trading başlat
python cli.py calistir --sembol BTC/USDT --aralik 1h --bekci

# Portföy kontrol
python cli.py portfoy

# Sistem durumu
python cli.py durum

# Sağlık kontrolü
python cli.py saglik
```

---

**İyi İşlemler! 🚀**
