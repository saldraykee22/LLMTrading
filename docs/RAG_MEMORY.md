# RAG / Memory System Architecture

## Overview

The RAG (Retrieval-Augmented Generation) / Memory system provides historical context to the trading agents by storing past trade decisions, market conditions, and outcomes in a vector database (ChromaDB). When analyzing a new trade, agents query this memory to find similar past situations and learn from previous successes and failures.

## Components

### 1. VectorStore (`data/vector_store.py`)

The core storage layer built on ChromaDB with sentence transformer embeddings (`all-MiniLM-L6-v2`).

#### Key Features

- **Rich Context Text**: Each stored decision includes price, VIX regime, all technical indicators (RSI, MACD, ATR, EMA20, EMA50, SMA200, Bollinger Bands position, volume ratio), top 3 news titles, sentiment score and confidence, and market regime tag.

- **Semantic Tagging**: Automatic tags are generated based on market conditions:
  - Trend: `bullish_trend`, `bearish_trend`
  - RSI: `oversold`, `overbought`
  - MACD: `macd_bullish`, `macd_bearish`
  - Volatility: `high_volatility`, `low_volatility`, `high_atr`
  - Volume: `high_volume`
  - Sentiment: `bullish_sentiment`, `bearish_sentiment`
  - Price levels: `above_sma200`, `below_sma200`, `near_bb_upper`, `near_bb_lower`
  - Calendar: `earnings_season`

- **Market Regime Detection**: Classifies market state as `high_volatility`, `normal`, or `low_volatility` based on VIX and ATR.

- **Multi-Symbol Queries**: Query across specific symbols or all symbols at once.

- **Auto-Pruning**: Remove entries older than a configurable number of days.

- **Retroactive Accuracy Updates**: Update accuracy scores after trade outcomes are known.

#### API

```python
from data.vector_store import AgentMemoryStore

store = AgentMemoryStore()

# Store a trade decision
store.store_decision(state, accuracy_score=0.75)

# Query similar conditions (single symbol from state)
results = store.query_similar_conditions(state, n_results=5)

# Query across multiple symbols
results = store.query_similar_conditions(state, n_results=5, symbols=["BTC/USDT", "ETH/USDT"])

# Query with custom text (no state needed)
results = store.query_similar_conditions(query_text="bullish trend high volume", symbols=["BTC/USDT"])

# Prune old entries
pruned_count = store.prune_entries_older_than(days=30)

# Update accuracy retroactively
store.update_accuracy("BTC/USDT", "1712345678.9", new_accuracy=0.85)
```

### 2. AgentMemoryStoreWrapper (`data/agent_memory.py`)

Higher-level operations wrapping the VectorStore for trade-specific workflows.

#### API

```python
from data.agent_memory import AgentMemoryStoreWrapper

memory = AgentMemoryStoreWrapper()

# Store full trade context
trade_id = memory.store_trade_context(
    trade_data={
        "action": "buy",
        "confidence": 0.8,
        "entry_price": 50000.0,
        "stop_loss": 48000.0,
        "take_profit": 55000.0,
        "market_regime": "normal",
        "rsi": 45,
        "macd_hist": 0.02,
        "atr": 1500,
        "volume_ratio": 1.3,
        "sentiment_score": 0.4,
        "news_summary": "ETF approval rumors",
    },
    symbol="BTC/USDT",
    tags=["breakout_setup"],
)

# Find similar past trades
similar = memory.query_similar_trades(
    symbol="BTC/USDT",
    action="buy",
    regime="normal",
    top_k=5,
)

# Update trade outcome after close
memory.update_trade_outcome(
    trade_id=trade_id,
    actual_pnl=0.05,
    was_correct=True,
)

# Get learning summary
summary = memory.get_learning_summary("BTC/USDT", last_n=20)

# Get retrospective lessons
lessons = memory.get_retrospective_lessons("BTC/USDT", last_n=5)
```

### 3. RetrospectiveAgent (`agents/retrospective_agent.py`)

Analyzes losing trades and stores lessons back into the vector store. Triggered when positions close at a loss.

- Gathers OHLCV and news context from the trade period
- Uses LLM to perform root cause analysis
- Stores lessons with tags: `losing_trade`, `root_cause:XYZ`, symbol

## Data Flow

```
Market Data + News + Technical Signals
        |
        v
  Research Analyst
        |
        +--> Query VectorStore for similar past conditions
        |           |
        |           v
        |    Historical context (top 3 matches)
        |           |
        v           v
  LLM Analysis with RAG context
        |
        v
  Trade Decision
        |
        v
  Store decision in VectorStore (with semantic tags)
        |
        v
  [Later] Trade closes --> update accuracy
        |
        v
  [If loss] RetrospectiveAgent analyzes and stores lessons
```

## Storage

- **Location**: `data/vector_cache/` (ChromaDB persistent client)
- **Collection**: `trade_memory`
- **Embeddings**: `all-MiniLM-L6-v2` (auto-loaded by ChromaDB)
- **Metadata per entry**:
  - `symbol`: Asset symbol
  - `action`: buy / sell / hold
  - `accuracy`: Float 0.0-1.0
  - `timestamp`: ISO format UTC
  - `market_regime`: high_volatility / normal / low_volatility
  - `tags`: Comma-separated semantic tags
  - `source`: trade_context / decision / retrospective (optional)
  - Additional fields from retrospective analysis: `root_cause_category`, `entry_quality`, `exit_quality`

## Configuration

No explicit configuration needed. The system auto-initializes with:
- Default storage: `DATA_DIR / "vector_cache"`
- Default query results: 3
- Default prune window: 30 days

## Maintenance

Run pruning periodically to prevent unbounded growth:

```python
from data.vector_store import AgentMemoryStore

store = AgentMemoryStore()
store.prune_entries_older_than(days=30)
```

## Query Response Format

Each query result contains:
- `past_action`: The action taken (buy/sell/hold)
- `past_accuracy`: Accuracy score at time of storage
- `market_context`: Full context text (up to 500 chars)
- `market_regime`: Market regime classification
- `tags`: List of semantic tags
- `similarity_score`: 1.0 - distance (higher = more similar)
