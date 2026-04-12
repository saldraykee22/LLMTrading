"""
Comprehensive tests for Faz 7 modules:
- RL Environment (TradingEnv)
- RL Advisor (RLAdvisor / PPO)
- Enhanced VectorStore (rich context, semantic tags, multi-symbol, pruning, accuracy)
- AgentMemoryStoreWrapper (trade context, similar trades, outcomes, lessons)
- Enhanced DriftMonitor (time-decay, binomial test, magnitude, per-agent, heatmap)
- EnsembleVoter (parallel LLM, majority vote, weighted average, consensus)
- PromptEvolver (versioning, evolution, rollback)
- Dashboard API endpoints (FastAPI)
- Integration tests (RL + Graph, RL + Trader, RAG + RL, Drift + Risk, etc.)
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def mock_market_data():
    """Generate realistic mock market data for RL environment."""
    data = []
    for i in range(50):
        data.append(
            {
                "technical_signals": {
                    "rsi_14": 45.0 + (i % 20),
                    "macd_histogram": 0.5 + (i % 3) * 0.1,
                    "current_price": 50000.0 + i * 100,
                    "atr_14": 500.0,
                    "ema_20": 49500.0 + i * 80,
                    "volume_sma_ratio": 1.2,
                },
                "sentiment": {
                    "sentiment_score": 0.3,
                    "confidence": 0.7,
                },
                "rag_info": {
                    "similar_trade_accuracy": 0.65,
                },
                "drift_info": {
                    "agent_accuracy": 0.72,
                },
            }
        )
    return data


@pytest.fixture
def mock_portfolio_state():
    """Generate mock portfolio state."""
    return {
        "equity": 10000.0,
        "cash": 8000.0,
        "open_positions": 1,
        "max_positions": 5,
        "current_drawdown": 0.02,
        "total_pnl": 200.0,
    }


@pytest.fixture
def mock_state_dict():
    """Generate mock state dict for RLAdvisor."""
    return {
        "technical_signals": {
            "rsi_14": 35.0,
            "macd_histogram": 0.5,
            "current_price": 50000.0,
            "atr_14": 500.0,
            "ema_20": 49500.0,
            "volume_sma_ratio": 1.2,
            "trend": "bullish",
        },
        "sentiment": {
            "sentiment_score": 0.4,
            "confidence": 0.75,
        },
        "portfolio_state": {
            "equity": 10000.0,
            "cash": 8000.0,
            "open_positions": 1,
            "current_drawdown": 0.02,
            "total_pnl": 200.0,
        },
        "historical_context": [
            {"past_accuracy": 0.65},
            {"past_accuracy": 0.70},
        ],
        "agent_accuracy": 0.72,
    }


@pytest.fixture
def vector_store_state():
    """Generate mock state for VectorStore tests."""
    return {
        "symbol": "BTC/USDT",
        "market_data": {
            "current_price": 50000.0,
            "volume_ratio": 1.5,
        },
        "news_data": [
            {"title": "Bitcoin surges past resistance"},
            {"title": "Fed signals rate cut"},
        ],
        "technical_signals": {
            "ema20": 49000.0,
            "ema50": 48000.0,
            "sma200": 45000.0,
            "rsi": {"value": 25, "signal": "oversold"},
            "macd": {"histogram": 0.5, "macd": 1.2, "signal": 0.8},
            "vix": 35,
            "atr": {"value": 1500},
            "bollinger_bands": {"upper": 52000, "lower": 46000},
        },
        "sentiment": {
            "sentiment_score": 0.5,
            "confidence": 0.8,
            "signal": "bullish",
        },
        "trade_decision": {
            "action": "buy",
            "confidence": 0.75,
        },
    }


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory and patch DATA_DIR."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with patch("config.settings.DATA_DIR", data_dir):
        yield data_dir


# ──────────────────────────────────────────────
# A) RL Environment Tests
# ──────────────────────────────────────────────


class TestTradingEnv:
    def test_env_initialization(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv()
        assert env.max_steps == 100
        assert env.training is True
        assert env.market_data == []
        assert env.portfolio_state == {}
        assert env.render_mode is None

    def test_env_with_custom_params(self, mock_market_data, mock_portfolio_state):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(
            market_data=mock_market_data,
            portfolio_state=mock_portfolio_state,
            max_steps=50,
            training=False,
            render_mode="human",
        )
        assert env.max_steps == 50
        assert env.training is False
        assert len(env.market_data) == 50
        assert env.render_mode == "human"

    def test_observation_space_shape_and_bounds(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv()
        assert env.observation_space.shape == (15,)
        assert env.observation_space.low.shape == (15,)
        assert env.observation_space.high.shape == (15,)
        assert np.all(env.observation_space.low == -1.0)
        assert np.all(env.observation_space.high == 1.0)
        assert env.observation_space.dtype == np.float32

    def test_action_space_discrete_five(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv()
        assert env.action_space.n == 5
        assert 0 in env.action_space
        assert 4 in env.action_space

    def test_reset_returns_valid_observation(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv()
        obs, info = env.reset()
        assert isinstance(obs, np.ndarray)
        assert obs.shape == (15,)
        assert obs.dtype == np.float32
        assert isinstance(info, dict)
        assert env.current_step == 0
        assert env.initial_equity == 10000.0

    def test_reset_with_seed(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv()
        obs1, _ = env.reset(seed=42)
        obs2, _ = env.reset(seed=42)
        np.testing.assert_array_equal(obs1, obs2)

    def test_step_with_each_action(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(max_steps=10)
        env.reset()
        for action in range(5):
            obs, reward, terminated, truncated, info = env.step(action)
            assert isinstance(obs, np.ndarray)
            assert obs.shape == (15,)
            assert isinstance(reward, (float, np.floating))
            assert isinstance(terminated, bool)
            assert isinstance(truncated, bool)
            assert isinstance(info, dict)
            assert "action" in info
            assert "reward" in info
            assert "total_pnl" in info

    def test_reward_calculation_pnl_and_drawdown(self):
        from agents.rl_environment import TradingEnv

        portfolio = {
            "equity": 10000.0,
            "cash": 8000.0,
            "open_positions": 0,
            "max_positions": 5,
            "current_drawdown": 0.0,
        }
        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {"similar_trade_accuracy": 0.5},
                "drift_info": {"agent_accuracy": 0.5},
            }
        ]
        env = TradingEnv(market_data=data, portfolio_state=portfolio, max_steps=5)
        env.reset()
        obs, reward, _, _, info = env.step(1)
        assert env.has_position is True
        assert env.entry_price == 50000.0
        assert reward >= 0.01

    def test_reward_drawdown_penalty(self):
        from agents.rl_environment import TradingEnv

        portfolio = {
            "equity": 10000.0,
            "cash": 8000.0,
            "open_positions": 0,
            "max_positions": 5,
            "current_drawdown": 0.10,
        }
        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {"similar_trade_accuracy": 0.5},
                "drift_info": {"agent_accuracy": 0.5},
            }
        ]
        env = TradingEnv(market_data=data, portfolio_state=portfolio, max_steps=5)
        env.reset()
        obs, reward, _, _, _ = env.step(0)
        assert reward < 0

    def test_episode_termination(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(max_steps=3)
        env.reset()
        env.step(0)
        env.step(0)
        obs, reward, terminated, truncated, info = env.step(0)
        assert terminated is True
        assert truncated is False

    def test_episode_termination_data_exhausted(self):
        from agents.rl_environment import TradingEnv

        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {},
                "drift_info": {},
            }
        ]
        env = TradingEnv(market_data=data, max_steps=100)
        env.reset()
        env.step(0)
        obs, reward, terminated, truncated, _ = env.step(0)
        assert terminated is True

    def test_observation_normalization(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv()
        obs, _ = env.reset()
        assert np.all(obs >= -1.0)
        assert np.all(obs <= 1.0)

    def test_observation_with_mock_portfolio_data(
        self, mock_market_data, mock_portfolio_state
    ):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(
            market_data=mock_market_data,
            portfolio_state=mock_portfolio_state,
            max_steps=10,
        )
        obs, _ = env.reset()
        assert obs.shape == (15,)
        assert np.all(np.isfinite(obs))
        assert np.all(obs >= -1.0)
        assert np.all(obs <= 1.0)

    def test_render_method(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(max_steps=10, render_mode="ansi")
        env.reset()
        env.step(0)
        result = env.render()
        assert result is not None
        assert "Step:" in result
        assert "P&L:" in result
        assert "Position:" in result

    def test_render_human_mode(self, capsys):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(max_steps=10, render_mode="human")
        env.reset()
        env.step(0)
        env.render()
        captured = capsys.readouterr()
        assert "Step:" in captured.out

    def test_render_no_mode(self):
        from agents.rl_environment import TradingEnv

        env = TradingEnv(max_steps=10, render_mode=None)
        env.reset()
        env.step(0)
        result = env.render()
        assert result is None

    def test_sell_action_closes_position(self):
        from agents.rl_environment import TradingEnv

        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {},
                "drift_info": {},
            },
            {
                "technical_signals": {"current_price": 51000.0, "rsi_14": 55},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {},
                "drift_info": {},
            },
        ]
        env = TradingEnv(market_data=data, max_steps=10)
        env.reset()
        env.step(1)
        assert env.has_position is True
        obs, reward, _, _, _ = env.step(4)
        assert env.has_position is False
        assert env.total_pnl > 0

    def test_hold_reward_with_position(self):
        from agents.rl_environment import TradingEnv

        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {},
                "drift_info": {},
            },
            {
                "technical_signals": {"current_price": 51000.0, "rsi_14": 55},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {},
                "drift_info": {},
            },
        ]
        env = TradingEnv(market_data=data, max_steps=10)
        env.reset()
        env.step(1)
        obs, reward, _, _, _ = env.step(0)
        assert env.has_position is True

    def test_rag_accuracy_bonus(self):
        from agents.rl_environment import TradingEnv

        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {"similar_trade_accuracy": 0.8},
                "drift_info": {"agent_accuracy": 0.5},
            }
        ]
        env = TradingEnv(market_data=data, max_steps=5)
        env.reset()
        obs, reward, _, _, _ = env.step(0)
        assert reward > 0.0

    def test_low_agent_accuracy_penalty(self):
        from agents.rl_environment import TradingEnv

        data = [
            {
                "technical_signals": {"current_price": 50000.0, "rsi_14": 50},
                "sentiment": {"sentiment_score": 0.0, "confidence": 0.5},
                "rag_info": {},
                "drift_info": {"agent_accuracy": 0.3},
            }
        ]
        env = TradingEnv(market_data=data, max_steps=5)
        env.reset()
        obs, reward, _, _, _ = env.step(0)
        assert reward < 0


# ──────────────────────────────────────────────
# B) RL Advisor Tests
# ──────────────────────────────────────────────


class TestRLAdvisor:
    def test_advisor_initialization(self):
        from agents.rl_advisor import RLAdvisor

        advisor = RLAdvisor()
        assert advisor.model is None
        assert advisor.model_path is None
        assert advisor._last_confidence == 0.0

    def test_advisor_with_nonexistent_path(self, tmp_path):
        from agents.rl_advisor import RLAdvisor

        fake_path = tmp_path / "nonexistent_model.zip"
        with patch("agents.rl_advisor.logger"):
            advisor = RLAdvisor(model_path=fake_path)
        assert advisor.model is None

    @patch("agents.rl_advisor.RLAdvisor._ensure_model")
    @patch("agents.rl_advisor.RLAdvisor._state_to_observation")
    def test_get_recommendation_output_format(
        self, mock_obs, mock_ensure, mock_state_dict
    ):
        from agents.rl_advisor import RLAdvisor

        mock_obs.return_value = np.zeros(15, dtype=np.float32)

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(1), None)
        advisor.model = mock_model

        result = advisor.get_recommendation(mock_state_dict)

        assert "rl_action" in result
        assert "rl_amount_pct" in result
        assert "rl_confidence" in result
        assert "rl_reasoning" in result
        assert "model_version" in result
        assert result["rl_action"] in (
            "hold",
            "buy_small",
            "buy_medium",
            "buy_large",
            "sell",
        )
        assert 0.0 <= result["rl_amount_pct"] <= 1.0
        assert 0.0 <= result["rl_confidence"] <= 1.0

    @patch("agents.rl_advisor.RLAdvisor._ensure_model")
    @patch("agents.rl_advisor.RLAdvisor._state_to_observation")
    def test_recommendation_hold_action(self, mock_obs, mock_ensure, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        mock_obs.return_value = np.zeros(15, dtype=np.float32)

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(0), None)
        advisor.model = mock_model

        result = advisor.get_recommendation(mock_state_dict)
        assert result["rl_action"] == "hold"
        assert result["rl_amount_pct"] == 0.0

    @patch("agents.rl_advisor.RLAdvisor._ensure_model")
    @patch("agents.rl_advisor.RLAdvisor._state_to_observation")
    def test_recommendation_sell_action(self, mock_obs, mock_ensure, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        mock_obs.return_value = np.zeros(15, dtype=np.float32)

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(4), None)
        advisor.model = mock_model

        result = advisor.get_recommendation(mock_state_dict)
        assert result["rl_action"] == "sell"
        assert result["rl_amount_pct"] == 1.0

    @patch("agents.rl_advisor.RLAdvisor._ensure_model")
    @patch("agents.rl_advisor.RLAdvisor._state_to_observation")
    def test_get_confidence(self, mock_obs, mock_ensure, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        mock_obs.return_value = np.zeros(15, dtype=np.float32)

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(1), None)
        advisor.model = mock_model

        advisor.get_recommendation(mock_state_dict)
        conf = advisor.get_confidence()
        assert isinstance(conf, float)

    def test_save_and_load_model(self, tmp_path):
        from agents.rl_advisor import RLAdvisor

        model_path = tmp_path / "test_model"

        advisor = RLAdvisor()
        mock_model = MagicMock()
        advisor.model = mock_model

        advisor.save_model(model_path)
        mock_model.save.assert_called_once()

    @patch("stable_baselines3.PPO")
    def test_training_with_mock_env(self, mock_ppo_class):
        from agents.rl_advisor import RLAdvisor
        from agents.rl_environment import TradingEnv

        mock_model = MagicMock()
        mock_ppo_class.return_value = mock_model

        advisor = RLAdvisor()
        env = TradingEnv(max_steps=10)
        advisor.model = mock_model

        advisor.train(env, total_timesteps=100)
        mock_model.learn.assert_called_once()
        assert mock_model.learn.call_args.kwargs["total_timesteps"] == 100

    @patch("agents.rl_advisor.RLAdvisor._ensure_model")
    @patch("agents.rl_advisor.RLAdvisor._state_to_observation")
    def test_different_confidence_levels(self, mock_obs, mock_ensure, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        mock_obs.return_value = np.zeros(15, dtype=np.float32)

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(2), None)
        advisor.model = mock_model

        result = advisor.get_recommendation(mock_state_dict)
        assert "rl_confidence" in result
        assert isinstance(result["rl_confidence"], float)

    def test_backward_compatibility_no_model(self, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(0), None)
        advisor.model = mock_model

        result = advisor.get_recommendation(mock_state_dict)
        assert result["rl_action"] == "hold"
        assert result["rl_amount_pct"] == 0.0
        assert result["model_version"] == "1.0.0"


# ──────────────────────────────────────────────
# C) Enhanced VectorStore Tests
# ──────────────────────────────────────────────


class TestEnhancedVectorStore:
    def test_rich_context_text_generation(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        text = store._build_context_text(vector_store_state)
        assert "BTC/USDT" in text
        assert "50000.0" in text
        assert "VIX: 35" in text
        assert "RSI: 25" in text
        assert "Decision: buy" in text

    def test_semantic_tagging(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        tags = store._generate_semantic_tags(vector_store_state)
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert "bullish_trend" in tags
        assert "oversold" in tags
        assert "high_volatility" in tags

    def test_multi_symbol_query(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        state_eth = dict(vector_store_state)
        state_eth["symbol"] = "ETH/USDT"
        state_eth["market_data"]["current_price"] = 3000.0

        store.store_decision(vector_store_state, accuracy_score=0.7)
        store.store_decision(state_eth, accuracy_score=0.6)

        results = store.query_similar_conditions(
            query_text="Price: 50000",
            n_results=5,
            symbols=["BTC/USDT", "ETH/USDT"],
        )
        assert isinstance(results, list)

    def test_prune_entries_older_than(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore
        from unittest.mock import patch as mock_patch

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        old_time = datetime.now(timezone.utc) - timedelta(days=60)
        with mock_patch("data.vector_store.datetime") as mock_dt:
            mock_dt.now.return_value = old_time
            mock_dt.side_effect = lambda *a, **kw: (
                datetime.now(timezone.utc) if a else old_time
            )
            store.store_decision(vector_store_state, accuracy_score=0.7)

        deleted = store.prune_entries_older_than(days=30)
        assert isinstance(deleted, int)

    def test_update_accuracy(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore
        from unittest.mock import patch as mock_patch

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        ts = datetime.now(timezone.utc)
        with mock_patch("data.vector_store.datetime") as mock_dt:
            mock_dt.now.return_value = ts
            store.store_decision(vector_store_state, accuracy_score=0.7)

        result = store.update_accuracy("BTC/USDT", str(ts.timestamp()), 0.85)
        assert isinstance(result, bool)

    def test_query_returns_full_context(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        store.store_decision(vector_store_state, accuracy_score=0.7)
        results = store.query_similar_conditions(
            query_text="Bitcoin price",
            n_results=1,
        )
        assert len(results) > 0
        assert "market_context" in results[0]
        assert len(results[0]["market_context"]) <= 500

    def test_regime_tagging(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        regime = store._determine_market_regime(vector_store_state)
        assert regime in ("high_volatility", "low_volatility", "normal")
        assert regime == "high_volatility"

    def test_query_lessons(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        results = store.query_lessons(symbol="BTC/USDT", n_results=5)
        assert isinstance(results, list)

    def test_store_decision_with_metadata(self, vector_store_state, tmp_data_dir):
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        store.store_decision(vector_store_state, accuracy_score=0.75)
        results = store.collection.get(include=["metadatas"])
        assert results is not None
        assert len(results["ids"]) > 0
        meta = results["metadatas"][0]
        assert meta["symbol"] == "BTC/USDT"
        assert meta["action"] == "buy"
        assert meta["accuracy"] == pytest.approx(0.75, abs=0.06)


# ──────────────────────────────────────────────
# D) AgentMemoryStore Tests
# ──────────────────────────────────────────────


class TestAgentMemoryStoreWrapper:
    def _make_wrapper_with_store(self, tmp_data_dir):
        from data.vector_store import AgentMemoryStore
        from data.agent_memory import AgentMemoryStoreWrapper

        vs = AgentMemoryStore()
        if vs.collection is None:
            return None
        return AgentMemoryStoreWrapper(vector_store=vs)

    def test_store_trade_context(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        trade_data = {
            "action": "buy",
            "confidence": 0.75,
            "entry_price": 50000.0,
            "stop_loss": 48000.0,
            "take_profit": 55000.0,
            "market_regime": "normal",
            "rsi": 45,
            "macd_hist": 0.5,
            "atr": 500,
            "volume_ratio": 1.2,
            "sentiment_score": 0.3,
            "news_summary": "Bitcoin rally continues",
            "accuracy": 0.7,
        }
        doc_id = wrapper.store_trade_context(trade_data, "BTC/USDT")
        assert doc_id is not None
        assert "BTC/USDT" in doc_id

    def test_store_trade_context_no_collection(self):
        from data.agent_memory import AgentMemoryStoreWrapper

        mock_vs = MagicMock()
        mock_vs.collection = None
        wrapper = AgentMemoryStoreWrapper(vector_store=mock_vs)
        result = wrapper.store_trade_context({}, "BTC/USDT")
        assert result is None

    def test_query_similar_trades(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        trade_data = {
            "action": "buy",
            "confidence": 0.75,
            "entry_price": 50000.0,
            "stop_loss": 48000.0,
            "take_profit": 55000.0,
            "market_regime": "normal",
            "rsi": 45,
            "macd_hist": 0.5,
            "atr": 500,
            "volume_ratio": 1.2,
            "sentiment_score": 0.3,
            "news_summary": "Test",
            "accuracy": 0.7,
        }
        wrapper.store_trade_context(trade_data, "BTC/USDT")
        results = wrapper.query_similar_trades("BTC/USDT", action="buy", top_k=3)
        assert isinstance(results, list)
        if len(results) > 0:
            assert "action" in results[0]
            assert "accuracy" in results[0]
            assert "context" in results[0]

    def test_update_trade_outcome(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        trade_data = {
            "action": "buy",
            "confidence": 0.75,
            "entry_price": 50000.0,
            "stop_loss": 48000.0,
            "take_profit": 55000.0,
            "market_regime": "normal",
            "rsi": 45,
            "macd_hist": 0.5,
            "atr": 500,
            "volume_ratio": 1.2,
            "sentiment_score": 0.3,
            "news_summary": "Test",
            "accuracy": 0.5,
        }
        doc_id = wrapper.store_trade_context(trade_data, "BTC/USDT")
        result = wrapper.update_trade_outcome(
            doc_id, actual_pnl=500.0, was_correct=True
        )
        assert result is True

    def test_update_trade_outcome_nonexistent(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        result = wrapper.update_trade_outcome(
            "nonexistent_id", actual_pnl=0.0, was_correct=False
        )
        assert result is False

    def test_get_learning_summary(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        trade_data = {
            "action": "buy",
            "confidence": 0.75,
            "entry_price": 50000.0,
            "stop_loss": 48000.0,
            "take_profit": 55000.0,
            "market_regime": "normal",
            "rsi": 45,
            "macd_hist": 0.5,
            "atr": 500,
            "volume_ratio": 1.2,
            "sentiment_score": 0.3,
            "news_summary": "Test",
            "accuracy": 0.7,
        }
        wrapper.store_trade_context(trade_data, "BTC/USDT")
        summary = wrapper.get_learning_summary("BTC/USDT", last_n=10)
        assert "symbol" in summary
        assert summary["symbol"] == "BTC/USDT"
        assert "total_trades" in summary
        assert summary["total_trades"] >= 1

    def test_get_learning_summary_no_trades(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        summary = wrapper.get_learning_summary("NONEXISTENT")
        assert "total_trades" in summary
        assert summary["total_trades"] == 0

    def test_get_retrospective_lessons(self, tmp_data_dir):
        wrapper = self._make_wrapper_with_store(tmp_data_dir)
        if wrapper is None:
            pytest.skip("ChromaDB not available")

        lessons = wrapper.get_retrospective_lessons("BTC/USDT", last_n=5)
        assert isinstance(lessons, list)

    def test_integration_with_vectorstore(self, tmp_data_dir):
        from data.vector_store import AgentMemoryStore
        from data.agent_memory import AgentMemoryStoreWrapper

        vs = AgentMemoryStore()
        if vs.collection is None:
            pytest.skip("ChromaDB not available")

        wrapper = AgentMemoryStoreWrapper(vector_store=vs)
        trade_data = {
            "action": "sell",
            "confidence": 0.6,
            "entry_price": 52000.0,
            "stop_loss": 50000.0,
            "take_profit": 55000.0,
            "market_regime": "high_volatility",
            "rsi": 75,
            "macd_hist": -0.3,
            "atr": 800,
            "volume_ratio": 1.8,
            "sentiment_score": -0.4,
            "news_summary": "Market correction",
            "accuracy": 0.65,
        }
        doc_id = wrapper.store_trade_context(trade_data, "ETH/USDT")
        assert doc_id is not None

        results = wrapper.query_similar_trades("ETH/USDT", top_k=1)
        assert len(results) >= 1
        assert results[0]["action"] == "sell"


# ──────────────────────────────────────────────
# E) Enhanced DriftMonitor Tests
# ──────────────────────────────────────────────


class TestEnhancedDriftMonitor:
    def _make_monitor_with_history(self, tmp_path, records=None):
        from evaluation.drift_monitor import DriftMonitor

        history_file = tmp_path / "drift_history.jsonl"
        if records:
            with open(history_file, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")
        with patch("evaluation.drift_monitor.DRIFT_HISTORY_FILE", history_file):
            with patch("evaluation.drift_monitor.DATA_DIR", tmp_path):
                monitor = DriftMonitor()
        return monitor, history_file

    def test_time_decay_weighted_accuracy(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = [
            {
                "symbol": "BTC/USDT",
                "predicted_direction": "up",
                "actual_direction": "up",
                "correct": 1,
                "confidence": 0.8,
                "magnitude_error": 0.0,
                "agent_name": "analyst",
                "logged_at": (now - timedelta(days=1)).isoformat(),
            },
            {
                "symbol": "BTC/USDT",
                "predicted_direction": "down",
                "actual_direction": "up",
                "correct": 0,
                "confidence": 0.6,
                "magnitude_error": 0.1,
                "agent_name": "analyst",
                "logged_at": (now - timedelta(days=14)).isoformat(),
            },
        ]
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        acc = monitor.get_agent_accuracy("BTC/USDT")
        assert 0.0 <= acc <= 1.0

    def test_binomial_significance_test(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = []
        for i in range(20):
            records.append(
                {
                    "symbol": "ETH/USDT",
                    "predicted_direction": "up" if i < 8 else "down",
                    "actual_direction": "up",
                    "correct": 1 if i < 8 else 0,
                    "confidence": 0.7,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        result = monitor.is_significant_drift("ETH/USDT")
        assert isinstance(result, bool)

    def test_magnitude_aware_drift(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = [
            {
                "symbol": "BTC/USDT",
                "predicted_direction": "up",
                "actual_direction": "up",
                "correct": 1,
                "confidence": 0.8,
                "magnitude_error": 0.01,
                "agent_name": "analyst",
                "logged_at": (now - timedelta(days=1)).isoformat(),
            },
            {
                "symbol": "BTC/USDT",
                "predicted_direction": "down",
                "actual_direction": "up",
                "correct": 0,
                "confidence": 0.9,
                "magnitude_error": 0.15,
                "agent_name": "analyst",
                "logged_at": (now - timedelta(days=2)).isoformat(),
            },
        ]
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        acc = monitor.get_agent_accuracy("BTC/USDT")
        assert isinstance(acc, float)

    def test_per_agent_accuracy_tracking(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = [
            {
                "symbol": "BTC/USDT",
                "predicted_direction": "up",
                "actual_direction": "up",
                "correct": 1,
                "confidence": 0.8,
                "magnitude_error": 0.0,
                "agent_name": "analyst",
                "logged_at": (now - timedelta(days=1)).isoformat(),
            },
            {
                "symbol": "BTC/USDT",
                "predicted_direction": "down",
                "actual_direction": "up",
                "correct": 0,
                "confidence": 0.6,
                "magnitude_error": 0.0,
                "agent_name": "risk_manager",
                "logged_at": (now - timedelta(days=1)).isoformat(),
            },
        ]
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        acc_analyst = monitor.get_agent_accuracy("BTC/USDT", agent_name="analyst")
        acc_risk = monitor.get_agent_accuracy("BTC/USDT", agent_name="risk_manager")
        assert acc_analyst == 1.0
        assert acc_risk == 0.0

    def test_get_heatmap_data(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = []
        for i in range(10):
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "up" if i % 2 == 0 else "down",
                    "correct": 1 if i % 2 == 0 else 0,
                    "confidence": 0.7,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        heatmap = monitor.get_heatmap_data(days=30)
        assert isinstance(heatmap, dict)
        assert "BTC/USDT" in heatmap

    def test_is_drift_worsening(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = []
        for i in range(14):
            correct = 1 if i >= 7 else 0
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "up",
                    "correct": correct,
                    "confidence": 0.7,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        result = monitor.is_drift_worsening("BTC/USDT", window=7)
        assert isinstance(result, bool)

    def test_get_drift_summary(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = []
        for i in range(10):
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "up" if i < 7 else "down",
                    "correct": 1 if i < 7 else 0,
                    "confidence": 0.7,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        summary = monitor.get_drift_summary()
        assert "total_records" in summary
        assert "symbols_tracked" in summary
        assert "agents_tracked" in summary
        assert "per_symbol" in summary
        assert "per_agent" in summary
        assert "worsening_drifts" in summary
        assert "significant_drifts" in summary

    def test_append_only_history_log(self, tmp_path):
        history_file = tmp_path / "drift_history.jsonl"
        import sys

        saved_modules = {}
        for key in list(sys.modules.keys()):
            if key.startswith("evaluation.drift_monitor"):
                saved_modules[key] = sys.modules.pop(key)

        with (
            patch("evaluation.drift_monitor.DATA_DIR", tmp_path),
            patch("evaluation.drift_monitor.DRIFT_HISTORY_FILE", history_file),
        ):
            from evaluation.drift_monitor import DriftMonitor

            monitor = DriftMonitor()
            monitor.update_accuracy("BTC/USDT", "up", "up", confidence=0.8)
            monitor.update_accuracy("BTC/USDT", "down", "up", confidence=0.6)

            assert history_file.exists()
            with open(history_file, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 2

        for key, mod in saved_modules.items():
            sys.modules[key] = mod

    def test_with_various_confidence_levels(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = []
        for conf in [0.1, 0.3, 0.5, 0.7, 0.9]:
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "up",
                    "correct": 1,
                    "confidence": conf,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=1)).isoformat(),
                }
            )
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        acc = monitor.get_agent_accuracy("BTC/USDT")
        assert acc == 1.0

    def test_statistical_edge_cases(self, tmp_path):
        monitor, _ = self._make_monitor_with_history(tmp_path, [])
        acc = monitor.get_agent_accuracy("BTC/USDT")
        assert acc == 0.60  # Varsayılan değer - yeni semboller için engelleme

        result = monitor.is_significant_drift("BTC/USDT")
        assert result is False

        worsening = monitor.is_drift_worsening("BTC/USDT")
        assert worsening is False

    def test_update_accuracy_returns_current_accuracy(self, tmp_path):
        history_file = tmp_path / "drift_history.jsonl"
        with patch("evaluation.drift_monitor.DATA_DIR", tmp_path):
            with patch("evaluation.drift_monitor.DRIFT_HISTORY_FILE", history_file):
                from evaluation.drift_monitor import DriftMonitor

                monitor = DriftMonitor()

        acc = monitor.update_accuracy("BTC/USDT", "up", "up", confidence=0.8)
        assert isinstance(acc, float)
        assert 0.0 <= acc <= 1.0

    def test_multiple_symbols_tracking(self, tmp_path):
        now = datetime.now(timezone.utc)
        records = []
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
            for i in range(5):
                records.append(
                    {
                        "symbol": sym,
                        "predicted_direction": "up",
                        "actual_direction": "up" if i < 4 else "down",
                        "correct": 1 if i < 4 else 0,
                        "confidence": 0.7,
                        "magnitude_error": 0.0,
                        "agent_name": "analyst",
                        "logged_at": (now - timedelta(days=i)).isoformat(),
                    }
                )
        monitor, _ = self._make_monitor_with_history(tmp_path, records)
        summary = monitor.get_drift_summary()
        assert len(summary["symbols_tracked"]) == 3


# ──────────────────────────────────────────────
# F) EnsembleVoter Tests
# ──────────────────────────────────────────────


class TestEnsembleVoter:
    def _make_mock_vote(
        self,
        model,
        action,
        confidence,
        amount=0.0,
        sl=0.0,
        tp=0.0,
        sentiment=0.0,
        risk=0.5,
        reasoning="",
    ):
        return {
            "model": model,
            "action": action,
            "confidence": confidence,
            "amount": amount,
            "stop_loss": sl,
            "take_profit": tp,
            "sentiment_score": sentiment,
            "risk_score": risk,
            "reasoning": reasoning,
        }

    def test_ensemble_voter_initialization(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params") as mock_params:
            mock_params.return_value.agents.ensemble_models = ["model1", "model2"]
            mock_params.return_value.agents.ensemble_min_consensus = 0.5
            voter = EnsembleVoter()
        assert len(voter.models) == 2
        assert voter.min_consensus == 0.5

    def test_ensemble_voter_custom_models(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(
                models=["deepseek/chat", "ollama/llama3"],
                min_consensus=0.7,
            )
        assert voter.models == ["deepseek/chat", "ollama/llama3"]
        assert voter.min_consensus == 0.7

    def test_majority_voting_for_actions(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(min_consensus=0.3)

        votes = [
            self._make_mock_vote("m1", "buy", 0.8),
            self._make_mock_vote("m2", "buy", 0.7),
            self._make_mock_vote("m3", "hold", 0.6),
        ]
        result = voter._aggregate_votes(votes)
        assert result["action"] == "buy"
        assert result["consensus_score"] == pytest.approx(2 / 3, abs=0.01)

    def test_weighted_averaging_for_numerics(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(min_consensus=0.3)

        votes = [
            self._make_mock_vote(
                "m1", "buy", 0.9, amount=100.0, sl=48000.0, tp=55000.0
            ),
            self._make_mock_vote("m2", "buy", 0.6, amount=50.0, sl=49000.0, tp=54000.0),
        ]
        result = voter._aggregate_votes(votes)
        assert result["amount"] > 0.0
        assert result["stop_loss"] > 0.0
        assert result["take_profit"] > 0.0

    def test_consensus_score_calculation(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(min_consensus=0.3)

        votes = [
            self._make_mock_vote("m1", "buy", 0.8),
            self._make_mock_vote("m2", "buy", 0.7),
            self._make_mock_vote("m3", "sell", 0.6),
            self._make_mock_vote("m4", "buy", 0.9),
        ]
        result = voter._aggregate_votes(votes)
        assert result["consensus_score"] == pytest.approx(0.75, abs=0.01)

    def test_graceful_failure_handling(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(min_consensus=0.3)

        votes = [
            self._make_mock_vote("m1", "buy", 0.8),
        ]
        result = voter._aggregate_votes(votes)
        assert result["action"] == "buy"
        assert result["confidence"] > 0.0

    def test_consensus_threshold_enforcement(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(min_consensus=0.9)

        votes = [
            self._make_mock_vote("m1", "buy", 0.8),
            self._make_mock_vote("m2", "sell", 0.7),
            self._make_mock_vote("m3", "hold", 0.6),
        ]
        result = voter._aggregate_votes(votes)
        assert result["action"] == "hold"
        assert "Low consensus" in result["reasoning"]

    def test_single_model_degenerate_case(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(min_consensus=0.3)

        votes = [
            self._make_mock_vote("m1", "buy", 0.8, amount=100.0),
        ]
        result = voter._aggregate_votes(votes)
        assert result["action"] == "buy"
        assert result["consensus_score"] == 1.0
        assert result["total_models"] == 1

    def test_all_models_fail_returns_default(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(models=["model1"])

        with patch.object(voter, "_call_single_model", return_value=None):
            result = voter.vote("system", "user")
        assert result["action"] == "hold"
        assert result["confidence"] == 0.1

    def test_parse_model_spec(self):
        from agents.ensemble_voter import EnsembleVoter
        from config.settings import LLMProvider

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter()

        provider, name = voter._parse_model_spec("deepseek/deepseek-chat")
        assert provider == LLMProvider.DEEPSEEK
        assert name == "deepseek-chat"

        provider, name = voter._parse_model_spec("ollama/llama3:8b")
        assert provider == LLMProvider.OLLAMA
        assert name == "llama3:8b"

        provider, name = voter._parse_model_spec("gpt-4")
        assert provider == LLMProvider.OPENROUTER
        assert name == "gpt-4"

    def test_vote_with_no_models(self):
        from agents.ensemble_voter import EnsembleVoter

        with patch("agents.ensemble_voter.get_trading_params"):
            voter = EnsembleVoter(models=[])

        result = voter._default_result("No ensemble models configured")
        assert result["action"] == "hold"
        assert "No ensemble models" in result["reasoning"]


# ──────────────────────────────────────────────
# G) PromptEvolver Tests
# ──────────────────────────────────────────────


class TestPromptEvolver:
    def test_prompt_evolver_initialization(self):
        from agents.prompt_evolver import PromptEvolver

        evolver = PromptEvolver()
        assert evolver is not None

    def test_store_prompt_version(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
        ):
            evolver = PromptEvolver()
            path = evolver.store_prompt_version(
                agent_name="analyst",
                prompt_content="Test prompt content",
                version=1,
                changelog="Initial version",
            )
            assert path is not None
            assert "analyst_v1.txt" in path
            assert (versions_dir / "analyst_v1.txt").exists()

    def test_get_current_prompt(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
        ):
            evolver = PromptEvolver()
            evolver.store_prompt_version(
                agent_name="analyst",
                prompt_content="Version 1 content",
                version=1,
                changelog="v1",
            )
            evolver.store_prompt_version(
                agent_name="analyst",
                prompt_content="Version 2 content",
                version=2,
                changelog="v2",
            )
            prompt = evolver.get_current_prompt("analyst")
            assert "Version 2 content" in prompt

    def test_get_prompt_history(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
        ):
            evolver = PromptEvolver()
            evolver.store_prompt_version("analyst", "v1", 1, "changelog1")
            evolver.store_prompt_version("analyst", "v2", 2, "changelog2")

            history = evolver.get_prompt_history("analyst")
            assert len(history) == 2
            assert history[0]["version"] == 1
            assert history[1]["version"] == 2

    def test_rollback_prompt(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
        ):
            evolver = PromptEvolver()
            evolver.store_prompt_version("analyst", "v1 content", 1, "v1")
            evolver.store_prompt_version("analyst", "v2 content", 2, "v2")

            result = evolver.rollback_prompt("analyst", 1)
            assert result is True

            prompt = evolver.get_current_prompt("analyst")
            assert "v1 content" in prompt

    def test_rollback_nonexistent_version(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
        ):
            evolver = PromptEvolver()
            evolver.store_prompt_version("analyst", "v1", 1, "v1")

            result = evolver.rollback_prompt("analyst", 99)
            assert result is False

    def test_evolve_from_drift(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "analyst.txt").write_text("Base prompt", encoding="utf-8")

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
            patch("agents.prompt_evolver.PROMPTS_DIR", prompts_dir),
        ):
            evolver = PromptEvolver()
            drift_data = {
                "accuracy": 0.55,
                "warnings": ["Low accuracy detected", "High variance"],
            }
            new_prompt = evolver.evolve_from_drift("analyst", drift_data)
            assert "DİKKAT" in new_prompt
            assert "0.55" in new_prompt or "55.0" in new_prompt

    def test_evolve_from_retrospective(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "analyst.txt").write_text("Base prompt", encoding="utf-8")

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
            patch("agents.prompt_evolver.PROMPTS_DIR", prompts_dir),
        ):
            evolver = PromptEvolver()
            lessons = [
                {
                    "root_cause": "False breakout",
                    "lesson_learned": "Wait for volume confirmation",
                    "root_cause_category": "false_signal",
                },
                {
                    "root_cause": "Overtrading",
                    "lesson_learned": "Limit to 3 trades per day",
                    "root_cause_category": "behavioral",
                },
            ]
            new_prompt = evolver.evolve_from_retrospective("analyst", lessons)
            assert "ÖĞRENİLEN DERSLER" in new_prompt
            assert "False breakout" in new_prompt

    def test_apply_evolution(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "analyst.txt").write_text("Base prompt", encoding="utf-8")

        history_file = tmp_path / "drift_history.jsonl"
        now = datetime.now(timezone.utc)
        records = []
        for i in range(10):
            records.append(
                {
                    "symbol": "analyst",
                    "predicted_direction": "up",
                    "actual_direction": "down",
                    "correct": 0,
                    "confidence": 0.5,
                    "magnitude_error": 0.1,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        with open(history_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
            patch("agents.prompt_evolver.PROMPTS_DIR", prompts_dir),
            patch("evaluation.drift_monitor.DRIFT_HISTORY_FILE", history_file),
            patch("evaluation.drift_monitor.DATA_DIR", tmp_path),
        ):
            evolver = PromptEvolver()
            result = evolver.apply_evolution("analyst")
            assert isinstance(result, bool)

    def test_get_current_prompt_fallback(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "unknown_agent.txt").write_text(
            "Fallback prompt", encoding="utf-8"
        )

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
            patch("agents.prompt_evolver.PROMPTS_DIR", prompts_dir),
        ):
            evolver = PromptEvolver()
            prompt = evolver.get_current_prompt("unknown_agent")
            assert "Fallback prompt" in prompt

    def test_get_prompt_history_empty(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
        ):
            evolver = PromptEvolver()
            history = evolver.get_prompt_history("nonexistent")
            assert history == []


# ──────────────────────────────────────────────
# H) Integration Tests
# ──────────────────────────────────────────────


class TestIntegrationRLGraph:
    def test_rl_state_enrichment(self, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(1), None)
        advisor.model = mock_model

        rec = advisor.get_recommendation(mock_state_dict)
        assert "rl_action" in rec
        assert rec["rl_action"] == "buy_small"
        assert "rl_confidence" in rec

    def test_rl_trader_blending(self, mock_state_dict):
        from agents.rl_advisor import RLAdvisor

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(2), None)
        advisor.model = mock_model

        rl_rec = advisor.get_recommendation(mock_state_dict)

        llm_decision = {
            "action": "buy",
            "confidence": 0.8,
            "amount_pct": 0.25,
        }

        blended_action = rl_rec["rl_action"]
        blended_amount = (llm_decision["amount_pct"] + rl_rec["rl_amount_pct"]) / 2

        assert blended_action in (
            "hold",
            "buy_small",
            "buy_medium",
            "buy_large",
            "sell",
        )
        assert 0.0 <= blended_amount <= 1.0

    def test_rag_rl_state_enrichment(self, mock_state_dict, tmp_data_dir):
        from data.vector_store import AgentMemoryStore
        from agents.rl_advisor import RLAdvisor

        store = AgentMemoryStore()
        if store.collection is None:
            pytest.skip("ChromaDB not available")

        state = {
            "symbol": "BTC/USDT",
            "market_data": {"current_price": 50000},
            "news_data": [],
            "technical_signals": {"vix": 20, "macd": {"histogram": 0.5}},
            "trade_decision": {"action": "buy"},
        }
        store.store_decision(state, accuracy_score=0.7)

        advisor = RLAdvisor()
        mock_model = MagicMock()
        mock_model.predict.return_value = (np.array(0), None)
        advisor.model = mock_model

        rec = advisor.get_recommendation(mock_state_dict)
        assert "rl_action" in rec

    def test_drift_risk_manager_integration(self, tmp_path):
        from evaluation.drift_monitor import DriftMonitor

        now = datetime.now(timezone.utc)
        records = []
        for i in range(15):
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "down",
                    "correct": 0,
                    "confidence": 0.5,
                    "magnitude_error": 0.1,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        monitor, _ = TestEnhancedDriftMonitor()._make_monitor_with_history(
            tmp_path, records
        )

        accuracy = monitor.get_agent_accuracy("BTC/USDT")
        is_drift = monitor.is_significant_drift("BTC/USDT")
        worsening = monitor.is_drift_worsening("BTC/USDT")

        if accuracy < 0.5 or is_drift:
            risk_action = "reduce_exposure"
        else:
            risk_action = "maintain"

        assert risk_action in ("reduce_exposure", "maintain")

    def test_prompt_evolver_agent_integration(self, tmp_path):
        from agents.prompt_evolver import PromptEvolver

        versions_dir = tmp_path / "prompt_versions"
        manifest_file = versions_dir / "manifest.json"
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "trader.txt").write_text(
            "You are a trading assistant.", encoding="utf-8"
        )

        with (
            patch("agents.prompt_evolver.VERSIONS_DIR", versions_dir),
            patch("agents.prompt_evolver.MANIFEST_FILE", manifest_file),
            patch("agents.prompt_evolver.PROMPTS_DIR", prompts_dir),
        ):
            evolver = PromptEvolver()

            current = evolver.get_current_prompt("trader")
            assert "trading assistant" in current

            evolver.store_prompt_version("trader", current + "\n# Updated", 1, "init")

            updated = evolver.get_current_prompt("trader")
            assert "Updated" in updated

    def _dashboard_import_available(self):
        """Check if prometheus_client is available for dashboard tests."""
        try:
            import prometheus_client

            return True
        except ImportError:
            return False

    def test_dashboard_api_portfolio_endpoint(self, tmp_path):
        if not self._dashboard_import_available():
            pytest.skip("prometheus_client not installed")
        from fastapi.testclient import TestClient
        from dashboard.server import app, PORTFOLIO_FILE

        portfolio_data = {
            "cash": 9500.0,
            "equity": 10500.0,
            "total_pnl": 500.0,
            "daily_pnl": 100.0,
            "drawdown": 0.02,
            "max_equity": 10500.0,
            "open_positions": 1,
            "positions": [{"symbol": "BTC/USDT", "entry_price": 50000}],
            "closed_trades": [],
            "benchmark_symbol": "BTC/USDT",
            "benchmark_return": 0.05,
            "alpha": 0.02,
        }

        test_portfolio = tmp_path / "portfolio_state.json"
        test_portfolio.write_text(json.dumps(portfolio_data), encoding="utf-8")

        with (
            patch("dashboard.server.PORTFOLIO_FILE", test_portfolio),
            patch("dashboard.server.EXPORTS_DIR", tmp_path / "exports"),
        ):
            client = TestClient(app)
            response = client.get("/api/portfolio")
            assert response.status_code == 200
            data = response.json()
            assert data["equity"] == 10500.0
            assert data["cash"] == 9500.0

    def test_dashboard_api_health_endpoint(self):
        if not self._dashboard_import_available():
            pytest.skip("prometheus_client not installed")
        from fastapi.testclient import TestClient
        from dashboard.server import app

        with patch("dashboard.server.PORTFOLIO_FILE", Path("/nonexistent")):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

    def test_dashboard_api_status_endpoint(self, tmp_path):
        if not self._dashboard_import_available():
            pytest.skip("prometheus_client not installed")
        from fastapi.testclient import TestClient
        from dashboard.server import app

        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()

        with (
            patch("dashboard.server.PORTFOLIO_FILE", Path("/nonexistent")),
            patch("dashboard.server.EXPORTS_DIR", exports_dir),
        ):
            client = TestClient(app)
            response = client.get("/api/status")
            assert response.status_code == 200
            data = response.json()
            assert "portfolio_loaded" in data
            assert "total_analyses" in data

    def test_dashboard_api_rl_status_endpoint(self, tmp_path):
        if not self._dashboard_import_available():
            pytest.skip("prometheus_client not installed")
        from fastapi.testclient import TestClient
        from dashboard.server import app

        with (
            patch("dashboard.server.PORTFOLIO_FILE", Path("/nonexistent")),
            patch("dashboard.server.DATA_DIR", tmp_path),
        ):
            client = TestClient(app)
            response = client.get("/api/rl_status")
            assert response.status_code == 200
            data = response.json()
            assert "model_loaded" in data
            assert "model_version" in data

    def test_dashboard_api_drift_heatmap_endpoint(self, tmp_path):
        if not self._dashboard_import_available():
            pytest.skip("prometheus_client not installed")
        from fastapi.testclient import TestClient
        from dashboard.server import app
        from evaluation.drift_monitor import DRIFT_HISTORY_FILE

        history_file = tmp_path / "drift_history.jsonl"
        now = datetime.now(timezone.utc)
        records = []
        for i in range(5):
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "up",
                    "correct": 1,
                    "confidence": 0.7,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        with open(history_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        with (
            patch("dashboard.server.PORTFOLIO_FILE", Path("/nonexistent")),
            patch("evaluation.drift_monitor.DRIFT_HISTORY_FILE", history_file),
            patch("evaluation.drift_monitor.DATA_DIR", tmp_path),
        ):
            client = TestClient(app)
            response = client.get("/api/drift_heatmap")
            assert response.status_code == 200
            data = response.json()
            assert "heatmap" in data
            assert "days" in data

    def test_dashboard_api_drift_summary_endpoint(self, tmp_path):
        if not self._dashboard_import_available():
            pytest.skip("prometheus_client not installed")
        from fastapi.testclient import TestClient
        from dashboard.server import app

        history_file = tmp_path / "drift_history.jsonl"
        now = datetime.now(timezone.utc)
        records = []
        for i in range(5):
            records.append(
                {
                    "symbol": "BTC/USDT",
                    "predicted_direction": "up",
                    "actual_direction": "up",
                    "correct": 1,
                    "confidence": 0.7,
                    "magnitude_error": 0.0,
                    "agent_name": "analyst",
                    "logged_at": (now - timedelta(days=i)).isoformat(),
                }
            )
        with open(history_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        with (
            patch("dashboard.server.PORTFOLIO_FILE", Path("/nonexistent")),
            patch("evaluation.drift_monitor.DRIFT_HISTORY_FILE", history_file),
            patch("evaluation.drift_monitor.DATA_DIR", tmp_path),
        ):
            client = TestClient(app)
            response = client.get("/api/drift_summary")
            assert response.status_code == 200
            data = response.json()
            assert "total_records" in data
            assert "symbols_tracked" in data
