"""
İşlemci Ajan (Trader)
======================
Onaylanmış analiz ve risk değerlendirmesine dayanarak
kesin, uygulanabilir bir alım-satım emri oluşturur.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import TradingState
from config.settings import get_trading_params
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

    # Faz 5: Dinamik kuralları enjekte et
    dynamic_rules = state.get("dynamic_rules", "")
    
    user_msg = f"""## Varlık: {symbol}

## Duyarlılık Analizi
- Sinyal: {sentiment.get("signal", "neutral")}
- Skor: {sentiment.get("sentiment_score", 0):.2f}
- Güven: {sentiment.get("confidence", 0):.2f}

## Araştırma Raporu
- Öneri: {research.get("recommendation", "hold")}
- Trend: {research.get("trend", "neutral")}

## Tartışma Sonucu
- Konsensüs: {debate.get("consensus_score", 0) or 0:.2f}
- Düzeltilmiş sinyal: {debate.get("adjusted_signal", "neutral")}

## KRITIK: Risk Yöneticisi Onayı
RISK ONAYlandı! Aşağıdaki parametrelere göre işlem emri oluştur:
- Onaylanan boyut: {risk.get("approved_size", 0) or 0} USDT
- Stop-loss seviyesi: {(risk.get("stop_loss_level", 0) or 0):.2f}
- Take-profit seviyesi: {(risk.get("take_profit_level", 0) or 0):.2f}

## Teknik Göstergeler
- Güncel fiyat: {tech.get("current_price", 0)}
- ATR: {tech.get("atr_14", 0)}
- RSI: {tech.get("rsi_14", 50)}
- Trend: {tech.get("trend", "neutral")}
"""
    
    # Dinamik kuralları ekle (güçlü sanitization ile)
    if dynamic_rules:
        # Security: Enhanced Dynamic Rules Sanitization (shared utility)
        from utils.dynamic_rules import sanitize_dynamic_rules
        sanitized_rules = sanitize_dynamic_rules(dynamic_rules)
        logger.debug("Dynamic rules sanitized: %d chars (original: %d)", len(sanitized_rules), len(dynamic_rules))
        user_msg += f"\n{sanitized_rules}"
    
    user_msg += f"""

## İşlem Parametreleri
- Emir tipi: {params.execution.default_order_type}
- Komisyon: %{params.execution.commission_pct * 100}
- Kayma (slippage): %{params.execution.slippage_pct * 100}
- Min risk/ödül: {params.limits.min_risk_reward}

## Portföy
{json.dumps(portfolio, indent=2, ensure_ascii=False) if portfolio else "Bilgi yok"}

ÖNEMLI: Risk yöneticisi işlemi ONAYLADI. Yukarıdaki stop-loss ve take-profit seviyelerini kullanarak BUY veya SELL emri oluştur. Sadece ve sadece aşırı risk koşullarında "hold" kararı ver."""

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
            request_timeout=None,
            fallback_on_error=True,
            fallback_value={
                "action": "hold",
                "symbol": symbol,
                "amount": 0,
                "confidence": 0.0,
                "reasoning": "LLM API error - işlem yapılmıyor (güvenlik fallback)",
                "stop_loss": 0,
                "take_profit": 0,
            },
        )
        if isinstance(response, dict):
            trade_decision = response
        else:
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
        # Fallback zaten döndü
        trade_decision = {
            "action": "hold",
            "symbol": symbol,
            "amount": 0,
            "confidence": 0.0,
            "reasoning": f"LLM API error - işlem yapılmıyor: {e}",
        }

    # Varsayılanları doldur
    trade_decision.setdefault("symbol", symbol)
    trade_decision.setdefault("action", "hold")
    trade_decision.setdefault("amount", 0)
    trade_decision.setdefault("confidence", 0)

    # Risk onaylı boyutu aşma kontrolü
    approved_size = float(risk.get("approved_size", 0) or 0)
    if approved_size > 0 and trade_decision.get("amount", 0) > approved_size:
        logger.warning(
            "Trader amount (%.2f) exceeds approved size (%.2f) — capping to approved limit",
            trade_decision["amount"],
            approved_size,
        )
        trade_decision["amount"] = approved_size

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

    _log_decision_trace(state, trade_decision)

    return result




_log_lock = threading.Lock()

def _log_decision_trace(state: dict, trade_decision: dict) -> None:
    try:
        from config.settings import DATA_DIR
        log_dir = DATA_DIR
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "decision_trace.jsonl"
        
        trace = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": state.get("symbol"),
            "action": trade_decision.get("action"),
            "trade_decision": trade_decision,
            "inputs": {
                "sentiment_score": state.get("sentiment", {}).get("sentiment_score"),
                "debate_consensus": state.get("debate_result", {}).get("consensus_score"),
                "risk_decision": state.get("risk_assessment", {}).get("decision"),
                "historical_context": bool(state.get("historical_context")),
            }
        }
        with _log_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Decision trace loglanamadı: {e}")
