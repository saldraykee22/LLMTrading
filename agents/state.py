"""
Ajan Durum Modülü (Trading State)
===================================
LangGraph çoklu ajan sistemi için paylaşımlı durum tanımı.
Tüm ajanlar bu durumu okur ve günceller.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, NotRequired, TypedDict

MAX_MESSAGES = 50  # Max messages to keep in state


class TradingState(TypedDict):
    messages: Annotated[list[dict], operator.add]
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
        historical_context=[],
        agent_accuracy=1.0,
        iteration=0,
        error="",
        phase="init",
        provider=provider or "",
    )


def trim_messages(messages: list[dict]) -> list[dict]:
    """Keep only the last MAX_MESSAGES to prevent unbounded growth."""
    if len(messages) > MAX_MESSAGES:
        return messages[-MAX_MESSAGES:]
    return messages
