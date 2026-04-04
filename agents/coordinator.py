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

    has_market = bool(state.get("market_data"))
    has_news = bool(state.get("news_data"))
    has_technical = bool(state.get("technical_signals"))

    status_msg = (
        f"[Koordinatör] Analiz başlatılıyor: {symbol}\n"
        f"  Piyasa verisi: {'✓' if has_market else '✗'}\n"
        f"  Haber verisi: {'✓' if has_news else '✗'} ({len(state.get('news_data', []))} haber)\n"
        f"  Teknik göstergeler: {'✓' if has_technical else '✗'}\n"
        f"  İterasyon: #{iteration}"
    )

    logger.info(status_msg)

    return {
        "messages": [{"role": "coordinator", "content": status_msg}],
        "phase": "research",
        "iteration": iteration + 1,
    }
