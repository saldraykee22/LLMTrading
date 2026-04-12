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
from models.sentiment_analyzer import create_agent_llm
from utils.json_utils import extract_json
from utils.llm_retry import invoke_with_retry

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
    provider = state.get("provider") or None

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
    from agents.prompt_evolver import PromptEvolver

    evolver = PromptEvolver()
    system_prompt = evolver.get_current_prompt("trader")

    sentiment = state.get("sentiment", {})
    research = state.get("research_report", {})
    debate = state.get("debate_result", {})
    risk = state.get("risk_assessment", {})
    tech = state.get("technical_signals", {})
    portfolio = state.get("portfolio_state", {})

    user_msg = f"""## Varlık: {symbol}

## Duyarlılık Analizi
- Sinyal: {sentiment.get("signal", "neutral")}
- Skor: {sentiment.get("sentiment_score", 0):.2f}
- Güven: {sentiment.get("confidence", 0):.2f}

## Araştırma Raporu
- Öneri: {research.get("recommendation", "hold")}
- Trend: {research.get("trend", "neutral")}

## Tartışma Sonucu
- Konsensüs: {debate.get("consensus_score", 0):.2f}
- Düzeltilmiş sinyal: {debate.get("adjusted_signal", "neutral")}

## Risk Onayı
- Karar: {risk.get("decision", "N/A")}
- Önerilen boyut: {risk.get("approved_size", 0)}
- Stop-loss: {risk.get("stop_loss_level", 0)}
- Take-profit: {risk.get("take_profit_level", 0)}

## Teknik Göstergeler
- Güncel fiyat: {tech.get("current_price", 0)}
- ATR: {tech.get("atr_14", 0)}
- RSI: {tech.get("rsi_14", 50)}
- Trend: {tech.get("trend", "neutral")}

## Portföy
{json.dumps(portfolio, indent=2, ensure_ascii=False) if portfolio else "Bilgi yok"}

## İşlem Parametreleri
- Emir tipi: {params.execution.default_order_type}
- Komisyon: %{params.execution.commission_pct * 100}
- Kayma (slippage): %{params.execution.slippage_pct * 100}
- Min risk/ödül: {params.limits.min_risk_reward}

Lütfen kesin bir alım-satım emri oluştur veya "hold" kararı ver."""

    llm = create_agent_llm(
        provider=provider,
        model=params.agents.trader_model,
        temperature=0.1,
        max_tokens=params.limits.max_tokens_trader,
    )

    try:
        response = invoke_with_retry(
            llm.invoke,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ],
            max_tokens=params.limits.max_tokens_trader,
            response_format={"type": "json_object"},
            max_retries=3,
            base_delay=2.0,
        )
        trade_decision = extract_json(response.content)
        if trade_decision.get("__parse_error__"):
            logger.warning(
                "Trader LLM JSON parse hatası: %s",
                trade_decision.get("__raw_text__", "")[:200],
            )
            trade_decision = {
                "action": "hold",
                "symbol": symbol,
                "reasoning": f"LLM çıktı parse edilemedi: {trade_decision.get('__raw_text__', '')[:200]}",
                "parse_error": True,
            }
    except Exception as e:
        logger.error("İşlemci LLM hatası: %s", e)
        trade_decision = {
            "action": "hold",
            "symbol": symbol,
            "reasoning": f"İşlem emri oluşturulamadı: {e}",
            "error": f"LLM Timeout veya API Hatası: {e}",
        }

    # Varsayılanları doldur
    trade_decision.setdefault("symbol", symbol)
    trade_decision.setdefault("action", "hold")
    trade_decision.setdefault("amount", 0)
    trade_decision.setdefault("confidence", 0)

    rl_recommendation = state.get("rl_recommendation", {})
    rl_confidence = state.get("rl_confidence", 0.0)

    if rl_recommendation and rl_confidence > 0.0:
        trade_decision = _blend_llm_with_rl(
            trade_decision, rl_recommendation, rl_confidence
        )

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

    result = {
        "messages": [{"role": "trader", "content": trade_msg}],
        "trade_decision": trade_decision,
        "phase": "complete",
    }

    if "error" in trade_decision:
        result["error"] = trade_decision["error"]

    return result


def _blend_llm_with_rl(
    llm_decision: dict,
    rl_recommendation: dict,
    rl_confidence: float,
) -> dict:
    rl_action = rl_recommendation.get("rl_action", "hold")
    rl_amount_pct = rl_recommendation.get("rl_amount_pct", 0.0)

    if rl_confidence > 0.7:
        rl_weight = 0.6
        llm_weight = 0.4
    elif rl_confidence < 0.4:
        return llm_decision
    else:
        rl_weight = 0.5
        llm_weight = 0.5

    llm_action = llm_decision.get("action", "hold")
    llm_amount = llm_decision.get("amount", 0)

    action_priority = {
        "buy_large": 4,
        "buy_medium": 3,
        "buy_small": 2,
        "hold": 1,
        "sell": 0,
    }

    llm_action_mapped = llm_action
    if llm_action == "buy":
        llm_action_mapped = "buy_medium"

    llm_score = action_priority.get(llm_action_mapped, 1)
    rl_score = action_priority.get(rl_action, 1)

    blended_score = llm_score * llm_weight + rl_score * rl_weight

    portfolio_equity = llm_decision.get("portfolio_equity", 10000.0)
    rl_amount_absolute = rl_amount_pct * portfolio_equity

    if blended_score >= 3.0:
        final_action = "buy"
        final_amount = llm_amount * llm_weight + rl_amount_absolute * rl_weight
    elif blended_score >= 2.0:
        final_action = "buy"
        final_amount = (llm_amount * llm_weight + rl_amount_absolute * rl_weight) * 0.7
    elif blended_score >= 1.5:
        final_action = "buy"
        final_amount = (llm_amount * llm_weight + rl_amount_absolute * rl_weight) * 0.4
    elif blended_score <= 0.3:
        final_action = "sell"
        final_amount = llm_amount
    else:
        final_action = "hold"
        final_amount = 0

    blended_confidence = (
        llm_decision.get("confidence", 0.5) * llm_weight + rl_confidence * rl_weight
    )

    llm_reasoning = llm_decision.get("reasoning", "")
    rl_reasoning = rl_recommendation.get("rl_reasoning", "")
    blended_reasoning = (
        f"LLM: {llm_reasoning} | RL ({rl_confidence:.2f}): {rl_reasoning}"
    )

    blended = dict(llm_decision)
    blended["action"] = final_action
    blended["amount"] = round(final_amount, 6)
    blended["confidence"] = round(blended_confidence, 4)
    blended["reasoning"] = blended_reasoning
    blended["rl_influenced"] = True
    blended["rl_confidence"] = rl_confidence

    return blended
