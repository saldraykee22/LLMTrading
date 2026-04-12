# RL Advisor — Reinforcement Learning Trading System

## Overview

The RL Advisor integrates a PPO (Proximal Policy Optimization) reinforcement learning agent into the multi-agent trading pipeline. It runs **after** risk management approval and **before** the trader node, providing data-driven trade recommendations that are blended with the LLM's decision.

### Graph Flow

```
coordinator → research_analyst → debate → risk_manager
                                       │
                         ┌─────────────┴─────────────┐
                         ↓                           ↓
                     (Approved)                  (Rejected)
                         ↓                           ↓
                    rl_advisor → trader      hold_decision → END
```

## Components

### 1. TradingEnv (`agents/rl_environment.py`)

A custom Gymnasium environment that simulates trading for PPO training.

**Observation Space (15-dimensional):**

| Index | Feature | Range | Description |
|-------|---------|-------|-------------|
| 0 | RSI | [-1, 1] | RSI (0-100) normalized |
| 1 | MACD Histogram | [-1, 1] | MACD histogram / price |
| 2 | ATR | [-1, 1] | ATR normalized by price |
| 3 | EMA20/Price | [-1, 1] | EMA20 to price ratio |
| 4 | Volume Ratio | [-1, 1] | Current volume / 20-day avg |
| 5 | Sentiment Score | [-1, 1] | News/social sentiment |
| 6 | Sentiment Confidence | [0, 1] | Confidence in sentiment |
| 7 | Cash Ratio | [-1, 1] | Cash / equity |
| 8 | Position Count | [-1, 1] | Open positions / max |
| 9 | Drawdown | [-1, 0] | Current drawdown (negative) |
| 10 | RAG Accuracy | [-1, 1] | Similar trade accuracy from vector store |
| 11 | Agent Accuracy | [-1, 1] | LLM accuracy from drift monitor |
| 12 | Position P&L | [-1, 1] | Unrealized P&L of open position |
| 13 | Total P&L | [-1, 1] | Cumulative P&L / equity |
| 14 | Step Progress | [-1, 1] | Current step / max steps |

**Action Space (Discrete 5):**

| Action | Meaning | Size |
|--------|---------|------|
| 0 | hold | 0% |
| 1 | buy_small | 10% of max |
| 2 | buy_medium | 30% of max |
| 3 | buy_large | 60% of max |
| 4 | sell | 100% (close position) |

### 2. RLAdvisor (`agents/rl_advisor.py`)

Wraps the PPO model and integrates with the LangGraph state.

**Methods:**

- `__init__(model_path=None)` — Loads existing PPO model or initializes a new one
- `get_recommendation(state_dict)` → `dict` — Returns RL recommendation from current state
- `train(env, total_timesteps=10000)` — Trains the PPO model on the environment
- `save_model(path)` / `load_model(path)` — Persist/load model weights
- `get_confidence()` → `float` — Returns confidence based on action probability distribution

**Output Format:**

```python
{
    "rl_action": "buy_medium",       # hold | buy_small | buy_medium | buy_large | sell
    "rl_amount_pct": 0.30,           # Position size as fraction
    "rl_confidence": 0.82,           # 0.0 - 1.0
    "rl_reasoning": "RL recommends BUY medium ...",
    "model_version": "1.0.0"
}
```

### 3. Reward Function

The reward function combines multiple signals:

| Component | Formula | Purpose |
|-----------|---------|---------|
| **Base P&L** | `pnl * 10.0` (on sell) / `unrealized * 5.0` (on hold) | Direct profit incentive |
| **Drawdown Penalty** | `-exp(drawdown * 10) * 0.5` (if dd > 5%) | Exponential penalty for large drawdowns |
| **Sharpe Bonus** | `clip(sharpe * 0.5, -1, 1)` (after 10 steps) | Risk-adjusted return bonus |
| **RAG Accuracy Bonus** | `+0.2` (if similar trade accuracy > 0.7) | Reward following historically successful patterns |
| **Drift Penalty** | `-0.3` (if agent accuracy < 0.4) | Penalize when LLM accuracy has drifted |

### 4. Decision Blending (`agents/trader.py`)

The trader node blends LLM and RL recommendations based on RL confidence:

| RL Confidence | RL Weight | LLM Weight | Behavior |
|---------------|-----------|------------|----------|
| > 0.7 | 60% | 40% | RL-dominant |
| 0.4 - 0.7 | 50% | 50% | Equal blend |
| < 0.4 | 0% | 100% | LLM only (RL ignored) |
| No RL data | 0% | 100% | LLM only (backward compatible) |

## Training the Model

### Prerequisites

```bash
pip install gymnasium stable-baselines3 torch scikit-learn
```

### Training Script Example

```python
from agents.rl_environment import TradingEnv
from agents.rl_advisor import RLAdvisor

# Prepare historical data
market_data = [...]  # List of state dicts with technical_signals, sentiment, etc.
portfolio = {"equity": 10000, "cash": 10000, "open_positions": 0, "current_drawdown": 0.0}

env = TradingEnv(
    market_data=market_data,
    portfolio_state=portfolio,
    max_steps=100,
    training=True,
)

advisor = RLAdvisor()
advisor.train(env, total_timesteps=50000, save_path="models/ppo_trading.zip")
```

### Loading a Trained Model

```python
from agents.rl_advisor import RLAdvisor

advisor = RLAdvisor(model_path="models/ppo_trading.zip")
recommendation = advisor.get_recommendation(state_dict)
print(recommendation)
```

## Configuration

### Environment Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_steps` | 100 | Steps per episode |
| `training` | True | Training mode (random start) vs inference (sequential) |

### PPO Hyperparameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `learning_rate` | 3e-4 | Learning rate |
| `n_steps` | 512 | Steps per rollout |
| `batch_size` | 64 | Minibatch size |
| `n_epochs` | 10 | Epochs per update |
| `gamma` | 0.99 | Discount factor |
| `gae_lambda` | 0.95 | GAE lambda |
| `clip_range` | 0.2 | PPO clip range |
| `ent_coef` | 0.01 | Entropy coefficient |

## Interpreting RL Confidence

The confidence score is derived from the **maximum action probability** in the PPO policy's output distribution:

- **0.8 - 1.0 (High):** The model is very certain about its recommendation. RL dominates the decision (60% weight).
- **0.4 - 0.8 (Medium):** Moderate certainty. Equal blend with LLM (50/50).
- **0.0 - 0.4 (Low):** The model is uncertain, likely due to unfamiliar market conditions. RL is ignored; LLM decides alone.

**When confidence is low, investigate:**
- Is the market regime different from training data?
- Check drift monitor for LLM accuracy degradation
- Consider retraining with more recent data

## State Enrichment

The RL observation vector is enriched from:

- **Technical Analyzer** (`models/technical_analyzer.py`): RSI, MACD, ATR, EMA20, volume ratio
- **Sentiment Analyzer**: Sentiment score and confidence
- **Portfolio** (`risk/portfolio.py`): Cash ratio, position count, drawdown
- **RAG** (`data/vector_store.py`): Similar trade accuracy from historical decisions
- **Drift Monitor** (`evaluation/drift_monitor.py`): LLM agent accuracy over time
