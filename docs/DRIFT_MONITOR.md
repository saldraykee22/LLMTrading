# Drift Monitor System

## Overview

The Drift Monitor tracks LLM prediction accuracy over time to detect concept drift — when the model's predictions become less aligned with actual market outcomes. It provides statistical rigor, time-aware weighting, and dashboard-ready data.

## Core Concepts

### Time-Decay Weighted Accuracy

Recent predictions matter more than old ones. The system uses exponential decay with a configurable half-life (default: 7 days).

**Formula:**
```
weight = exp(-ln(2) * age_seconds / half_life_seconds)
```

A prediction from 7 days ago counts half as much as today's prediction. After 14 days, it counts as 1/4, and so on.

**Why:** Market regimes change. A model that was accurate during a bull market may not be accurate during a crash. Time-decay automatically adapts to this.

### Statistical Significance Testing

Uses a binomial test to determine if observed accuracy is significantly below random chance (50%).

**How it works:**
- Null hypothesis: the model is no better than random (p = 0.5)
- Calculates the cumulative probability of observing `k` or fewer successes in `n` trials
- If p-value < threshold (default 0.05), drift is statistically significant

**Minimum data:** At least 5 weighted observations are required before the test runs. This prevents false alarms from sparse data.

### Magnitude-Aware Drift

Beyond binary correct/incorrect, the system tracks:
- `confidence`: how confident the model was (0.0-1.0)
- `magnitude_error`: how far off the prediction was

These are stored in the history log for future analysis and can be used to compute weighted accuracy scores that penalize high-confidence wrong predictions more heavily.

### Per-Agent Tracking

The system tracks accuracy per agent, not just overall:
- `analyst`: sentiment analysis agent
- `debate`: multi-agent debate consensus
- Any custom agent name

This lets you identify which component is degrading, not just that "the system" is drifting.

## API Reference

### `DriftMonitor(half_life_days=7.0)`

Initialize the drift monitor.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `half_life_days` | float | 7.0 | Half-life for exponential decay in days |

### `update_accuracy(symbol, predicted_direction, actual_direction, confidence=0.5, magnitude_error=0.0, agent_name="analyst") -> float`

Record a prediction outcome and return the updated time-decay accuracy.

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Trading pair (e.g., "BTC/USDT") |
| `predicted_direction` | str | "bullish", "bearish", or "neutral" |
| `actual_direction` | str | Actual market direction |
| `confidence` | float | Model confidence (0.0-1.0) |
| `magnitude_error` | float | How far off the prediction was |
| `agent_name` | str | Which agent made the prediction |

**Returns:** Updated time-decay weighted accuracy (0.0-1.0)

### `get_agent_accuracy(symbol, agent_name=None) -> float`

Get time-decay weighted accuracy for a symbol and optional agent.

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Trading pair |
| `agent_name` | str \| None | Filter by agent, or None for all agents |

**Returns:** Weighted accuracy (0.0-1.0). Returns 1.0 if no data exists.

### `is_significant_drift(symbol, threshold=0.05, agent_name=None) -> bool`

Test if accuracy is statistically significantly below random chance.

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Trading pair |
| `threshold` | float | P-value threshold for significance |
| `agent_name` | str \| None | Filter by agent |

**Returns:** True if drift is statistically significant

### `get_heatmap_data(days=30) -> dict`

Returns per-symbol, per-day accuracy matrix for dashboard visualization.

**Returns:**
```python
{
    "BTC/USDT": {
        "2026-04-01": 0.75,
        "2026-04-02": 0.60,
        ...
    },
    "ETH/USDT": {
        "2026-04-01": 0.80,
        ...
    }
}
```

### `is_drift_worsening(symbol, window=7, agent_name=None) -> bool`

Check if accuracy is declining over time by comparing the most recent window against the previous window.

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Trading pair |
| `window` | int | Days per comparison window |
| `agent_name` | str \| None | Filter by agent |

**Returns:** True if recent accuracy is >5 percentage points below the prior window.

### `get_drift_summary() -> dict`

Complete summary for dashboard display.

**Returns:**
```python
{
    "total_records": 150,
    "symbols_tracked": ["BTC/USDT", "ETH/USDT"],
    "agents_tracked": ["analyst", "debate"],
    "per_symbol": {
        "BTC/USDT": {
            "accuracy": 0.65,
            "significant_drift": False,
            "worsening": True
        }
    },
    "per_agent": {
        "analyst": {"BTC/USDT": 0.65, "ETH/USDT": 0.70},
        "debate": {"BTC/USDT": 0.72}
    },
    "worsening_drifts": ["BTC/USDT"],
    "significant_drifts": [],
    "generated_at": "2026-04-05T12:00:00+00:00"
}
```

## Data Storage

### `data/drift_history.jsonl`

Append-only JSON Lines log. Each record contains:

```json
{
    "symbol": "BTC/USDT",
    "predicted_direction": "bullish",
    "actual_direction": "bearish",
    "correct": 0,
    "confidence": 0.85,
    "magnitude_error": 0.12,
    "agent_name": "analyst",
    "logged_at": "2026-04-05T12:00:00+00:00"
}
```

This file grows over time and is loaded on initialization. Consider periodic archival if it becomes large.

### `data/agent_accuracy.json`

Legacy cache file (maintained for backward compatibility with risk_manager.py).

## Configuration

| Setting | Location | Default | Description |
|---------|----------|---------|-------------|
| Half-life | `DriftMonitor(half_life_days)` | 7.0 | Days for exponential decay half-life |
| Significance threshold | `is_significant_drift(threshold)` | 0.05 | P-value threshold |
| Worsening window | `is_drift_worsening(window)` | 7 | Days per comparison window |
| Heatmap range | `get_heatmap_data(days)` | 30 | Days of history to include |

## Integration with Risk Manager

The risk manager (`agents/risk_manager.py`) uses drift monitor accuracy to gate trades:

- Accuracy < 40%: Trade rejected (critical failure)
- Accuracy 40-60%: Warning added to assessment
- Accuracy > 60%: Check passes

## Interpreting Heatmap Data

The heatmap is a 2D matrix: symbols x dates. Use it to:

1. **Spot patterns**: Is accuracy lower on certain days of the week?
2. **Identify regime changes**: Sudden drops across all symbols suggest market regime shift
3. **Compare agents**: Side-by-side accuracy for the same symbol reveals which agent performs better
4. **Color coding**: Green (>70%), Yellow (50-70%), Red (<50%)

## Example Usage

```python
from evaluation.drift_monitor import DriftMonitor

monitor = DriftMonitor(half_life_days=7.0)

# Record a prediction outcome
accuracy = monitor.update_accuracy(
    symbol="BTC/USDT",
    predicted_direction="bullish",
    actual_direction="bearish",
    confidence=0.85,
    magnitude_error=0.12,
    agent_name="analyst"
)

# Check for significant drift
if monitor.is_significant_drift("BTC/USDT"):
    print("Warning: statistically significant drift detected!")

# Check if drift is worsening
if monitor.is_drift_worsening("BTC/USDT"):
    print("Accuracy is declining over time")

# Get dashboard data
summary = monitor.get_drift_summary()
heatmap = monitor.get_heatmap_data(days=30)
```
