"""
İşlemci Ajan (Trader)
======================
Onaylanmış analiz ve risk değerlendirmesine dayanarak
kesin, uygulanabilir bir alım-satım emri oluşturur.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import TradingState
from config.settings import PROMPTS_DIR, get_trading_params
from models.sentiment_analyzer import _extract_json, create_agent_llm

logger = logging.getLogger(__name__)


def trader_node(state: TradingState) -> dict[str, Any]:
    """
    İşlemci ajan düğümü.

    Risk onaylıysa → yapılandırılmış alım-satım emri üretir.
    Risk onaylı değilse → "hold" kararı döndürür.
    """
    symbol = state["symbol"]
    params = get_trading_params()
    risk_approved = state.get("risk_approved", False)

    logger.info("İşlemci Ajan çalışıyor: %s (onay: %s)", symbol, risk_approved)

    if not risk_approved:
        hold_decision = {
            "action": "hold",
            "symbol": symbol,
            "reasoning": "Risk yöneticisi tarafından reddedildi",
            "amount": 0,
            "confidence": 0,
        }
        return {
            "messages": [
                {
                    "role": "trader",
                    "content": f"[İşlemci] {symbol}: BEKLE — Risk onayı yok",
                }
            ],
            "trade_decision": hold_decision,
            "phase": "complete",
        }

    # ── LLM ile emir oluşturma ────────────────────────────
    trader_prompt_path = PROMPTS_DIR / "trader.txt"
    system_prompt = ""
    if trader_prompt_path.exists():
        system_prompt = trader_prompt_path.read_text(encoding="utf-8")

    sentiment = state.get("sentiment", {})
    research = state.get("research_report", {})
    debate = state.get("debate_result", {})
    risk = state.get("risk_assessment", {})
    tech = state.get("technical_signals", {})
    portfolio = state.get("portfolio_state", {})

    user_msg = f"""## Varlık: {symbol}

## Duyarlılık Analizi
- Sinyal: {sentiment.get('signal', 'neutral')}
- Skor: {sentiment.get('sentiment_score', 0):.2f}
- Güven: {sentiment.get('confidence', 0):.2f}

## Araştırma Raporu
- Öneri: {research.get('recommendation', 'hold')}
- Trend: {research.get('trend', 'neutral')}

## Tartışma Sonucu
- Konsensüs: {debate.get('consensus_score', 0):.2f}
- Düzeltilmiş sinyal: {debate.get('adjusted_signal', 'neutral')}

## Risk Onayı
- Karar: {risk.get('decision', 'N/A')}
- Önerilen boyut: {risk.get('approved_size', 0)}
- Stop-loss: {risk.get('stop_loss_level', 0)}
- Take-profit: {risk.get('take_profit_level', 0)}

## Teknik Göstergeler
- Güncel fiyat: {tech.get('current_price', 0)}
- ATR: {tech.get('atr_14', 0)}
- RSI: {tech.get('rsi_14', 50)}
- Trend: {tech.get('trend', 'neutral')}

## Portföy
{json.dumps(portfolio, indent=2, ensure_ascii=False) if portfolio else 'Bilgi yok'}

## İşlem Parametreleri
- Emir tipi: {params.execution.default_order_type}
- Komisyon: %{params.execution.commission_pct * 100}
- Kayma (slippage): %{params.execution.slippage_pct * 100}
- Min risk/ödül: 1.5

Lütfen kesin bir alım-satım emri oluştur veya "hold" kararı ver."""

    llm = create_agent_llm(model=params.agents.trader_model, temperature=0.1)

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])
        trade_decision = _extract_json(response.content)
    except Exception as e:
        logger.error("İşlemci LLM hatası: %s", e)
        trade_decision = {
            "action": "hold",
            "symbol": symbol,
            "reasoning": f"İşlem emri oluşturulamadı: {e}",
        }

    # Varsayılanları doldur
    trade_decision.setdefault("symbol", symbol)
    trade_decision.setdefault("action", "hold")
    trade_decision.setdefault("amount", 0)
    trade_decision.setdefault("confidence", 0)

    action = trade_decision.get("action", "hold")
    amount = trade_decision.get("amount", 0)
    entry = trade_decision.get("entry_price", 0)
    sl = trade_decision.get("stop_loss", 0)
    tp = trade_decision.get("take_profit", 0)

    trade_msg = (
        f"[İşlemci] {symbol} kararı:\n"
        f"  Aksiyon: {action.upper()}\n"
        f"  Miktar: {amount}\n"
        f"  Giriş: {entry}\n"
        f"  Stop-Loss: {sl}\n"
        f"  Take-Profit: {tp}\n"
        f"  Güven: {trade_decision.get('confidence', 0):.2f}"
    )

    logger.info(trade_msg)

    return {
        "messages": [{"role": "trader", "content": trade_msg}],
        "trade_decision": trade_decision,
        "phase": "complete",
    }
