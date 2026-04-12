"""
Ana Ajan Grafiği (LangGraph StateGraph)
=========================================
Çoklu ajan iş akışını tanımlar:

   Coordinator → Research Analyst → Debate → Risk Manager → Trader → END
                                                           │
                                              ┌────────────┴────────────┐
                                              ↓                         ↓
                                          (Approved)                (Rejected)
                                              ↓                         ↓
                                        Trader → END          Hold Decision → END
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from agents.coordinator import coordinator_node
from agents.debate import debate_node
from agents.research_analyst import research_analyst_node
from agents.risk_manager import risk_manager_node
from agents.rl_advisor import rl_advisor_node
from agents.state import TradingState, trim_messages
from agents.trader import trader_node
from config.settings import get_trading_params

logger = logging.getLogger(__name__)

_cached_app = None


def get_compiled_graph():
    global _cached_app
    if _cached_app is None:
        _cached_app = compile_trading_graph()
    return _cached_app


def _should_continue_after_risk(state: TradingState) -> str:
    """
    Risk yöneticisi kararından sonra yönlendirme.

    Akış mantığı:
    - Risk onaylandıysa → trader (emir oluştur)
    - Risk reddedildiyse ama açık pozisyon varsa → monitor_positions (pozisyonları izle)
    - Risk reddedildiyse ve açık pozisyon yoksa → direkt hold kararı ile bitir (END)
    """
    risk_approved = state.get("risk_approved", False)
    has_open_positions = state.get("portfolio_state", {}).get("open_positions", 0) > 0

    if risk_approved:
        logger.info("Risk onaylandı → RL Advisor'a yönlendiriliyor")
        return "rl_advisor"
    elif has_open_positions:
        # Risk reddedildi ama açık pozisyon var → monitor mode
        logger.info("Risk reddedildi, açık pozisyonlar izleniyor → Monitor'a yönlendiriliyor")
        return "monitor_positions"
    else:
        # Red → hold kararı ile sonlandır
        risk_data = state.get("risk_assessment", {})
        failed_checks = risk_data.get("checks_failed", [])
        logger.warning(
            "Risk reddedildi → HOLD kararı ile sonlandırılıyor. Nedenler: %s",
            failed_checks,
        )
        return "hold_decision"

def _monitor_positions_node(state: TradingState) -> dict[str, Any]:
    """Açık pozisyonları izle, stop-loss/take-profit kontrol et"""
    symbol = state["symbol"]
    
    msg = f"[Monitor] {symbol} pozisyonları izleniyor, risk kapalı olduğu için yeni emir yok."
    logger.info(msg)
    
    return {
        "messages": [{"role": "monitor", "content": msg}],
        "phase": "monitoring",
    }

def _hold_decision_node(state: TradingState) -> dict[str, Any]:
    """
    Risk reddettiğinde hold kararı oluşturan düğüm.
    Retry loop'u kaldırır — aynı veriyle tekrar analiz mantıksız.
    """
    risk_data = state.get("risk_assessment", {})
    symbol = state["symbol"]

    hold_decision = {
        "action": "hold",
        "symbol": symbol,
        "reason": "Risk yönetimi tarafından reddedildi",
        "risk_checks_failed": risk_data.get("checks_failed", []),
        "risk_warnings": risk_data.get("warnings", []),
    }

    msg = (
        f"[Risk → Hold] {symbol} — risk kontrolleri başarısız, "
        f"işlem yapılmıyor. Başarısız: {len(risk_data.get('checks_failed', []))} kontrol"
    )
    logger.info(msg)

    return {
        "messages": [{"role": "risk_manager", "content": msg}],
        "trade_decision": hold_decision,
        "phase": "complete",
    }


def build_trading_graph() -> StateGraph:
    """
    Çoklu ajan alım-satım grafını oluşturur ve derler.

    Akış:
    coordinator → research_analyst → debate → risk_manager
                                               │
                                  ┌────────────┴────────────┬─────────────┐
                                  ↓                         ↓             ↓
                              (Approved)           (Rejected+Open)   (Rejected)
                                  ↓                         ↓             ↓
                            trader → END      monitor_positions → END   hold_decision → END
    """
    graph = StateGraph(TradingState)

    # ── Düğümleri ekle ────────────────────────────────────
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("research_analyst", research_analyst_node)
    graph.add_node("debate", debate_node)
    graph.add_node("risk_manager", risk_manager_node)
    graph.add_node("rl_advisor", rl_advisor_node)
    graph.add_node("trader", trader_node)
    graph.add_node("monitor_positions", _monitor_positions_node)
    graph.add_node("hold_decision", _hold_decision_node)

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
            "rl_advisor": "rl_advisor",
            "monitor_positions": "monitor_positions",
            "hold_decision": "hold_decision",
        },
    )

    graph.add_edge("rl_advisor", "trader")

    graph.add_edge("trader", END)
    graph.add_edge("monitor_positions", END)
    graph.add_edge("hold_decision", END)

    return graph


def compile_trading_graph():
    """Grafı derler ve çalıştırılabilir hale getirir."""
    graph = build_trading_graph()
    compiled = graph.compile()
    logger.info("Ajan grafı derlendi (6 düğüm, koşullu yönlendirme)")
    return compiled


# ── Kolaylık fonksiyonu ───────────────────────────────────
def run_analysis(
    symbol: str,
    market_data: dict | None = None,
    news_data: list | None = None,
    technical_signals: dict | None = None,
    portfolio_state: dict | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """
    Tek bir sembol için tam analiz pipeline'ını çalıştırır.

    Args:
        symbol: Varlık sembolü (ör. BTC/USDT, AAPL)
        market_data: OHLCV veri özeti
        news_data: Haber verileri (serialized dict listesi)
        technical_signals: Teknik gösterge verileri
        portfolio_state: Mevcut portföy durumu
        provider: LLM sağlayıcı override (openrouter, deepseek, ollama)

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
        provider=provider,
    )

    app = get_compiled_graph()
    result = app.invoke(initial)

    # ── Son Kararı RAG Hafızasına Kaydet ───────────────────
    try:
        from data.vector_store import AgentMemoryStore
        from evaluation.drift_monitor import DriftMonitor

        acc = DriftMonitor().get_agent_accuracy(symbol, agent_name="trader")
        AgentMemoryStore().store_decision(result, accuracy_score=acc)
    except Exception as e:
        logger.error("Hafıza kaydetme hatası: %s", e)

    return result
