"""
Reinforcement Learning Advisor
================================
PPO-based RL agent that provides trading recommendations
to complement LLM-driven decisions in the trading graph.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from agents.rl_environment import TradingEnv

logger = logging.getLogger(__name__)

_MODEL_VERSION = "1.0.0"


class RLAdvisor:
    """PPO-based RL advisor for trading decisions."""

    def __init__(self, model_path: str | Path | None = None):
        self.model = None
        self.model_path = Path(model_path) if model_path else None
        self._action_probabilities = None
        self._last_confidence = 0.0

        if self.model_path and self.model_path.exists():
            self.load_model(self.model_path)
        elif self.model_path:
            logger.warning("Model path does not exist: %s", self.model_path)

    def _ensure_model(self):
        if self.model is None:
            try:
                from stable_baselines3 import PPO
                from agents.rl_environment import TradingEnv

                env = TradingEnv()
                self.model = PPO(
                    "MlpPolicy",
                    env,
                    verbose=0,
                    learning_rate=3e-4,
                    n_steps=512,
                    batch_size=64,
                    n_epochs=10,
                    gamma=0.99,
                    gae_lambda=0.95,
                    clip_range=0.2,
                    ent_coef=0.01,
                )
                logger.warning(
                    "RL advisor: Using UNTRAINED model — recommendations are random. "
                    "Train the model first or provide a saved model path."
                )
            except ImportError:
                logger.error("stable-baselines3 not installed")
                raise

    def get_recommendation(self, state_dict: dict[str, Any]) -> dict[str, Any]:
        observation = self._state_to_observation(state_dict)

        self._ensure_model()

        # Model atanmış mı kontrol et (manual mock için)
        if self.model is None or not hasattr(self.model, "predict"):
            logger.error("RL model yok veya bozuk")
            return {
                "rl_action": "hold",
                "rl_amount_pct": 0.0,
                "rl_confidence": 0.0,
                "rl_reasoning": "Model çalışmıyor - güvenlik nedeniyle HOLD",
                "model_version": _MODEL_VERSION,
                "error": True,
            }

        # Untrained kontrolü (sadece model_path belirtilmiş ama model yüklenmemişse)
        if (
            hasattr(self, "model_path")
            and self.model_path
            and not self.model_path.exists()
        ):
            logger.warning("RL model path mevcut değil - güvenli hold")
            return {
                "rl_action": "hold",
                "rl_amount_pct": 0.0,
                "rl_confidence": 0.0,
                "rl_reasoning": "Model yüklenmedi - güvenlik nedeniyle HOLD",
                "model_version": _MODEL_VERSION,
                "untrained": True,
            }

        observation = self._state_to_observation(state_dict)

        self._ensure_model()

        if self.model is None or not hasattr(self.model, "predict"):
            logger.error("RL model yok veya bozuk")
            return {
                "rl_action": "hold",
                "rl_amount_pct": 0.0,
                "rl_confidence": 0.0,
                "rl_reasoning": "Model çalışmıyor - güvenlik nedeniyle HOLD",
                "model_version": _MODEL_VERSION,
                "error": True,
            }

        action, _ = self.model.predict(observation, deterministic=True)
        action = int(action)

        try:
            tensor_obs = (
                observation
                if isinstance(observation, np.ndarray)
                else np.array(observation)
            )
            action_probs, _ = self.model.predict(
                tensor_obs.reshape(1, -1), deterministic=False
            )
            if hasattr(self.model, "policy"):
                dist = self.model.policy.get_distribution(
                    self.model.policy.obs_to_tensor(tensor_obs.reshape(1, -1))[0]
                )
                probs = dist.distribution.probs.detach().cpu().numpy()[0]
                self._action_probabilities = probs
                self._last_confidence = float(np.max(probs))
            else:
                self._last_confidence = 0.5
        except Exception:
            self._last_confidence = 0.5

        action_map = {
            0: "hold",
            1: "buy_small",
            2: "buy_medium",
            3: "buy_large",
            4: "sell",
        }
        amount_map = {
            0: 0.0,
            1: 0.10,
            2: 0.30,
            3: 0.60,
            4: 1.0,
        }

        rl_action = action_map.get(action, "hold")
        rl_amount = amount_map.get(action, 0.0)

        reasoning = self._generate_reasoning(action, state_dict)

        return {
            "rl_action": rl_action,
            "rl_amount_pct": rl_amount,
            "rl_confidence": self._last_confidence,
            "rl_reasoning": reasoning,
            "model_version": _MODEL_VERSION,
        }

    def train(
        self,
        env: TradingEnv,
        total_timesteps: int = 10000,
        save_path: str | Path | None = None,
    ):
        self._ensure_model()

        logger.info("Training PPO model: %d timesteps", total_timesteps)
        self.model.set_env(env)
        self.model.learn(total_timesteps=total_timesteps, progress_bar=False)

        if save_path:
            self.save_model(save_path)

        logger.info("PPO training complete")

    def save_model(self, path: str | Path):
        self._ensure_model()
        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save(str(save_path))
        logger.info("PPO model saved: %s", save_path)

    def load_model(self, path: str | Path):
        try:
            from stable_baselines3 import PPO

            load_path = Path(path)
            self.model = PPO.load(str(load_path))
            self.model_path = load_path
            logger.info("PPO model loaded: %s", load_path)
        except Exception as e:
            logger.error("Failed to load PPO model: %s", e)
            raise

    def get_confidence(self) -> float:
        return self._last_confidence

    def _state_to_observation(self, state_dict: dict) -> np.ndarray:
        obs = np.zeros(15, dtype=np.float32)

        tech = state_dict.get("technical_signals", {})
        sentiment = state_dict.get("sentiment", {})
        portfolio = state_dict.get("portfolio_state", {})
        historical = state_dict.get("historical_context", [])
        agent_acc = state_dict.get("agent_accuracy", 1.0)

        rsi = tech.get("rsi_14", 50.0)
        obs[0] = (rsi / 100.0) * 2.0 - 1.0

        macd_hist = tech.get("macd_histogram", 0.0)
        price = tech.get("current_price", 0.0)
        if price > 0:
            obs[1] = np.clip(macd_hist / price, -1.0, 1.0)

        atr = tech.get("atr_14", 0.0)
        if price > 0 and atr > 0:
            obs[2] = np.clip((atr / price) * 10.0 - 1.0, -1.0, 1.0)

        ema20 = tech.get("ema_20", 0.0)
        if price > 0 and ema20 > 0:
            obs[3] = np.clip((ema20 / price) - 1.0, -1.0, 1.0)

        vol_ratio = tech.get("volume_sma_ratio", 1.0)
        obs[4] = np.clip((vol_ratio / 3.0) - 1.0, -1.0, 1.0)

        sent_score = sentiment.get("sentiment_score", 0.0)
        obs[5] = np.clip(sent_score, -1.0, 1.0)

        sent_conf = sentiment.get("confidence", 0.0)
        obs[6] = np.clip(sent_conf, 0.0, 1.0)

        cash = portfolio.get("cash", 10000.0)
        equity = portfolio.get("equity", 10000.0)
        if equity > 0:
            obs[7] = (cash / equity) * 2.0 - 1.0

        open_pos = portfolio.get("open_positions", 0)
        max_pos = 5
        obs[8] = (open_pos / max_pos) * 2.0 - 1.0

        drawdown = portfolio.get("current_drawdown", 0.0)
        obs[9] = np.clip(-drawdown * 2.0, -1.0, 0.0)

        rag_acc = 0.5
        if historical:
            accuracies = [
                h.get("past_accuracy", 0.5)
                for h in historical
                if h.get("past_accuracy") is not None
            ]
            if accuracies:
                rag_acc = np.mean(accuracies)
        obs[10] = np.clip(rag_acc * 2.0 - 1.0, -1.0, 1.0)

        obs[11] = np.clip(agent_acc * 2.0 - 1.0, -1.0, 1.0)

        has_position = portfolio.get("open_positions", 0) > 0
        if has_position:
            positions = portfolio.get("positions", [])
            if positions:
                avg_entry = np.mean([p.get("entry_price", 0) for p in positions])
                if avg_entry > 0 and price > 0:
                    pnl_pct = (price - avg_entry) / avg_entry
                    obs[12] = np.clip(pnl_pct * 5.0, -1.0, 1.0)
        else:
            obs[12] = 0.0

        total_pnl = portfolio.get("total_pnl", 0.0)
        if equity > 0:
            obs[13] = np.clip(total_pnl / equity, -1.0, 1.0)

        obs[14] = 0.0

        return obs

    def _generate_reasoning(self, action: int, state_dict: dict) -> str:
        tech = state_dict.get("technical_signals", {})
        sentiment = state_dict.get("sentiment", {})
        confidence = self._last_confidence

        conf_label = (
            "high" if confidence > 0.7 else "medium" if confidence > 0.4 else "low"
        )

        rsi = tech.get("rsi_14", 50.0)
        trend = tech.get("trend", "neutral")
        sent_score = sentiment.get("sentiment_score", 0.0)

        reasons = []

        if action == 0:
            reasons.append(
                f"RL recommends HOLD (confidence: {confidence:.2f}, {conf_label})"
            )
        elif action in (1, 2, 3):
            size_labels = {1: "small (10%)", 2: "medium (30%)", 3: "large (60%)"}
            reasons.append(
                f"RL recommends BUY {size_labels[action]} (confidence: {confidence:.2f}, {conf_label})"
            )
        elif action == 4:
            reasons.append(
                f"RL recommends SELL (confidence: {confidence:.2f}, {conf_label})"
            )

        if rsi < 30:
            reasons.append("RSI oversold")
        elif rsi > 70:
            reasons.append("RSI overbought")

        if trend != "neutral":
            reasons.append(f"Trend: {trend}")

        if abs(sent_score) > 0.3:
            sent_dir = "bullish" if sent_score > 0 else "bearish"
            reasons.append(f"Sentiment: {sent_dir}")

        return " | ".join(reasons)


# ── LangGraph Node ──────────────────────────────────────────
def rl_advisor_node(state: TradingState) -> dict[str, Any]:
    """
    RL Advisor düğümü.
    Mevcut state'i RL modeline besler ve tavsiye oluşturur.
    """
    from config.settings import get_trading_params
    
    params = get_trading_params()
    symbol = state["symbol"]
    
    # RL kapalıysa pasla
    if not getattr(params.agents, "rl_enabled", False):
        return {"phase": "rl_skipped"}

    logger.info("RL Advisor çalışıyor: %s", symbol)
    
    try:
        # Model yolunu belirle
        model_path = getattr(params.agents, "rl_model_path", "models/ppo_trading.zip")
        
        advisor = RLAdvisor(model_path=model_path)
        recommendation = advisor.get_recommendation(state)
        
        return {
            "rl_recommendation": recommendation,
            "rl_confidence": recommendation.get("rl_confidence", 0.0),
            "phase": "rl_complete",
        }
    except Exception as e:
        logger.error("RL Advisor hatası: %s", e)
        return {
            "rl_error": str(e),
            "phase": "rl_error",
        }
