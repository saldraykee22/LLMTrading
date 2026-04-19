"""
Backtest Module
================
LLM-based backtest engine and utilities.
"""

from backtest.llm_backtest import LLMBacktestEngine, run_llm_backtest, BacktestBarResult, BacktestStats
from backtest.backtest_cache import BacktestCache, BacktestCacheEntry
from backtest.historical_news import HistoricalNewsManager

__all__ = [
    "LLMBacktestEngine",
    "run_llm_backtest",
    "BacktestBarResult",
    "BacktestStats",
    "BacktestCache",
    "BacktestCacheEntry",
    "HistoricalNewsManager",
]
