"""
Lead Scout Ajanı (Seviye 2)
===========================
Algoritmik filtreden geçen coinleri inceler ve "Konsey"e iletilecek 
en iyi adayları seçer.
"""

import json
import logging
from typing import List, Dict
from config.settings import get_settings, get_trading_params
from data.market_data import MarketDataClient
from models.technical_analyzer import TechnicalAnalyzer
from utils.llm_retry import invoke_with_retry

logger = logging.getLogger(__name__)

class LeadScout:
    """Adayları eleyen öncü ajan."""

    def __init__(self):
        self.settings = get_settings()
        self.params = get_trading_params().scanner
        self.client = MarketDataClient()
        self.analyzer = TechnicalAnalyzer()

    def select_best_candidates(self, candidates: List[Dict]) -> List[str]:
        """
        Aday listesini teknik özetlerle beraber LLM'e sunar ve en iyilerini seçtirir.
        """
        if not candidates:
            return []
            
        if len(candidates) <= self.params.max_scout_recommendations:
            logger.info("Aday sayısı limit altı, doğrudan konseye iletiliyor.")
            return [c['symbol'] for c in candidates]

        logger.info("Lead Scout %d aday için teknik özet hazırlıyor...", len(candidates))

        # Her aday için teknik özet oluştur
        enhanced_candidates_str = ""
        for cand in candidates:
            try:
                # 1 saatlik veri ile teknik analiz
                df = self.client.fetch_ohlcv(cand['symbol'], timeframe="1h", days=5)
                signals = self.analyzer.analyze(cand['symbol'], df)
                summary = signals.get_llm_summary()
                
                enhanced_candidates_str += f"\n{summary}\n"
                enhanced_candidates_str += f"Ek Skorlar: Kalite Puanı: {cand.get('quality_score', 0):.1f}, 1h Momentum: %{cand.get('change_1h', 0):.2f}\n"
                enhanced_candidates_str += "-" * 40 + "\n"
            except Exception as e:
                logger.warning("Teknik özet hatası (%s): %s", cand['symbol'], e)

        prompt = f"""
SEN BİR QUANT TRADING ANALİSTİSİN (LEAD SCOUT). 
Görevin: Aşağıdaki teknik verileri inceleyerek "Konsey" analizi için en yüksek potansiyele sahip {self.params.max_scout_recommendations} coin'i seçmek.

STRATEJİ: "EARLY MOMENTUM" - Henüz yolun başında olan, aşırı şişmemiş coinleri bul.

ANALİZ KRİTERLERİN (ÖNCELİLİK SIRASINA GÖRE):

1. ATR-NORMALİZE MOMENTUM (EN ÖNEMLİ):
   - "ATR Katı" 1.0-2.5x arası olanları tercih et (bu coinin kendi volatilitesine göre GÜÇLÜ sinyal)
   - Bitcoin için %2 = 1.5 ATR katı (güçlü)
   - PEPE için %6 = 1.5 ATR katı (güçlü)
   - ATR Katı > 4.0 olanlardan KAÇIN (aşırı, düzeltme riski)

2. SESSİZ BİRİKİM (DIVERGENCE) - BÜYÜK FIRSAT:
   - "Sessiz Birikim: EVET" olan coinler HACİM artıyor ama fiyat henüz patlamadı
   - Bu coinler "patlama öncesi son çıkış" adayıdır
   - Örnek: Hacim 3x, Fiyat +1% → ÇOK GÜÇLÜ SİNYAL

3. ERKEN MOMENTUM BÖLGESİ:
   - 24h değişimi %2-5 arası (early stage) → EN YÜKSEK ÖNCELİK
   - %5-8 arası (mid stage) → Kabul edilebilir ama ikinci tercih
   - %8+ (late stage) → KAÇIN (geç kalındı)

4. RSI SEVİYESİ:
   - RSI > 75 olanlardan uzak dur (aşırı almış)
   - İdeal: RSI 40-65 arası olup ivmelenenler

5. TREND GÜCÜ:
   - ADX > 25 ve SuperTrend Bullish olanlar önceliklidir

6. KALİTE PUANI:
   - Algoritma tarafından hesaplanan toplam skor (ATR-normalized + divergence bonusu)
   - Min 45 puan önerilir, 60+ çok güçlü

VERİ SETİ:
{enhanced_candidates_str}

ÇIKTI TALİMATI:
- Sadece bir JSON array döndür. 
- Array içinde sadece sembol isimleri olsun.
- Örnek: ["BTC/USDT", "SOL/USDT"]
- BAŞKA HİÇBİR METİN YAZMA.
"""

        try:
            from openai import OpenAI
            llm_client = OpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url
            )
            
            def call_llm():
                return llm_client.chat.completions.create(
                    model=self.params.scout_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=300
                )

            # Elephant-alpha için JSON doğrulamalı retry (timeout=None for OpenRouter)
            response = invoke_with_retry(
                call_llm,
                max_retries=5,
                validate_json=True,
                request_timeout=None
            )
            
            # response'dan content'i al (invoke_with_retry response'un kendisini döndürüyor)
            content = response.choices[0].message.content.strip()
            
            # Markdown temizliği
            if "```json" in content:
                content = content.split("```json")[-1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[-1].split("```")[0].strip()
                
            selected_symbols = json.loads(content)
            
            if not isinstance(selected_symbols, list):
                raise ValueError("LLM format is not a list")
                
            logger.info("Lead Scout (Elephant-Alpha) seçimi: %s", selected_symbols)
            return selected_symbols

        except Exception as e:
            logger.error("Lead Scout LLM hatası: %s. Yedek plan (En yüksek skorlu adaylar) uygulanıyor.", e)
            # Hata durumunda skora göre en iyi N tanesini döndür
            return [c['symbol'] for c in candidates[:self.params.max_scout_recommendations]]

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    scout = LeadScout()
    mock_candidates = [
        {"symbol": "BTC/USDT", "price": 65000, "change_24h": 5.2, "volume_24h": 500000000},
        {"symbol": "PEPE/USDT", "price": 0.00001, "change_24h": 15.1, "volume_24h": 200000000},
        {"symbol": "ETH/USDT", "price": 3500, "change_24h": 2.1, "volume_24h": 300000000},
    ]
    print(scout.select_best_candidates(mock_candidates))
