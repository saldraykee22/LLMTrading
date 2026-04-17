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
from utils.llm_retry import invoke_with_retry

logger = logging.getLogger(__name__)


_drift_monitor_instance = None

def _get_drift_monitor():
    global _drift_monitor_instance
    if _drift_monitor_instance is None:
        from evaluation.drift_monitor import DriftMonitor
        _drift_monitor_instance = DriftMonitor()
    return _drift_monitor_instance

def risk_manager_node(state: TradingState) -> dict[str, Any]:
    symbol = state["symbol"]
    params = get_trading_params()
    provider = state.get("provider") or None

    logger.info("Risk Yöneticisi çalışıyor: %s", symbol)

    sentiment = state.get("sentiment", {})
    research = state.get("research_report", {})
    debate = state.get("debate_result", {})
    tech = state.get("technical_signals", {})
    portfolio = state.get("portfolio_state", {})

    checks_passed: list[str] = []
    checks_failed: list[str] = []
    warnings: list[str] = []
    critical_failed: list[str] = []

    sentiment_conf = sentiment.get("confidence", 0)
    debate_conf = debate.get("consensus_score", 0)
    if sentiment_conf < params.sentiment.min_confidence:
        checks_failed.append(
            f"Duyarlılık güveni çok düşük: {sentiment_conf:.2f} < {params.sentiment.min_confidence}"
        )
    else:
        checks_passed.append(f"Duyarlılık güveni yeterli: {sentiment_conf:.2f}")

    hallu = debate.get("hallucinations_detected", [])
    if len(hallu) > 2:
        checks_failed.append(f"Çok fazla halüsinasyon tespit edildi: {len(hallu)} adet")
    elif len(hallu) > 0:
        warnings.append(f"Halüsinasyon uyarısı: {len(hallu)} adet tespit edildi")
    else:
        checks_passed.append("Halüsinasyon tespit edilmedi")

    sent_signal = sentiment.get("signal", "neutral")
    tech_signal = tech.get("signal", "hold")
    if sent_signal == "bullish" and tech_signal == "sell":
        warnings.append("Duyarlılık-teknik uyumsuzluk: Sentiment bullish, teknik sell")
    elif sent_signal == "bearish" and tech_signal == "buy":
        warnings.append("Duyarlılık-teknik uyumsuzluk: Sentiment bearish, teknik buy")
    else:
        checks_passed.append("Duyarlılık-teknik uyumu kabul edilebilir")

    open_positions = portfolio.get("open_positions", 0)
    if open_positions >= params.risk.max_open_positions:
        critical_failed.append(
            f"Max pozisyon limiti aşıldı: {open_positions} >= {params.risk.max_open_positions}"
        )
    else:
        checks_passed.append(f"Açık pozisyon sayısı uygun: {open_positions}")

    current_dd = portfolio.get("current_drawdown", 0)
    if current_dd >= params.risk.max_drawdown_pct:
        critical_failed.append(
            f"Drawdown limiti aşıldı: {current_dd:.2%} >= {params.risk.max_drawdown_pct:.2%}"
        )
    else:
        checks_passed.append(f"Drawdown limiti içinde: {current_dd:.2%}")

    # Rejim filtresi kontrolü
    try:
        from risk.regime_filter import RegimeFilter
        vix_data = state.get("vix_data")
        if vix_data is not None and not vix_data.empty:
            regime_filter = RegimeFilter()
            regime = regime_filter.update(vix_data)
            if regime_filter.should_halt_trading():
                critical_failed.append(
                    f"Yüksek volatilite rejimi: {regime.value}"
                )
            else:
                checks_passed.append(f"Piyasa rejimi uygun: {regime.value}")
    except Exception as e:
        warnings.append(f"Rejim filtresi hatası: {e}")

    # Crypto Fear & Greed kontrolü
    try:
        from risk.regime_filter import CryptoFearGreedFilter
        fear_greed_index = state.get("fear_greed_index")
        if fear_greed_index is not None:
            fg_filter = CryptoFearGreedFilter()
            classification = fg_filter.update(fear_greed_index)
            if fg_filter.should_reduce_exposure():
                warnings.append(
                    f"Fear & Greed extremum: {classification} (index: {fear_greed_index})"
                )
            else:
                checks_passed.append(f"Fear & Greed seviyesi normal: {classification}")
    except Exception as e:
        warnings.append(f"Fear & Greed filtresi hatası: {e}")

    try:
        drift_monitor = _get_drift_monitor()
        acc = drift_monitor.get_agent_accuracy(symbol)
        if acc < 0.40:
            checks_failed.append(
                f"LLM İsabet Oranı Çok Düşük (Drift): %{acc * 100:.1f} < %40"
            )
        elif acc < 0.60:
            warnings.append(f"LLM isabet oranı düşüyor: %{acc * 100:.1f}")
        else:
            checks_passed.append(f"LLM İsabet Oranı iyi: %{acc * 100:.1f}")
    except Exception as e:
        warnings.append(f"Drift monitor hatası: {e}")

    equity = portfolio.get("equity", 10000)
    daily_pnl = portfolio.get("daily_pnl", 0)
    daily_loss = abs(min(daily_pnl, 0))
    if equity > 0 and daily_loss / equity >= params.risk.max_daily_loss_pct:
        critical_failed.append(
            f"Günlük kayıp limiti aşıldı: {daily_loss / equity:.2%} >= {params.risk.max_daily_loss_pct:.2%}"
        )
    else:
        checks_passed.append(f"Günlük kayıp limiti içinde: {daily_loss / equity:.2%}")

    debate_signal = debate.get("adjusted_signal", "neutral")
    if debate_signal == "neutral" and sent_signal == "neutral":
        checks_failed.append("Hem tartışma hem duyarlılık nötr — işlem gerekmiyor")

    if critical_failed:
        checks_failed.extend(critical_failed)
        risk_data = {
            "decision": "rejected",
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "warnings": warnings,
            "llm_assessment": {},
            "stop_loss_level": 0,
            "take_profit_level": 0,
            "approved_size": 0,
        }

        risk_msg = (
            f"[Risk Yöneticisi] {symbol} değerlendirmesi:\n"
            f"  Karar: REDDEDİLDİ (kritik kontrol)\n"
            f"  Geçen kontroller: {len(checks_passed)}\n"
            f"  Başarısız kontroller: {len(checks_failed)}\n"
            f"  Uyarılar: {len(warnings)}"
        )

        logger.info(risk_msg)

        return {
            "messages": [{"role": "risk_manager", "content": risk_msg}],
            "risk_assessment": risk_data,
            "risk_approved": False,
            "phase": "analysis",
        }

    if checks_failed:
        risk_data = {
            "decision": "rejected",
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "warnings": warnings,
            "llm_assessment": {},
            "stop_loss_level": 0,
            "take_profit_level": 0,
            "approved_size": 0,
        }

        risk_msg = (
            f"[Risk Yöneticisi] {symbol} değerlendirmesi:\n"
            f"  Karar: REDDEDİLDİ (deterministik kontrol)\n"
            f"  Geçen kontroller: {len(checks_passed)}\n"
            f"  Başarısız kontroller: {len(checks_failed)}\n"
            f"  Uyarılar: {len(warnings)}"
        )

        logger.info(risk_msg)

        return {
            "messages": [{"role": "risk_manager", "content": risk_msg}],
            "risk_assessment": risk_data,
            "risk_approved": False,
            "phase": "analysis",
        }

    from agents.prompt_evolver import PromptEvolver

    evolver = PromptEvolver()
    system_prompt = evolver.get_current_prompt("risk_manager")
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

    max_allowed = equity * params.risk.max_position_pct

    user_msg = f"""## Varlık: {symbol}

## KESİN KURALLAR (Aşılamaz Limitler)
- Max pozisyon boyutu: {max_allowed:.2f} USDT (approved_size BU DEĞERİ AŞAMAZ)
- Max drawdown: %{params.risk.max_drawdown_pct * 100}
- Günlük kayıp limiti: %{params.risk.max_daily_loss_pct * 100}
- ATR çarpanı (stop-loss): {params.stop_loss.atr_multiplier}
- Başlangıç sermayesi: {params.backtest.initial_cash} USDT

## Deterministik Kontroller
Geçen: {json.dumps(checks_passed, ensure_ascii=False)}
Uyarılar: {json.dumps(warnings, ensure_ascii=False)}

## Araştırma Raporu
{json.dumps(research, indent=2, ensure_ascii=False)}

## Duyarlılık Analizi
{json.dumps(sentiment, indent=2, ensure_ascii=False)}

## Tartışma Sonucu
{json.dumps(debate, indent=2, ensure_ascii=False)}

## Teknik Göstergeler
{json.dumps(tech, indent=2, ensure_ascii=False)}

## Portföy Durumu
{json.dumps(portfolio, indent=2, ensure_ascii=False)}

Deterministik kontrollerin tamamı geçti. KESİN KURALLAR'I dikkate al. approved_size değeri {max_allowed:.2f} USDT'yi ASLA aşmamalı. Nihai risk değerlendirmesini yap."""

    llm = create_agent_llm(
        provider=provider,
        model=params.agents.risk_model,
        temperature=0.1,
        max_tokens=params.limits.max_tokens_risk,
    )

    try:
        response = invoke_with_retry(
            llm.invoke,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ],
            max_tokens=params.limits.max_tokens_risk,
            response_format={"type": "json_object"},
            max_retries=3,
            base_delay=2.0,
            request_timeout=60,
        )
        llm_assessment = extract_json(response.content)
        if llm_assessment.get("__parse_error__"):
            logger.warning(
                "Risk LLM JSON parse hatası: %s",
                llm_assessment.get("__raw_text__", "")[:200],
            )
            llm_assessment = {}
    except Exception as e:
        logger.error("Risk LLM hatası: %s", e)
        llm_assessment = {}

    proposed_size = llm_assessment.get("approved_size", 0) if llm_assessment else 0
    if proposed_size > 0:
        epsilon = 0.01
        if proposed_size > max_allowed + epsilon:
            logger.warning(
                "LLM max_allowed limiti aştı: %.2f > %.2f — otomatik reddedildi",
                proposed_size,
                max_allowed,
            )
            checks_failed.append(
                f"LLM önerilen pozisyon boyutu limiti aştı: {proposed_size:.2f} > {max_allowed:.2f}"
            )
            final_decision = "rejected"
        else:
            checks_passed.append(
                f"Pozisyon boyutu uygun: {proposed_size:.2f} <= {max_allowed:.2f}"
            )
            final_decision = llm_assessment.get("decision", "approved")
    else:
        if not llm_assessment:
            logger.warning("Risk LLM boş yanıt döndü, güvenlik nedeniyle reddedildi")
            final_decision = "rejected"
        else:
            final_decision = llm_assessment.get("decision", "approved")

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
        "phase": "trade" if risk_approved else "analysis",
    }
