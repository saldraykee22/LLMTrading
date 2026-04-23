"""
Koordinatör Ajan
=================
İş akışını başlatır, veri toplanmasını koordine eder
ve diğer ajanların çalışma sırasını yönetir.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.state import TradingState

logger = logging.getLogger(__name__)


def coordinator_node(state: TradingState) -> dict[str, Any]:
    """
    Koordinatör düğümü — iş akışının giriş noktası.

    Görevler:
    1. Durum doğrulama (veriler hazır mı?)
    2. Faz güncelleme
    3. Kontrol mesajı ekleme
    """
    symbol = state["symbol"]
    iteration = state.get("iteration", 0)

    logger.info("═" * 60)
    logger.info("Koordinatör başlatıldı: %s (iterasyon #%d)", symbol, iteration)
    logger.info("═" * 60)

    # Veri varlığı kontrolleri (None ve boş dict/list güvenliği)
    market_data = state.get("market_data")
    news_data = state.get("news_data")
    tech_signals = state.get("technical_signals")

    has_market = market_data is not None and len(market_data) > 0
    has_news = news_data is not None and len(news_data) > 0
    has_technical = tech_signals is not None and len(tech_signals) > 0

    status_msg = (
        f"[Koordinatör] Analiz başlatılıyor: {symbol}\n"
        f"  Piyasa verisi: {'✓' if has_market else '✗'}\n"
        f"  Haber verisi: {'✓' if has_news else '✗'} ({len(news_data) if has_news else 0} haber)\n"
        f"  Teknik göstergeler: {'✓' if has_technical else '✗'}\n"
        f"  İterasyon: #{iteration}"
    )

    logger.info(status_msg)

    return {
        "messages": [{"role": "coordinator", "content": status_msg}],
        "phase": "research",
        "iteration": iteration + 1,
    }
