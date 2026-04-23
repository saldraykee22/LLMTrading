"""
Ensemble LLM Voter
====================
Runs multiple LLM models in parallel and aggregates their responses
via majority vote (categorical) and weighted average (numerical).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from config.settings import LLMProvider, get_trading_params
from models.sentiment_analyzer import create_llm
from utils.json_utils import extract_json

logger = logging.getLogger(__name__)


class EnsembleVoter:
    """Runs multiple LLM models in parallel and votes on the result."""

    def __init__(
        self,
        models: list[str] | None = None,
        min_consensus: float | None = None,
    ) -> None:
        params = get_trading_params()
        self.models = models or params.agents.ensemble_models
        self.min_consensus = (
            min_consensus
            if min_consensus is not None
            else params.agents.ensemble_min_consensus
        )

    def _parse_model_spec(self, model_spec: str) -> tuple[LLMProvider, str]:
        """Parses 'provider/model_name' into (LLMProvider, model_name)."""
        if "/" in model_spec:
            provider_str, model_name = model_spec.split("/", 1)
        else:
            provider_str = "openrouter"
            model_name = model_spec

        provider_map = {
            "openrouter": LLMProvider.OPENROUTER,
            "deepseek": LLMProvider.DEEPSEEK,
            "ollama": LLMProvider.OLLAMA,
        }
        provider = provider_map.get(provider_str.lower(), LLMProvider.OPENROUTER)
        return provider, model_name

    def _call_single_model(
        self,
        model_spec: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 300,
    ) -> dict[str, Any] | None:
        """Calls a single LLM model and returns parsed JSON response."""
        try:
            provider, model_name = self._parse_model_spec(model_spec)
            llm = create_llm(provider=provider, model=model_name, temperature=0.1)

            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            response = llm.invoke(
                messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw_text = response.content
            result = extract_json(raw_text)

            if not result:
                logger.warning("No valid JSON from model %s", model_spec)
                return None

            return {
                "model": model_spec,
                "action": result.get("action", result.get("signal", "hold")).lower(),
                "confidence": float(result.get("confidence", 0.3)),
                "amount": float(result.get("amount", 0.0)),
                "stop_loss": float(result.get("stop_loss", result.get("sl", 0.0))),
                "take_profit": float(result.get("take_profit", result.get("tp", 0.0))),
                "reasoning": result.get("reasoning", ""),
                "sentiment_score": float(result.get("sentiment_score", 0.0)),
                "risk_score": float(result.get("risk_score", 0.5)),
            }
        except Exception as e:
            logger.error("Ensemble model %s failed: %s", model_spec, e)
            return None

    def vote(
        self,
        system_prompt: str,
        user_prompt: str,
        models: list[str] | None = None,
        max_tokens: int = 300,
    ) -> dict[str, Any]:
        """
        Runs multiple LLM models in parallel and aggregates via voting.

        Args:
            system_prompt: System prompt for all models
            user_prompt: User prompt for all models
            models: Override list of model specs (e.g. ["deepseek/deepseek-chat", "ollama/llama3:8b"])
            max_tokens: Max tokens per model call

        Returns:
            dict with keys: action, confidence, consensus_score, individual_votes, reasoning
        """
        target_models = models or self.models
        if not target_models:
            logger.warning("No ensemble models configured, returning hold")
            return self._default_result("No ensemble models configured")

        successful_votes: list[dict[str, Any]] = []

        # Max workers cap: min of (configured models count, system max_workers)
        params = get_trading_params()
        max_workers_cap = min(len(target_models), params.system.max_workers)
        
        with ThreadPoolExecutor(max_workers=max_workers_cap) as executor:
            logger.debug("Running ensemble with %d workers for %d models", max_workers_cap, len(target_models))
            futures = {
                executor.submit(
                    self._call_single_model,
                    spec,
                    system_prompt,
                    user_prompt,
                    max_tokens,
                ): spec
                for spec in target_models
            }

            for future in as_completed(futures):
                spec = futures[future]
                try:
                    result = future.result()
                    if result:
                        successful_votes.append(result)
                    else:
                        logger.warning("Model %s returned no valid result", spec)
                except Exception as e:
                    logger.error("Future exception for %s: %s", spec, e)

        if not successful_votes:
            return self._default_result("All ensemble models failed")

        return self._aggregate_votes(successful_votes)

    def _aggregate_votes(self, votes: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregates individual votes into a final decision with confidence weighting."""
        total = len(votes)
        if total == 0:
            return self._default_result("No votes to aggregate")

        # 1. Action Voting (Confidence Weighted)
        weighted_action_scores: dict[str, float] = {}
        for vote in votes:
            action = vote["action"]
            conf = max(0.01, vote["confidence"]) # Zero confidence safety
            weighted_action_scores[action] = weighted_action_scores.get(action, 0.0) + conf

        winning_action = max(weighted_action_scores, key=weighted_action_scores.get)
        total_weight = sum(weighted_action_scores.values())
        weighted_consensus = weighted_action_scores[winning_action] / total_weight

        # Simple majority count for legacy compatibility/logging
        action_counts: dict[str, int] = {}
        for v in votes:
            a = v["action"]
            action_counts[a] = action_counts.get(a, 0) + 1
        simple_consensus = action_counts[winning_action] / total

        # 2. Numerical Aggregation (Confidence Weighted + Outlier Filter)
        # Sadece kazanan aksiyona katılanların sayısal değerlerini baz alalım (opsiyonel ama daha tutarlı)
        # Şimdilik tüm başarılı oyları ağırlıklı ortalama ile alıyoruz.
        weighted_amount = 0.0
        weighted_sl = 0.0
        weighted_tp = 0.0
        weighted_sentiment = 0.0
        weighted_risk = 0.0
        total_conf = 0.0
        all_reasoning: list[str] = []

        for vote in votes:
            conf = max(0.01, vote["confidence"])
            weighted_amount += conf * vote["amount"]
            weighted_sl += conf * vote["stop_loss"]
            weighted_tp += conf * vote["take_profit"]
            weighted_sentiment += conf * vote["sentiment_score"]
            weighted_risk += conf * vote["risk_score"]
            total_conf += conf
            if vote["reasoning"]:
                all_reasoning.append(f"[{vote['model']}] {vote['reasoning']}")

        avg_confidence = total_conf / total
        avg_amount = weighted_amount / total_conf if total_conf > 0 else 0.0
        avg_sl = weighted_sl / total_conf if total_conf > 0 else 0.0
        avg_tp = weighted_tp / total_conf if total_conf > 0 else 0.0
        avg_sentiment = weighted_sentiment / total_conf if total_conf > 0 else 0.0
        avg_risk = weighted_risk / total_conf if total_conf > 0 else 0.0

        # Consensus check
        final_consensus = max(weighted_consensus, simple_consensus)
        if final_consensus < self.min_consensus:
            logger.warning(
                "Low ensemble consensus (weighted: %.2f, simple: %.2f < %.2f), returning hold",
                weighted_consensus,
                simple_consensus,
                self.min_consensus,
            )
            return self._default_result(
                f"Low consensus ({final_consensus:.2f})",
                individual_votes=votes,
                consensus_score=final_consensus,
            )

        combined_reasoning = "\n".join(all_reasoning) if all_reasoning else "No reasoning provided"

        logger.info(
            "Ensemble weighted vote: %s (weighted_cons=%.2f, simple_cons=%.2f, models=%d/%d)",
            winning_action,
            weighted_consensus,
            simple_consensus,
            len([v for v in votes if v["action"] == winning_action]),
            total,
        )

        return {
            "action": winning_action,
            "confidence": round(avg_confidence, 4),
            "consensus_score": round(final_consensus, 4),
            "amount": round(avg_amount, 4),
            "stop_loss": round(avg_sl, 4),
            "take_profit": round(avg_tp, 4),
            "sentiment_score": round(avg_sentiment, 4),
            "risk_score": round(avg_risk, 4),
            "individual_votes": votes,
            "reasoning": combined_reasoning,
            "models_used": [v["model"] for v in votes],
            "total_models": total,
            "weighted_consensus": round(weighted_consensus, 4),
        }

    def _default_result(
        self,
        reason: str,
        individual_votes: list[dict] | None = None,
        consensus_score: float = 0.0,
    ) -> dict[str, Any]:
        """Returns a safe default result."""
        return {
            "action": "hold",
            "confidence": 0.1,
            "consensus_score": consensus_score,
            "amount": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "sentiment_score": 0.0,
            "risk_score": 0.5,
            "individual_votes": individual_votes or [],
            "reasoning": reason,
            "models_used": [],
            "total_models": 0,
        }
