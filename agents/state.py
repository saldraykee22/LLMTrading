"""
Ajan Durum Modülü (Trading State)
===================================
LangGraph çoklu ajan sistemi için paylaşımlı durum tanımı.
Tüm ajanlar bu durumu okur ve günceller.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict


class TradingState(TypedDict):
    """
    Çoklu ajan sistemi için merkezi durum nesnesi.
    LangGraph StateGraph'ın paylaşımlı belleği olarak kullanılır.
    """

    # ── İletişim ───────────────────────────────────────────
    messages: Annotated[list[dict], operator.add]  # Ajan mesaj geçmişi

    # ── Girdi Verileri ─────────────────────────────────────
    symbol: str  # Analiz edilen sembol
    market_data: dict[str, Any]  # OHLCV özeti
    news_data: list[dict[str, Any]]  # Haberler (serialized)
    technical_signals: dict[str, Any]  # Teknik göstergeler

    # ── Analiz Sonuçları ───────────────────────────────────
    sentiment: dict[str, Any]  # LLM duyarlılık analizi
    research_report: dict[str, Any]  # Araştırmacı raporu
    debate_result: dict[str, Any]  # Bull vs Bear tartışma sonucu

    # ── Risk ve Karar ──────────────────────────────────────
    risk_assessment: dict[str, Any]  # Risk değerlendirmesi
    risk_approved: bool  # Risk onayı
    trade_decision: dict[str, Any]  # Nihai alım/satım kararı

    # ── Portföy ────────────────────────────────────────────
    portfolio_state: dict[str, Any]  # Mevcut portföy durumu

    # ── Kontrol ────────────────────────────────────────────
    iteration: int  # Döngü sayacı
    error: str  # Hata mesajı (varsa)
    phase: str  # Mevcut aşama adı
    provider: str  # LLM sağlayıcı override (opsiyonel)


def create_initial_state(
    symbol: str,
    market_data: dict | None = None,
    news_data: list | None = None,
    technical_signals: dict | None = None,
    portfolio_state: dict | None = None,
    provider: str | None = None,
) -> TradingState:
    """Başlangıç durumu oluşturur."""
    return TradingState(
        messages=[],
        symbol=symbol,
        market_data=market_data or {},
        news_data=news_data or [],
        technical_signals=technical_signals or {},
        sentiment={},
        research_report={},
        debate_result={},
        risk_assessment={},
        risk_approved=False,
        trade_decision={},
        portfolio_state=portfolio_state or {},
        iteration=0,
        error="",
        phase="init",
        provider=provider or "",
    )
