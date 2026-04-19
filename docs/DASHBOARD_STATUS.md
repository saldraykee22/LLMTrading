# Aegis Terminal Status: INACTIVE / ON HOLD

> [!IMPORTANT]
> **Status:** Detached / Headless-First
> **Date:** 2026-04-19
> **Context:** The "Aegis Terminal 3.0" UI development has been suspended. The user has expressed UI fatigue and requested that the trading bot operate independently of the web dashboard.

## To Future AI Agents (Ajanlar İçin Bilgilendirme)
Bu proje şu an için **Dashboard-bağımsız (Headless)** çalışacak şekilde yapılandırılmıştır. Arayüz kısmındaki yoğun geliştirme süreci kullanıcıyı yorduğu için, sistemin görsel kısmına değil, işlem mantığına (Trading Logic) odaklanılması kararlaştırılmıştır.

### Mevcut Durum (Current State)
1. **Dashboard Server:** `dashboard/server.py` manuel olarak başlatılmadığı sürece kapalı kalmalıdır.
2. **Bot Execution:** Bot, CLI/Terminal üzerinden tam yetkiyle çalışmaktadır. Dashboard bağlantısı zorunlu değildir.
3. **UI Code:** `dashboard/` altındaki dosyalar (Aegis 3.0 tasarımı dahil) "Frozen/Dondurulmuş" durumdadır. Kullanıcı talimat vermediği sürece tasarımda değişiklik yapmayın.

### Botu Başlatma (Running the Bot)
Botu dashboard olmadan çalıştırmak için:
```powershell
$env:PYTHONPATH="."; python main.py
```
(Veya kullanılan ana giriş dosyası hangisiyse).

---
*Bu belge, kullanıcı isteği üzerine sistemin neden "kapalı" veya "bağımsız" olduğunu açıklamak amacıyla oluşturulmuştur.*
