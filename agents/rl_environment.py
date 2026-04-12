"""
Reinforcement Learning Trading Environment
============================================
Custom Gymnasium environment for training a PPO agent
to make trading decisions based on market state.
"""

from __future__ import annotations

import logging
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

logger = logging.getLogger(__name__)


class TradingEnv(gym.Env):
    """Custom trading environment for RL training and inference."""

    metadata = {"render_modes": ["human", "ansi"]}

    def __init__(
        self,
        market_data: list[dict] | None = None,
        portfolio_state: dict | None = None,
        max_steps: int = 100,
        training: bool = True,
        render_mode: str | None = None,
    ):
        super().__init__()

        self.market_data = market_data or []
        self.portfolio_state = portfolio_state or {}
        self.max_steps = max_steps
        self.training = training
        self.render_mode = render_mode

        self.observation_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(15,),
            dtype=np.float32,
        )

        self.action_space = spaces.Discrete(5)

        self.current_step = 0
        self.initial_equity = 0.0
        self.equity_history: list[float] = []
        self.total_pnl = 0.0
        self.position_size = 0.0
        self.entry_price = 0.0
        self.has_position = False
        self._data_index = 0

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict | None = None,
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)

        self.current_step = 0
        self.total_pnl = 0.0
        self.position_size = 0.0
        self.entry_price = 0.0
        self.has_position = False
        self.equity_history = []
        self._data_index = 0

        equity = self.portfolio_state.get("equity", 10000.0)
        self.initial_equity = equity

        if self.market_data:
            if self.training:
                start = np.random.randint(
                    0, max(1, len(self.market_data) - self.max_steps)
                )
                self._data_index = start
            else:
                self._data_index = 0

        obs = self._get_observation()
        return obs, {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        reward = self._calculate_reward(action)

        self.current_step += 1
        if self.market_data:
            self._data_index += 1

        terminated = self.current_step >= self.max_steps
        truncated = False

        if self.market_data and self._data_index >= len(self.market_data):
            terminated = True

        obs = self._get_observation()
        info = {
            "action": action,
            "reward": reward,
            "total_pnl": self.total_pnl,
            "step": self.current_step,
        }

        return obs, reward, terminated, truncated, info

    def render(self) -> str | None:
        if self.render_mode == "human" or self.render_mode == "ansi":
            line = (
                f"Step: {self.current_step}/{self.max_steps} | "
                f"P&L: {self.total_pnl:.4f} | "
                f"Position: {'Yes' if self.has_position else 'No'}"
            )
            if self.render_mode == "human":
                print(line)
            return line
        return None

    def _get_observation(self) -> np.ndarray:
        obs = np.zeros(15, dtype=np.float32)

        tech = self._get_current_data().get("technical_signals", {})
        sentiment = self._get_current_data().get("sentiment", {})
        portfolio = self.portfolio_state or {}
        rag_info = self._get_current_data().get("rag_info", {})
        drift_info = self._get_current_data().get("drift_info", {})

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
        max_pos = portfolio.get("max_positions", 5)
        if max_pos > 0:
            obs[8] = (open_pos / max_pos) * 2.0 - 1.0

        drawdown = portfolio.get("current_drawdown", 0.0)
        obs[9] = np.clip(-drawdown * 2.0, -1.0, 0.0)

        rag_acc = rag_info.get("similar_trade_accuracy", 0.5)
        obs[10] = np.clip(rag_acc * 2.0 - 1.0, -1.0, 1.0)

        agent_acc = drift_info.get("agent_accuracy", 0.5)
        obs[11] = np.clip(agent_acc * 2.0 - 1.0, -1.0, 1.0)

        if self.has_position and self.entry_price > 0:
            current_price = price if price > 0 else self.entry_price
            pnl_pct = (current_price - self.entry_price) / self.entry_price
            obs[12] = np.clip(pnl_pct * 5.0, -1.0, 1.0)
        else:
            obs[12] = 0.0

        obs[13] = np.clip(self.total_pnl / max(self.initial_equity, 1.0), -1.0, 1.0)

        if self.training:
            obs[14] = np.clip(
                self.current_step / max(self.max_steps, 1) * 2.0 - 1.0, -1.0, 1.0
            )
        else:
            obs[14] = 0.0

        return obs

    def _calculate_reward(self, action: int) -> float:
        reward = 0.0

        price_data = self._get_current_data()
        tech = price_data.get("technical_signals", {})
        price = tech.get("current_price", 0.0)

        if action == 4:
            if self.has_position and self.entry_price > 0 and price > 0:
                pnl = (price - self.entry_price) / self.entry_price
                reward += pnl * 10.0
                self.total_pnl += pnl
                self.has_position = False
                self.position_size = 0.0
        elif action in (1, 2, 3):
            buy_sizes = {1: 0.10, 2: 0.30, 3: 0.60}
            size_pct = buy_sizes[action]

            if not self.has_position and price > 0:
                equity = self.portfolio_state.get("equity", 10000.0)
                self.position_size = equity * size_pct
                self.entry_price = price
                self.has_position = True
                reward += 0.01
        else:
            if self.has_position and self.entry_price > 0 and price > 0:
                unrealized = (price - self.entry_price) / self.entry_price
                reward += unrealized * 5.0

        portfolio = self.portfolio_state or {}
        drawdown = portfolio.get("current_drawdown", 0.0)
        if drawdown > 0.05:
            reward -= np.exp(drawdown * 10.0) * 0.5

        if len(self.equity_history) >= 10:
            returns = np.diff(self.equity_history[-10:])
            if np.std(returns) > 0:
                sharpe = np.mean(returns) / np.std(returns)
                reward += np.clip(sharpe * 0.5, -1.0, 1.0)

        rag_info = price_data.get("rag_info", {})
        rag_acc = rag_info.get("similar_trade_accuracy", 0.5)
        if rag_acc > 0.7:
            reward += 0.2

        drift_info = price_data.get("drift_info", {})
        agent_acc = drift_info.get("agent_accuracy", 0.5)
        if agent_acc < 0.4:
            reward -= 0.3

        self.equity_history.append(self.initial_equity + self.total_pnl)
        if len(self.equity_history) > 1000:
            self.equity_history = self.equity_history[-500:]

        return reward

    def _get_current_data(self) -> dict:
        if self.market_data and 0 <= self._data_index < len(self.market_data):
            return self.market_data[self._data_index]
        return {
            "technical_signals": {},
            "sentiment": {},
            "rag_info": {},
            "drift_info": {},
        }
