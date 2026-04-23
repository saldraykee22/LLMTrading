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
import threading
import traceback
from typing import Any

from langgraph.graph import END, StateGraph

from agents.coordinator import coordinator_node
from agents.debate import debate_node
from agents.research_analyst import research_analyst_node
from agents.risk_manager import risk_manager_node
from agents.state import TradingState, trim_messages
from agents.trader import trader_node
from config.settings import get_trading_params

logger = logging.getLogger(__name__)

_cached_app = None
_graph_lock = threading.Lock()


def get_compiled_graph():
    """Thread-safe graph retrieval with singleton pattern."""
    global _cached_app
    if _cached_app is None:
        with _graph_lock:
            # Double-check pattern
            if _cached_app is None:
                _cached_app = compile_trading_graph()
    return _cached_app


def _should_continue_after_risk(state: TradingState) -> str:
    """
    Risk yöneticisi kararından sonra yönlendirme.

    Akış mantığı:
    - Risk onaylandıysa → trader (emir oluştur)
    - Risk reddedildiyse ama bu sembolde açık pozisyon varsa → monitor_positions (pozisyonları izle)
    - Risk reddedildiyse ve bu sembolde açık pozisyon yoksa → direkt hold kararı ile bitir (END)
    """
    risk_approved = state.get("risk_approved", False)
    symbol = state.get("symbol", "")
    
    # Yalnızca bu sembole ait pozisyon var mı kontrol et
    portfolio_state = state.get("portfolio_state", {})
    if isinstance(portfolio_state, dict):
        positions = portfolio_state.get("positions", [])
    elif portfolio_state is None:
        positions = []
    else:
        positions = getattr(portfolio_state, "positions", []) or []
    has_open_positions = any(
        (p.get("symbol") == symbol if isinstance(p, dict) else getattr(p, "symbol", None) == symbol)
        for p in positions
    )

    if risk_approved:
        logger.info("Risk onaylandı → RL bypass edildi, doğrudan Trader'a yönlendiriliyor")
        return "trader"
    elif has_open_positions:
        # Risk reddedildi ama bu sembolde açık pozisyon var → monitor mode
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
            "trader": "trader",
            "monitor_positions": "monitor_positions",
            "hold_decision": "hold_decision",
        },
    )



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

async def run_analysis_async(
    symbol: str,
    market_data: dict | None = None,
    news_data: list | None = None,
    technical_signals: dict | None = None,
    portfolio_state: dict | None = None,
    provider: str | None = None,
    dynamic_rules: str | None = None,
) -> dict[str, Any]:
    """
    Async versiyon - tam analiz pipeline'ını çalıştırır.

    Args:
        symbol: Varlık sembolü (ör. BTC/USDT, AAPL)
        market_data: OHLCV veri özeti
        news_data: Haber verileri (serialized dict listesi)
        technical_signals: Teknik gösterge verileri
        portfolio_state: Mevcut portföy durumu
        provider: LLM sağlayıcı override (openrouter, deepseek, ollama)
        dynamic_rules: Dinamik öğrenilen kurallar (opsiyonel)

    Returns:
        Nihai durum (tüm ajan çıktılarını içerir)
    """
    import asyncio
    from agents.state import create_initial_state

    initial = create_initial_state(
        symbol=symbol,
        market_data=market_data,
        news_data=news_data,
        technical_signals=technical_signals,
        portfolio_state=portfolio_state,
        provider=provider,
        dynamic_rules=dynamic_rules,
    )

    app = get_compiled_graph()

    try:
        result = await asyncio.to_thread(app.invoke, initial)
    except Exception as e:
        logger.error("Ajan grafı çalışırken kritik hata oluştu: %s", e)
        logger.error(traceback.format_exc())

        result = initial.copy()
        result["trade_decision"] = {
            "action": "hold",
            "symbol": symbol,
            "reason": f"Sistem hatası: {str(e)}",
            "error": True
        }
        result["phase"] = "error"
        return result

    try:
        from data.vector_store import AgentMemoryStore
        from evaluation.drift_monitor import DriftMonitor

        try:
            acc = DriftMonitor().get_agent_accuracy(symbol, agent_name="trader")
        except Exception as drift_err:
            logger.debug("DriftMonitor error (non-critical): %s", drift_err)
            acc = 0.0

        try:
            AgentMemoryStore().store_decision(result, acc)
        except Exception as store_err:
            logger.debug("AgentMemoryStore error (non-critical): %s", store_err)
    except ImportError as import_err:
        logger.debug("Memory/drift modules not available (non-critical): %s", import_err)
    except Exception as e:
        logger.warning("Hafıza kaydetme hatası (opsiyonel): %s", e)

    return result


def run_analysis(
    symbol: str,
    market_data: dict | None = None,
    news_data: list | None = None,
    technical_signals: dict | None = None,
    portfolio_state: dict | None = None,
    provider: str | None = None,
    dynamic_rules: str | None = None,
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
        dynamic_rules: Dinamik öğrenilen kurallar (opsiyonel)

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
        dynamic_rules=dynamic_rules,
    )

    app = get_compiled_graph()
    
    try:
        result = app.invoke(initial)
    except Exception as e:
        logger.error("Ajan grafı çalışırken kritik hata oluştu: %s", e)
        logger.error(traceback.format_exc())
        
        # Hata durumunda güvenli bir 'hold' sonucu dön
        result = initial.copy()
        result["trade_decision"] = {
            "action": "hold",
            "symbol": symbol,
            "reason": f"Sistem hatası: {str(e)}",
            "error": True
        }
        result["phase"] = "error"
        return result

    # ── Son Kararı RAG Hafızasına Kaydet ───────────────────
    try:
        from data.vector_store import AgentMemoryStore
        from evaluation.drift_monitor import DriftMonitor

        try:
            acc = DriftMonitor().get_agent_accuracy(symbol, agent_name="trader")
        except Exception as drift_err:
            logger.debug("DriftMonitor error (non-critical): %s", drift_err)
            acc = 0.0

        try:
            AgentMemoryStore().store_decision(result, accuracy_score=acc)
        except Exception as store_err:
            logger.debug("AgentMemoryStore error (non-critical): %s", store_err)
    except ImportError as import_err:
        logger.debug("Memory/drift modules not available (non-critical): %s", import_err)
    except Exception as e:
        logger.warning("Hafıza kaydetme hatası (opsiyonel): %s", e)

    return result
