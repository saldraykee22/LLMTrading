# Agent Architecture (Ajan Mimarisi)

Bu proje **LangGraph** kullanılarak geliştirilmiş bir Durum Grafiği (StateGraph) mekanizmasına dayanır. Ajanlar sırayla çalışır. Her bir ajan, bir önceki ajanın ürettiği durum nesnesini okuyup günceller.

Durum nesnesi (State), `agents/state.py` içerisinde tanımlanan `TradingState` adlı bir `TypedDict` sınıfıdır.

## 🤖 1. Coordinator Node (Koordinatör)
**Dosya**: `agents/coordinator.py`
**Görevi**: Sistemin ana orkestra şefi. İlk aşamada toparlanmış olan piyasa verileri, haber verileri ve teknik indikasyonların bütünlüğünü kontrol eder.
- **Input**: İşlem yapılacak sembol ve toplanmış raw data.
- **Output**: Sürecin başlayıp başlamayacağına dair iterasyon sayacı kontrolü. Veriler eksik veya limitin altındaysa sistemi sonraki adıma (Research Analyst) aktarır veya hatayla sonlandırır.

## 🧠 2. Research Analyst (Araştırmacı Ajan)
**Dosya**: `agents/research_analyst.py`
**Görevi**: Teknik verileri ve son 24 saatin haber özetlerini işleyerek duyarlılık (sentiment) analizi yapmak.
- **Mimari Notu**: Bu ajan içerisinde ekstra bir **SentimentAnalyzer** modülü çalışır (Chain-of-Thought - CoT kullanılarak). Puanları ve teknik verileri LLM üzerinden geçirerek varlık hakkında "genel tavsiye", "risk" ve "trend gücü" içeren kapsamlı bir araştırma raporu derler.
- **Çıktı (Payload)**: `research_report` dict, `sentiment` dict.

## ⚔️ 3. Bull vs Bear Debate (Tartışma / Halüsinasyon Filtresi)
**Dosya**: `agents/debate.py`
**Görevi**: Modelin körü körüne haberlerin etkisinde kalarak halüsinasyon görmesini (hallucination/confirmation bias) engellemek. 
- **İşleyiş**: 
  - **Bull Agent**: Varlığın kesinlikle yükseleceğini kanıtlamaya çalışan karşıt görüş argümanı hazırlar. (Sistem istemi ona zorla bullish olmasını söyler).
  - **Bear Agent**: Varlığın kesinlikle düşeceğini veya tehlikeli olduğunu kanıtlamaya çalışan karşıt argüman.
  - **Moderator**: İki argümanı değerlendirir, hangi argümanların veri (teknik/temel) ile örtüştüğünü ve hangilerinin uydurma (halüsinasyon) olduğunu tespit edip bir *Konsensüs Skoru (Consensus Score)* çıkarır.
- **Çıktı (Payload)**: `debate_result` (Kim kazandı, güven skoru nedir).

## 🛡️ 4. Risk Manager (Risk Yöneticisi)
**Dosya**: `agents/risk_manager.py`
**Görevi**: Tüm raporları inceler. Algoritmik/Deterministik kurallar ile Bilişsel/LLM kurallarını çarpıştırır.
- **Algoritmik Kontroller**: Mevcut pozisyon limiti doldu mu? VIX endeksi çok mu yüksek? Debate kısmında 2'den fazla halüsinasyon mu tespit edildi? Eğer deterministik kontroller başarısız olursa, işlemi doğrudan *REDDEDER*.
- **Bilişsel Kontroller**: LLM'ye (daha muhafazakar promptlar ile) işlem analizini gösterir ve Take Profit / Stop Loss seviyelerini, önerilen pozisyon büyüklüğünü ayarlamasını ister.
- **Yönlendirme Durumu**:
  - `risk_approved = True` ise → **Trader** ajana geç.
  - `risk_approved = False` ise → **Coordinator** ajana (Retry mekanizmasıyla, max loop 3 defa) geri dön.
- **Çıktı (Payload)**: `risk_assessment`, `risk_approved`.

## 💼 5. Trader (İşlemci / Yürütücü Ajan)
**Dosya**: `agents/trader.py`
**Görevi**: Risk Yöneticisi ve diğer tüm birimlerin kararlarını standart, borsaların (CEX) anlayacağı formatta bir JSON aksiyon emrine (Action Order) çevirmek.
- **Çıktı Formatı**: 
  ```json
  {
      "action": "buy/sell/hold",
      "order_type": "market",
      "amount": 0.035,
      "stop_loss": 62000,
      "take_profit": 68000
  }
  ```
- **Çıktı (Payload)**: `trade_decision`.
Bu çıktı LangGraph döngüsünden dışarı çıkarak doğrudan uygulamanın ana yapısında bulunan `execution/order_manager.py` modülüne beslenir.
