# 📚 LLMTrading Dokümantasyon İndeksi

LLM Autonomous Trading System (Faz 7) için kapsamlı rehber haritası.

## 🗺️ Dokümantasyon Haritası

### 🚀 Başlangıç ve Kurulum
- **[README.md](../README.md)**: Proje özeti, kurulum adımları ve temel özellikler.
- **[LIVE_TRADING_SETUP.md](../LIVE_TRADING_SETUP.md)**: Canlı işlem kurulumu, API anahtarları ve güvenlik protokolleri.

### 🏗️ Mimari ve Teknik Detaylar
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: 6 Katmanlı sistem mimarisi, veri akışı ve modül yapıları.
- **[AGENTS.md](AGENTS.md)**: LangGraph ajan grafiği, düğümler (Nodes), I/O yapıları ve yeni hold_decision mekanizması.

### 🛡️ Risk ve İzleme
- **[RISK_MANAGEMENT.md](RISK_MANAGEMENT.md)**: Circuit Breaker, Regime Filter, Deterministik kontroller ve CVaR optimizasyonu.
- **[DRIFT_MONITOR.md](DRIFT_MONITOR.md)**: Model performans takibi, istatistiksel sapma tespiti ve düzeltici eylemler.

### 🧠 Gelişmiş Özellikler
- **[RAG_MEMORY.md](RAG_MEMORY.md)**: Tarihsel veriler ve geçmiş işlemler için vektör tabanlı hafıza sistemi.
- **[PROMPT_EVOLVER.md](PROMPT_EVOLVER.md)**: Kendi kendini geliştiren ve optimize olan ajan komutları (Prompts).

---

## 📅 Geliştirme Yol Haritası (Phases)

| Faz | Açıklama | Durum |
|-----|----------|-------|
| 1-3 | Temel Altyapı ve Backtest | ✅ Tamamlandı |
| 4-5 | Portföy Yönetimi ve Maliyet Optimizasyonu | ✅ Tamamlandı |
| 6 | Drift Monitor ve RAG Entegrasyonu | ✅ Tamamlandı |
| 7 | Ensemble Voter ve Prompt Evolver | ✅ Tamamlandı |
| 8-9 | RL Advisor ve Gelişmiş Hafıza | 🔄 Planlanıyor |

---

## 🛠️ Hızlı Erişim Linkleri
- **Veritabanı Şeması:** [schema.sql](../results/schema.sql)
- **Hata Ayıklama:** [docs/AGENTS.md#troubleshooting](AGENTS.md#troubleshooting)
- **API Referansı:** [docs/DRIFT_MONITOR.md#api-reference](DRIFT_MONITOR.md#api-reference)

---
> **Son Güncelleme:** 2026-04-17 | **Dokümantasyon Versiyonu:** 1.2.0 (Faz 7)
