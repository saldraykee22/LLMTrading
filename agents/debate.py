"""
Bull vs Bear Tartışma Modülü (Multi-Agent Debate)
===================================================
Halüsinasyonları filtrelemek için iki karşıt ajan tartıştırılır:
- Bull Agent: Yükseliş senaryosunu savunur
- Bear Agent: Düşüş senaryosunu savunur
- Moderator: Tartışmayı sentezler ve nihai konsensüs skoru üretir
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import TradingState
from config.settings import get_trading_params
from models.sentiment_analyzer import create_agent_llm
from utils.json_utils import extract_json
from utils.llm_retry import invoke_with_retry

logger = logging.getLogger(__name__)

BULL_SYSTEM = """Sen finansal piyasalarda yükseliş (bullish) senaryoları savunan bir analistsin.
Görevin, verilen varlık için YÜKSELME gerekçelerini güçlü argümanlarla sunmaktır.
ANCAK gerçek verilere dayanmalısın — uydurma veya abartılı iddialar YASAK.
Sadece kanıta dayalı argümanlar sun. Zayıf argümanlarını kabul et.

Çıktı Formatı (JSON):
```json
{
    "action": "bullish",
    "confidence": 0.0,
    "key_points": ["..."],
    "supporting_data": ["..."],
    "risks_acknowledged": ["..."],
    "reasoning": "..."
}
```
- confidence: 0.0-1.0 arası yükseliş güveni
- key_points: En güçlü 3-5 yükseliş argümanı
- supporting_data: Argümanları destekleyen somut veriler
- risks_acknowledged: Kabul ettiğin riskler
- reasoning: Kısa özet
"""

BEAR_SYSTEM = """Sen finansal piyasalarda düşüş (bearish) senaryoları savunan bir analistsin.
Görevin, verilen varlık için DÜŞÜŞ risklerini güçlü argümanlarla sunmaktır.
ANCAK gerçek verilere dayanmalısın — uydurma veya abartılı iddialar YASAK.
Sadece kanıta dayalı argümanlar sun. Zayıf argümanlarını kabul et.

Çıktı Formatı (JSON):
```json
{
    "action": "bearish",
    "confidence": 0.0,
    "key_points": ["..."],
    "supporting_data": ["..."],
    "risks_acknowledged": ["..."],
    "reasoning": "..."
}
```
- confidence: 0.0-1.0 arası düşüş güveni
- key_points: En güçlü 3-5 düşüş argümanı
- supporting_data: Argümanları destekleyen somut veriler
- risks_acknowledged: Kabul ettiğin riskler
- reasoning: Kısa özet
"""

MODERATOR_SYSTEM = """Sen tarafsız bir finansal tartışma moderatörüsün.
İki analistin (Bull ve Bear) argümanlarını değerlendir.

Görevin:
1. Her iki tarafın argümanlarının mantıksal tutarlılığını kontrol et
2. Dayanaklarla desteklenmeyen iddiaları (halüsinasyonları) tespit et
3. Daha güçlü argümanlara sahip tarafı belirle
4. Nihai konsensüs skoru üret

Çıktı Formatı (JSON):
```json
{
    "winner": "bull|bear|draw",
    "consensus_score": 0.0,
    "bull_strength": 0.0,
    "bear_strength": 0.0,
    "hallucinations_detected": ["..."],
    "key_arguments": {
        "bull": ["..."],
        "bear": ["..."]
    },
    "moderator_reasoning": "...",
    "adjusted_signal": "bullish|bearish|neutral",
    "confidence_adjustment": 0.0
}
```
consensus_score: -1.0 (kesin düşüş) ile 1.0 (kesin yükseliş) arası
"""


def debate_node(state: TradingState) -> dict[str, Any]:
    """
    Bull vs Bear tartışma düğümü.

    Süreç:
    1. Bull ajan → yükseliş argümanları
    2. Bear ajan → düşüş argümanları
    3. (Opsiyonel) 2. tur: karşılıklı yanıtlar
    4. Moderator → sentez ve konsensüs
    """
    symbol = state["symbol"]
    params = get_trading_params()
    max_rounds = params.agents.max_debate_rounds
    provider = state.get("provider") or None

    logger.info("Bull vs Bear tartışması başlıyor: %s (%d tur)", symbol, max_rounds)

    # Bağlam hazırla
    sentiment = state.get("sentiment", {})
    research = state.get("research_report", {})
    tech = state.get("technical_signals", {})

    context = f"""## Varlık: {symbol}

## Araştırma Raporu Özeti
- Duyarlılık skoru: {sentiment.get("sentiment_score", 0):.2f}
- Sinyal: {sentiment.get("signal", "neutral")}
- Öneri: {research.get("recommendation", "hold")}
- Anahtar faktörler: {sentiment.get("key_factors", [])}

## Teknik Göstergeler
{json.dumps(tech, indent=2, ensure_ascii=False) if tech else "Mevcut değil"}
"""

    llm = create_agent_llm(
        provider=provider, model=params.agents.analyst_model, temperature=0.3
    )

    debate_log: list[str] = []

    # ── Tur 1: İlk argümanlar ────────────────────────────
    # Bull
    try:
        bull_resp = invoke_with_retry(
            llm.invoke,
            [
                SystemMessage(content=BULL_SYSTEM),
                HumanMessage(
                    content=f"{context}\n\nBu varlık için yükseliş tezini sun. Somut verilerle destekle."
                ),
            ],
            max_tokens=params.limits.max_tokens_debate,
            response_format={"type": "json_object"},
            max_retries=2,
            base_delay=2.0,
            request_timeout=None,
            fallback_on_error=True,
            fallback_value={
                "action": "bullish",
                "confidence": 0.3,
                "key_points": ["LLM API error - yükseliş argümanı oluşturulamadı"],
                "supporting_data": [],
                "risks_acknowledged": ["API fallback"],
                "reasoning": "Fallback due to LLM API error"
            },
        )
        bull_args = bull_resp.content
    except Exception as e:
        logger.error("Bull ajan hatası: %s", e)
        bull_args = json.dumps({
            "action": "bullish",
            "confidence": 0.3,
            "key_points": ["LLM fallback"],
            "reasoning": "API error"
        })

    # Bear
    try:
        bear_resp = invoke_with_retry(
            llm.invoke,
            [
                SystemMessage(content=BEAR_SYSTEM),
                HumanMessage(
                    content=f"{context}\n\nBu varlık için düşüş risklerini sun. Somut verilerle destekle."
                ),
            ],
            max_tokens=params.limits.max_tokens_debate,
            response_format={"type": "json_object"},
            max_retries=2,
            base_delay=2.0,
            request_timeout=None,
            fallback_on_error=True,
            fallback_value={
                "action": "bearish",
                "confidence": 0.3,
                "key_points": ["LLM API error - düşüş argümanı oluşturulamadı"],
                "supporting_data": [],
                "risks_acknowledged": ["API fallback"],
                "reasoning": "Fallback due to LLM API error"
            },
        )
        bear_args = bear_resp.content
    except Exception as e:
        logger.error("Bear ajan hatası: %s", e)
        bear_args = json.dumps({
            "action": "bearish",
            "confidence": 0.3,
            "key_points": ["LLM fallback"],
            "reasoning": "API error"
        })

    debate_log.append(
        f"BULL (Tur 1): {bull_args[: params.limits.debate_truncate_chars]}"
    )
    debate_log.append(
        f"BEAR (Tur 1): {bear_args[: params.limits.debate_truncate_chars]}"
    )

    # ── Tur 2: Karşılıklı yanıtlar (max_rounds > 1 ise) ──
    if max_rounds >= 2:
        try:
            bull_rebuttal = invoke_with_retry(
                llm.invoke,
                [
                    SystemMessage(content=BULL_SYSTEM),
                    HumanMessage(
                        content=f"{context}\n\nBear tarafının argümanları:\n{bear_args}\n\n"
                        "Bu argümanlara yanıt ver ve yükseliş tezini güçlendir."
                    ),
                ],
                max_tokens=params.limits.max_tokens_debate,
                response_format={"type": "json_object"},
                max_retries=2,
                base_delay=2.0,
                request_timeout=None,
                fallback_on_error=True,
                fallback_value={
                    "action": "bullish",
                    "confidence": 0.3,
                    "key_points": ["LLM API error - yanıt oluşturulamadı"],
                    "reasoning": "Fallback"
                },
            )
            bull_args += "\n\n[Yanıt]: " + bull_rebuttal.content
        except Exception as e:
            logger.warning("Bull rebuttal hatası: %s", e)
            bull_args += "\n\n[Yanıt]: Bull yanıtı oluşturulamadı (fallback)."

        try:
            bear_rebuttal = invoke_with_retry(
                llm.invoke,
                [
                    SystemMessage(content=BEAR_SYSTEM),
                    HumanMessage(
                        content=f"{context}\n\nBull tarafının argümanları:\n{bull_args[: params.limits.debate_rebuttal_truncate_chars]}\n\n"
                        "Bu argümanlara yanıt ver ve düşüş risklerini güçlendir."
                    ),
                ],
                max_tokens=params.limits.max_tokens_debate,
                response_format={"type": "json_object"},
                max_retries=2,
                base_delay=2.0,
                request_timeout=None,
                fallback_on_error=True,
                fallback_value={
                    "action": "bearish",
                    "confidence": 0.3,
                    "key_points": ["LLM API error - yanıt oluşturulamadı"],
                    "reasoning": "Fallback"
                },
            )
            bear_args += "\n\n[Yanıt]: " + bear_rebuttal.content
        except Exception as e:
            logger.warning("Bear rebuttal hatası: %s", e)
            bear_args += "\n\n[Yanıt]: Bear yanıtı oluşturulamadı (fallback)."

    # ── Moderator ─────────────────────────────────────────
    from agents.prompt_evolver import PromptEvolver

    evolver = PromptEvolver()
    moderator_system = evolver.get_current_prompt("debate_moderator")
    if not moderator_system:
        moderator_system = MODERATOR_SYSTEM

    moderator_input = f"""{context}

## Bull Tarafının Argümanları
{bull_args[: params.limits.moderator_truncate_chars]}

## Bear Tarafının Argümanları
{bear_args[: params.limits.moderator_truncate_chars]}

Tartışmayı değerlendir ve JSON formatında konsensüs raporu üret."""

    try:
        mod_resp = invoke_with_retry(
            llm.invoke,
            [
                SystemMessage(content=moderator_system),
                HumanMessage(content=moderator_input),
            ],
            max_tokens=params.limits.max_tokens_moderator,
            response_format={"type": "json_object"},
            max_retries=2,
            base_delay=2.0,
            request_timeout=None,
            fallback_on_error=True,
            fallback_value={
                "winner": "draw",
                "consensus_score": 0.0,
                "adjusted_signal": "neutral",
                "moderator_reasoning": "LLM API error - tartışma sonuçsuz (fallback)",
                "hallucinations_detected": [],
                "bull_strength": 0.3,
                "bear_strength": 0.3,
                "confidence_adjustment": 0.0
            },
        )
        debate_result = extract_json(mod_resp.content)
        if debate_result.get("__parse_error__"):
            logger.warning(
                "Moderator LLM JSON parse hatası: %s",
                debate_result.get("__raw_text__", "")[:200],
            )
            debate_result = {
                "winner": "draw",
                "consensus_score": 0.0,
                "adjusted_signal": "neutral",
                "moderator_reasoning": f"Moderator çıktı parse edilemedi: {debate_result.get('__raw_text__', '')[:200]}",
                "parse_error": True,
            }
    except Exception as e:
        logger.error("Moderator hatası: %s", e)
        # Fallback zaten döndü
        debate_result = {
            "winner": "draw",
            "consensus_score": 0.0,
            "adjusted_signal": "neutral",
            "moderator_reasoning": f"LLM API error - tartışma sonuçsuz: {e}",
        }

    # Varsayılanları doldur
    debate_result.setdefault("winner", "draw")
    debate_result.setdefault("consensus_score", 0.0)
    debate_result.setdefault("adjusted_signal", "neutral")
    debate_result.setdefault("hallucinations_detected", [])

    hallu_count = len(debate_result.get("hallucinations_detected", []))

    debate_msg = (
        f"[Tartışma] {symbol} sonuç:\n"
        f"  Kazanan: {debate_result['winner']}\n"
        f"  Konsensüs: {debate_result['consensus_score']:.2f}\n"
        f"  Düzeltilmiş sinyal: {debate_result['adjusted_signal']}\n"
        f"  Tespit edilen halüsinasyon: {hallu_count}"
    )

    logger.info(debate_msg)

    return {
        "messages": [{"role": "debate", "content": debate_msg}],
        "debate_result": debate_result,
        "phase": "risk",
    }
