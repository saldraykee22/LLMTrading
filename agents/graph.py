"""
Ana Ajan Grafiği (LangGraph StateGraph)
=========================================
Çoklu ajan iş akışını tanımlar:

  Coordinator → Research Analyst → Bull vs Bear Debate → Risk Manager
       ↑                                                      │
       └──────────── (Red ise, max 3 iterasyon) ──────────────┘
                                                               │
                                                           (Onay ise)
                                                               ↓
                                                            Trader → END
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from agents.coordinator import coordinator_node
from agents.debate import debate_node
from agents.research_analyst import research_analyst_node
from agents.risk_manager import risk_manager_node
from agents.state import TradingState
from agents.trader import trader_node
from config.settings import get_trading_params

logger = logging.getLogger(__name__)


def _should_continue_after_risk(state: TradingState) -> str:
    """
    Risk yöneticisi kararından sonra yönlendirme.
    - Onaylandıysa → trader
    - Reddedildiyse ve iterasyon limiti aşılmadıysa → coordinator (yeniden analiz)
    - Max iterasyona ulaşıldıysa → trader (hold kararıyla)
    """
    params = get_trading_params()
    risk_approved = state.get("risk_approved", False)
    iteration = state.get("iteration", 0)
    max_iter = params.agents.max_retry_iterations

    if risk_approved:
        logger.info("Risk onaylandı → Trader'a yönlendiriliyor")
        return "trader"

    if iteration >= max_iter:
        logger.warning(
            "Max iterasyon (%d) aşıldı → Trader'a yönlendiriliyor (hold)",
            max_iter,
        )
        return "trader"

    logger.info(
        "Risk reddedildi → Yeniden analiz (iterasyon %d/%d)",
        iteration,
        max_iter,
    )
    return "coordinator"


def build_trading_graph() -> StateGraph:
    """
    Çoklu ajan alım-satım grafını oluşturur ve derler.

    Akış:
    coordinator → research_analyst → debate → risk_manager
        ↑                                          │
        └──── (rejected, iter < max) ──────────────┘
                                                    │ (approved OR iter >= max)
                                                    ↓
                                                  trader → END
    """
    graph = StateGraph(TradingState)

    # ── Düğümleri ekle ────────────────────────────────────
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("research_analyst", research_analyst_node)
    graph.add_node("debate", debate_node)
    graph.add_node("risk_manager", risk_manager_node)
    graph.add_node("trader", trader_node)

    # ── Kenarları tanımla ─────────────────────────────────
    graph.set_entry_point("coordinator")

    graph.add_edge("coordinator", "research_analyst")
    graph.add_edge("research_analyst", "debate")
    graph.add_edge("debate", "risk_manager")

    # Risk sonrası koşullu yönlendirme
    graph.add_conditional_edges(
        "risk_manager",
        _should_continue_after_risk,
        {
            "trader": "trader",
            "coordinator": "coordinator",
        },
    )

    graph.add_edge("trader", END)

    return graph


def compile_trading_graph():
    """Grafı derler ve çalıştırılabilir hale getirir."""
    graph = build_trading_graph()
    compiled = graph.compile()
    logger.info("Ajan grafı derlendi (5 düğüm, koşullu döngü)")
    return compiled


# ── Kolaylık fonksiyonu ───────────────────────────────────
def run_analysis(
    symbol: str,
    market_data: dict | None = None,
    news_data: list | None = None,
    technical_signals: dict | None = None,
    portfolio_state: dict | None = None,
) -> dict[str, Any]:
    """
    Tek bir sembol için tam analiz pipeline'ını çalıştırır.

    Args:
        symbol: Varlık sembolü (ör. BTC/USDT, AAPL)
        market_data: OHLCV veri özeti
        news_data: Haber verileri (serialized dict listesi)
        technical_signals: Teknik gösterge verileri
        portfolio_state: Mevcut portföy durumu

    Returns:
        Nihai durum (tüm ajan çıktılarını içerir)
    """
    from agents.state import create_initial_state

    initial = create_initial_state(
        symbol=symbol,
        market_data=market_data,
        news_data=news_data,
        technical_signals=technical_signals,
        portfolio_state=portfolio_state,
    )

    app = compile_trading_graph()
    result = app.invoke(initial)

    return result
