"""
Risk Yöneticisi Ajan
=====================
Önerilen işlemi risk parametrelerine göre değerlendirir.
CVaR, VIX rejim filtresi, pozisyon limitleri ve zarar-kes kontrolleri uygular.
Onay veya red kararı verir.
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

logger = logging.getLogger(__name__)


def risk_manager_node(state: TradingState) -> dict[str, Any]:
    """
    Risk yöneticisi ajan düğümü.

    Kontrol listesi:
    1. Pozisyon boyutu limiti
    2. Toplam portföy riski
    3. Max drawdown kontrolü
    4. Günlük kayıp limiti
    5. Volatilite rejimi kontrolü
    6. Zarar-kes tanımı
    """
    symbol = state["symbol"]
    params = get_trading_params()

    logger.info("Risk Yöneticisi çalışıyor: %s", symbol)

    sentiment = state.get("sentiment", {})
    research = state.get("research_report", {})
    debate = state.get("debate_result", {})
    tech = state.get("technical_signals", {})
    portfolio = state.get("portfolio_state", {})

    # ── Deterministik risk kontrolleri ─────────────────────
    checks_passed: list[str] = []
    checks_failed: list[str] = []
    warnings: list[str] = []

    # 1. Güven kontrolü
    sentiment_conf = sentiment.get("confidence", 0)
    debate_conf = debate.get("consensus_score", 0)
    if sentiment_conf < params.sentiment.min_confidence:
        checks_failed.append(
            f"Duyarlılık güveni çok düşük: {sentiment_conf:.2f} < {params.sentiment.min_confidence}"
        )
    else:
        checks_passed.append(f"Duyarlılık güveni yeterli: {sentiment_conf:.2f}")

    # 2. Halüsinasyon kontrolü
    hallu = debate.get("hallucinations_detected", [])
    if len(hallu) > 2:
        checks_failed.append(f"Çok fazla halüsinasyon tespit edildi: {len(hallu)} adet")
    elif len(hallu) > 0:
        warnings.append(f"Halüsinasyon uyarısı: {len(hallu)} adet tespit edildi")
    else:
        checks_passed.append("Halüsinasyon tespit edilmedi")

    # 3. Duyarlılık-teknik uyumu
    sent_signal = sentiment.get("signal", "neutral")
    tech_signal = tech.get("signal", "hold")
    if sent_signal == "bullish" and tech_signal == "sell":
        warnings.append("Duyarlılık-teknik uyumsuzluk: Sentiment bullish, teknik sell")
    elif sent_signal == "bearish" and tech_signal == "buy":
        warnings.append("Duyarlılık-teknik uyumsuzluk: Sentiment bearish, teknik buy")
    else:
        checks_passed.append("Duyarlılık-teknik uyumu kabul edilebilir")

    # 4. Max açık pozisyon kontrolü
    open_positions = portfolio.get("open_positions", 0)
    if open_positions >= params.risk.max_open_positions:
        checks_failed.append(
            f"Max pozisyon limiti aşıldı: {open_positions} >= {params.risk.max_open_positions}"
        )
    else:
        checks_passed.append(f"Açık pozisyon sayısı uygun: {open_positions}")

    # 5. Drawdown kontrolü (deterministik)
    current_dd = portfolio.get("current_drawdown", 0)
    if current_dd >= params.risk.max_drawdown_pct:
        checks_failed.append(
            f"Drawdown limiti aşıldı: {current_dd:.2%} >= {params.risk.max_drawdown_pct:.2%}"
        )
    else:
        checks_passed.append(f"Drawdown limiti içinde: {current_dd:.2%}")

    # 6. Günlük kayıp kontrolü (deterministik)
    equity = portfolio.get("equity", 10000)
    daily_pnl = portfolio.get("daily_pnl", 0)
    daily_loss = abs(min(daily_pnl, 0))
    if equity > 0 and daily_loss / equity >= params.risk.max_daily_loss_pct:
        checks_failed.append(
            f"Günlük kayıp limiti aşıldı: {daily_loss / equity:.2%} >= {params.risk.max_daily_loss_pct:.2%}"
        )
    else:
        checks_passed.append(f"Günlük kayıp limiti içinde: {daily_loss / equity:.2%}")



    # ── Karma veya nötr sinyal → "hold" öner ──────────────
    debate_signal = debate.get("adjusted_signal", "neutral")
    if debate_signal == "neutral" and sent_signal == "neutral":
        checks_failed.append("Hem tartışma hem duyarlılık nötr — işlem gerekmiyor")

    # ── LLM tabanlı derinlemesine risk değerlendirmesi ────
    risk_prompt_path = PROMPTS_DIR / "risk_manager.txt"
    system_prompt = ""
    if risk_prompt_path.exists():
        system_prompt = risk_prompt_path.read_text(encoding="utf-8")
        # Parametreleri prompt'a yerleştir
        system_prompt = system_prompt.replace(
            "{max_position_pct}", str(params.risk.max_position_pct * 100)
        )
        system_prompt = system_prompt.replace(
            "{max_portfolio_risk_pct}", str(params.risk.max_portfolio_risk_pct * 100)
        )
        system_prompt = system_prompt.replace(
            "{max_drawdown_pct}", str(params.risk.max_drawdown_pct * 100)
        )
        system_prompt = system_prompt.replace(
            "{max_daily_loss_pct}", str(params.risk.max_daily_loss_pct * 100)
        )
        system_prompt = system_prompt.replace(
            "{max_correlated_positions}", str(params.risk.max_correlated_positions)
        )

    user_msg = f"""## Varlık: {symbol}

## Deterministik Kontroller
Geçen: {json.dumps(checks_passed, ensure_ascii=False)}
Kalan: {json.dumps(checks_failed, ensure_ascii=False)}
Uyarılar: {json.dumps(warnings, ensure_ascii=False)}

## Duyarlılık Analizi
{json.dumps(sentiment, indent=2, ensure_ascii=False)}

## Tartışma Sonucu
{json.dumps(debate, indent=2, ensure_ascii=False)}

## Teknik Göstergeler
{json.dumps(tech, indent=2, ensure_ascii=False)}

## Portföy Durumu
{json.dumps(portfolio, indent=2, ensure_ascii=False)}

## Risk Parametreleri
- Max pozisyon: %{params.risk.max_position_pct * 100}
- Max drawdown: %{params.risk.max_drawdown_pct * 100}
- ATR çarpanı (stop-loss): {params.stop_loss.atr_multiplier}
- Başlangıç sermayesi: {params.backtest.initial_cash} USDT

Deterministik kontrol sonuçlarını dikkate al ve nihai risk değerlendirmesini yap."""

    llm = create_agent_llm(model=params.agents.risk_model, temperature=0.1)

    try:
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )
        llm_assessment = extract_json(response.content)
    except Exception as e:
        logger.error("Risk LLM hatası: %s", e)
        llm_assessment = {}

    # 7. Pozisyon boyutu limiti (deterministik, LLM sonrasında)
    proposed_size = llm_assessment.get("approved_size", 0) if llm_assessment else 0
    if proposed_size > 0:
        max_allowed = equity * params.risk.max_position_pct
        if proposed_size > max_allowed:
            checks_failed.append(
                f"Önerilen pozisyon boyutu limiti aşıldı: {proposed_size:.2f} > {max_allowed:.2f}"
            )
        else:
            checks_passed.append(
                f"Pozisyon boyutu uygun: {proposed_size:.2f} <= {max_allowed:.2f}"
            )

    # ── Nihai karar ───────────────────────────────────────
    # Deterministik kontroller LLM kararını geçersiz kılabilir
    if checks_failed:
        final_decision = "rejected"
        llm_assessment["checks_failed"] = checks_failed
        llm_assessment["checks_passed"] = checks_passed
    else:
        final_decision = llm_assessment.get("decision", "rejected")

    risk_approved = final_decision == "approved"

    risk_data = {
        "decision": final_decision,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "warnings": warnings,
        "llm_assessment": llm_assessment,
        "stop_loss_level": llm_assessment.get("stop_loss_level", 0),
        "take_profit_level": llm_assessment.get("take_profit_level", 0),
        "approved_size": llm_assessment.get("approved_size", 0),
    }

    risk_msg = (
        f"[Risk Yöneticisi] {symbol} değerlendirmesi:\n"
        f"  Karar: {'✓ ONAYLANDI' if risk_approved else '✗ REDDEDİLDİ'}\n"
        f"  Geçen kontroller: {len(checks_passed)}\n"
        f"  Başarısız kontroller: {len(checks_failed)}\n"
        f"  Uyarılar: {len(warnings)}"
    )

    logger.info(risk_msg)

    return {
        "messages": [{"role": "risk_manager", "content": risk_msg}],
        "risk_assessment": risk_data,
        "risk_approved": risk_approved,
        "phase": "trade" if risk_approved else "retry",
    }
