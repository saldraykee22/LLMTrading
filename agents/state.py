"""
Ajan Durum Modülü (Trading State)
===================================
LangGraph çoklu ajan sistemi için paylaşımlı durum tanımı.
Tüm ajanlar bu durumu okur ve günceller.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from config.settings import get_trading_params


def _get_max_messages() -> int:
    """Get MAX_MESSAGES from config, fallback to 100."""
    try:
        params = get_trading_params()
        return params.system.max_workers * 20  # Dynamic based on workers
    except Exception:
        return 100


MAX_MESSAGES = 100  # Default, overridden by _get_max_messages() at runtime


def _get_max_messages_runtime() -> int:
    """Get MAX_MESSAGES from config at runtime."""
    try:
        params = get_trading_params()
        return params.system.max_workers * 20
    except Exception:
        return MAX_MESSAGES


def merge_and_trim_messages(left: list[dict], right: list[dict]) -> list[dict]:
    """Merges new messages and ensures the total count does not exceed MAX_MESSAGES."""
    max_msgs = _get_max_messages_runtime()
    combined = (left or []) + (right or [])
    if len(combined) > max_msgs:
        return combined[-max_msgs:]
    return combined


class TradingState(TypedDict):
    messages: Annotated[list[dict], merge_and_trim_messages]
    symbol: str

    market_data: NotRequired[dict[str, Any]]
    news_data: NotRequired[list[dict[str, Any]]]
    technical_signals: NotRequired[dict[str, Any]]

    sentiment: NotRequired[dict[str, Any]]
    research_report: NotRequired[dict[str, Any]]
    debate_result: NotRequired[dict[str, Any]]

    risk_assessment: NotRequired[dict[str, Any]]
    risk_approved: NotRequired[bool]
    trade_decision: NotRequired[dict[str, Any]]

    portfolio_state: NotRequired[dict[str, Any]]

    historical_context: NotRequired[list[dict]]
    agent_accuracy: NotRequired[float]

    iteration: NotRequired[int]
    error: NotRequired[str]
    phase: NotRequired[str]
    provider: NotRequired[str]
    
    # Faz 5: Dinamik öğrenilen kurallar
    dynamic_rules: NotRequired[str]


def create_initial_state(
    symbol: str,
    market_data: dict | None = None,
    news_data: list | None = None,
    technical_signals: dict | None = None,
    portfolio_state: dict | None = None,
    provider: str | None = None,
    dynamic_rules: str | None = None,
) -> TradingState:
    """
    Başlangıç durumu oluşturur.
    
    Args:
        dynamic_rules: Dinamik öğrenilen kurallar (opsiyonel)
    """
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
        historical_context=[],
        agent_accuracy=1.0,
        iteration=0,
        error="",
        phase="init",
        provider=provider or "",
        # Faz 5: Dinamik kurallar
        dynamic_rules=dynamic_rules or "",
    )


def trim_messages(messages: list[dict]) -> list[dict]:
    """Keep only the last MAX_MESSAGES to prevent unbounded growth.

    Should be called at the end of each graph node to cap message list size.
    """
    max_msgs = _get_max_messages_runtime()
    if len(messages) > max_msgs:
        return messages[-max_msgs:]
    return messages
