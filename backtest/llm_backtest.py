"""
LLM Backtest Engine
====================
Main backtest engine using the full LangGraph trading pipeline.
Identical to live trading, but runs on historical data with caching.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table

from backtest.backtest_cache import BacktestCache, BacktestCacheEntry
from backtest.historical_news import HistoricalNewsManager
from backtest.walk_forward import BacktestResult, calculate_metrics, chronological_split
from agents.graph import run_analysis
from agents.state import create_initial_state
from config.settings import get_trading_params
from data.market_data import MarketDataClient
from data.symbol_resolver import resolve_symbol
from execution.order_manager import parse_trade_decision
from models.technical_analyzer import TechnicalAnalyzer
from risk.portfolio import PortfolioState, Position
from risk.stop_loss import DynamicStopLoss

console = Console()
logger = logging.getLogger(__name__)


@dataclass
class BacktestBarResult:
    """Result for a single bar backtest."""
    
    timestamp: datetime
    price: float
    action: str  # buy, sell, hold
    decision: dict[str, Any]
    sentiment: dict[str, Any]
    debate_result: dict[str, Any]
    risk_assessment: dict[str, Any]
    trade_executed: bool = False
    trade_price: float = 0.0
    trade_amount: float = 0.0
    cache_hit: bool = False


@dataclass
class BacktestStats:
    """Backtest statistics."""
    
    total_bars: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    llm_calls: int = 0
    total_trades: int = 0
    buy_trades: int = 0
    sell_trades: int = 0
    avg_decision_time: float = 0.0
    total_decision_time: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "total_bars": self.total_bars,
            "cache_hit_rate": f"{self.cache_hits / max(self.total_bars, 1) * 100:.1f}%",
            "llm_calls": self.llm_calls,
            "total_trades": self.total_trades,
            "avg_decision_time_sec": f"{self.avg_decision_time:.2f}",
        }


class LLMBacktestEngine:
    """
    LLM-based backtest engine.
    
    Uses the same pipeline as live trading:
    1. Market data
    2. Technical analysis
    3. News data
    4. LangGraph pipeline (coordinator → research → debate → risk → trader)
    5. Order execution (paper trading)
    6. Portfolio update
    7. RAG memory store
    """
    
    def __init__(
        self,
        symbol: str,
        initial_cash: float = 10000,
        cache_enabled: bool = True,
        provider: str = "deepseek",
        timeframe: str = "1h",
    ):
        self.symbol = symbol
        self.resolved_symbol = resolve_symbol(symbol)
        self.initial_cash = initial_cash
        self.cache_enabled = cache_enabled
        self.provider = provider
        self.timeframe = timeframe
        
        self.portfolio = PortfolioState(initial_cash=initial_cash, cash=initial_cash)
        self.cache = BacktestCache() if cache_enabled else None
        self.news_manager = HistoricalNewsManager()
        self.tech_analyzer = TechnicalAnalyzer()
        self.stop_loss_mgr = DynamicStopLoss()
        
        self.stats = BacktestStats()
        
        logger.info(f"LLMBacktestEngine initialized: {symbol}, {timeframe}, ${initial_cash}")
    
    async def run_bar_backtest(
        self,
        bar_datetime: datetime,
        lookback_df: pd.DataFrame,
        current_bar: pd.Series,
    ) -> BacktestBarResult:
        """
        Run backtest for a single bar using full LangGraph pipeline.
        
        Args:
            bar_datetime: Bar timestamp
            lookback_df: Lookback DataFrame for technical analysis
            current_bar: Current bar Series
        
        Returns:
            BacktestBarResult
        """
        start_time = asyncio.get_running_loop().time()
        current_price = float(current_bar["close"])
        
        # 1. Cache check
        if self.cache_enabled and self.cache:
            cached = self.cache.get(self.symbol, bar_datetime, self.timeframe)
            if cached:
                logger.debug(f"CACHE HIT: {bar_datetime}")
                self.stats.cache_hits += 1
                return await self._apply_cached_decision(cached, current_bar)
        
        self.stats.cache_misses += 1
        
        # 2. Market data
        market_data = {
            "current_price": current_price,
            "price_change_24h": float(
                (current_bar["close"] - lookback_df["close"].iloc[-2]) / lookback_df["close"].iloc[-2]
            ) if len(lookback_df) > 1 else 0,
            "high_24h": float(current_bar["high"]),
            "low_24h": float(current_bar["low"]),
            "volume_24h": float(current_bar["volume"]),
        }
        
        # 3. Technical analysis
        tech_signals = self.tech_analyzer.analyze(lookback_df, self.symbol)
        tech_dict = tech_signals.to_dict()
        # Ensure current_price from market_data is used (fallback for insufficient bars)
        tech_dict["current_price"] = current_price
        
        # 4. News data + sentiment
        news_data, sentiment_override = await self.news_manager.get_news_for_bar(
            symbol=self.symbol,
            bar_datetime=bar_datetime,
            lookback_hours=24,
            current_price=current_price,
        )
        
        # 5. LANGGRAPH PIPELINE (same as live trading)
        try:
            result = await asyncio.to_thread(run_analysis,
                symbol=self.symbol,  # Use string symbol, not ResolvedSymbol
                market_data=market_data,
                news_data=news_data,
                technical_signals=tech_dict,
                portfolio_state=self.portfolio.to_dict(),
                provider=self.provider,
            )
            self.stats.llm_calls += 1
        except Exception as e:
            logger.error(f"Pipeline error for {bar_datetime}: {e}")
            result = {
                "error": str(e),
                "trade_decision": {"action": "hold", "reason": f"Error: {e}"},
                "sentiment": sentiment_override or {},
                "debate_result": {},
                "risk_assessment": {},
            }

        # Override sentiment if we have cached data
        if sentiment_override and not result.get("sentiment"):
            result["sentiment"] = sentiment_override

        # 6. Apply decision
        decision = result.get("trade_decision", {})
        await self._apply_decision(decision, current_bar, tech_dict)
        await self._apply_decision(decision, current_bar, tech_dict)
        
        # 7. Cache result
        if self.cache_enabled and self.cache:
            cache_entry = BacktestCacheEntry.from_result(
                self.symbol, bar_datetime, self.timeframe, result
            )
            self.cache.save(cache_entry)
        
        # 8. Stats
        elapsed = asyncio.get_running_loop().time() - start_time
        self.stats.total_decision_time += elapsed
        
        # Build result
        action = decision.get("action", "hold")
        trade_executed = action in ("buy", "sell") and decision.get("amount", 0) > 0
        
        return BacktestBarResult(
            timestamp=bar_datetime,
            price=current_price,
            action=action,
            decision=decision,
            sentiment=result.get("sentiment", {}),
            debate_result=result.get("debate_result", {}),
            risk_assessment=result.get("risk_assessment", {}),
            trade_executed=trade_executed,
            trade_price=decision.get("entry_price", current_price),
            trade_amount=decision.get("amount", 0),
            cache_hit=False,
        )
    
    async def _apply_cached_decision(
        self,
        cached: BacktestCacheEntry,
        current_bar: pd.Series,
    ) -> BacktestBarResult:
        """Apply cached decision to portfolio."""
        current_price = float(current_bar["close"])
        decision = cached.decision

        await self._apply_decision(decision, current_bar, {})

        action = decision.get("action", "hold")
        trade_executed = action in ("buy", "sell") and decision.get("amount", 0) > 0

        return BacktestBarResult(
            timestamp=datetime.fromisoformat(cached.timestamp),
            price=current_price,
            action=action,
            decision=decision,
            sentiment=cached.sentiment,
            debate_result=cached.debate_result,
            risk_assessment=cached.risk_assessment,
            trade_executed=trade_executed,
            trade_price=decision.get("entry_price", current_price),
            trade_amount=decision.get("amount", 0),
            cache_hit=True,
        )
    
    async def _apply_decision(
        self,
        decision: dict[str, Any],
        current_bar: pd.Series,
        tech_signals: dict,
    ) -> None:
        """
        Apply trade decision to portfolio.
        
        Args:
            decision: Trade decision from LangGraph
            current_bar: Current bar data
            tech_signals: Technical signals dict
        """
        action = decision.get("action", "hold")
        
        if action == "hold":
            return
        
        current_price = float(current_bar["close"])
        atr_value = tech_signals.get("atr_14", 0)
        
        # Parse order
        order = parse_trade_decision(decision, current_price=current_price, atr_value=atr_value)
        if not order:
            logger.warning(f"Invalid order from decision: {decision}")
            return
        
        # Check existing position
        existing_pos = next(
            (p for p in self.portfolio.positions if p.symbol == order.symbol),
            None
        )
        
        if order.action == "buy":
            if not existing_pos:
                # Open new position
                amount = order.amount
                if amount <= 0:
                    # Calculate position size
                    amount = self.portfolio.calculate_position_size(current_price)
                
                if amount > 0:
                    stop_loss = order.stop_loss
                    take_profit = order.take_profit
                    
                    self.portfolio.open_position(
                        symbol=order.symbol,
                        side="long",
                        price=current_price,
                        amount=amount,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    )
                    logger.info(f"BUY: {order.symbol} {amount} @ {current_price}")
                    self.stats.buy_trades += 1
            else:
                logger.debug(f"Already have position in {order.symbol}, ignoring buy")
        
        elif order.action == "sell":
            if existing_pos:
                # Close position
                self.portfolio.close_position_safe(order.symbol, current_price)
                logger.info(f"SELL: {order.symbol} {existing_pos.amount} @ {current_price}")
                self.stats.sell_trades += 1
            else:
                logger.debug(f"No position in {order.symbol}, ignoring sell")
    
    async def run_full_backtest(
        self,
        df: pd.DataFrame,
        days: int = 90,
    ) -> dict[str, Any]:
        """
        Run full backtest on DataFrame.
        
        Args:
            df: OHLCV DataFrame
            days: Number of days to backtest
        
        Returns:
            Backtest results dict
        """
        console.print(f"\n[bold cyan]LLM Backtest Engine[/bold cyan]")
        console.print(f"Symbol: [bold]{self.symbol}[/bold]")
        console.print(f"Timeframe: {self.timeframe}")
        console.print(f"Days: {days}")
        console.print(f"Initial Cash: ${self.initial_cash:,.2f}")
        console.print(f"Cache Enabled: {self.cache_enabled}")
        
        # Split data - use simpler split for small datasets
        console.print("\n[bold yellow]Splitting data...[/bold yellow]")

        # For quick testing with small datasets, use simple chronological split
        if len(df) <= 100:
            # Simple 80/20 split for small datasets
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx]
            test_df = df.iloc[split_idx:]
            console.print(f"  Using simple split (80/20) for small dataset")
            console.print(f"  Train: {len(train_df)} bars")
            console.print(f"  Test: {len(test_df)} bars")
        else:
            # Walk-forward split for larger datasets
            split = chronological_split(df, train_pct=0.7, validation_pct=0.15, test_pct=0.15)
            console.print(f"  Train: {len(split.train)} bars ({split.train_range})")
            console.print(f"  Validation: {len(split.validation)} bars")
            console.print(f"  Test: {len(split.test)} bars ({split.test_range})")
            test_df = split.test
        if test_df.empty:
            console.print("[red]Test set is empty![/red]")
            return {"error": "Empty test set"}
        
        # Backtest loop
        console.print("\n[bold yellow]Running LLM backtest...[/bold yellow]")
        
        # Ensure datetime index
        if "datetime" in test_df.columns:
            test_df = test_df.set_index("datetime")

        total_bars = len(test_df)
        self.stats.total_bars = total_bars

        # Dynamic window based on test set size
        # For small datasets (like 3 days = ~72 bars, split into 50 train + 22 test)
        # we need a smaller lookback to have enough test bars
        MIN_TEST_BARS = 5  # Minimum bars to test
        MAX_LOOKBACK = min(30, total_bars // 2)  # Can't use more than half the data
        MIN_LOOKBACK = 10  # Minimum for basic technical analysis

        window = max(MIN_LOOKBACK, min(MAX_LOOKBACK, total_bars - MIN_TEST_BARS))
        console.print(f"  Lookback window: {window} bars (test set: {total_bars - window} bars)")

        if total_bars - window < MIN_TEST_BARS:
            console.print(f"[red]Test set too small: {total_bars - window} bars < {MIN_TEST_BARS}[/red]")
            return {"error": "Test set too small"}

        results: list[BacktestBarResult] = []
        progress_interval = max((total_bars - window) // 10, 1)
        
        for i in range(window, total_bars):
            lookback = test_df.iloc[max(0, i - window) : i + 1]
            current_bar = test_df.iloc[i]
            bar_datetime = current_bar.name
            
            if not isinstance(bar_datetime, datetime):
                bar_datetime = pd.Timestamp(bar_datetime).to_pydatetime()
            
            # Run bar backtest
            result = await self.run_bar_backtest(
                bar_datetime=bar_datetime,
                lookback_df=lookback,
                current_bar=current_bar,
            )
            results.append(result)
            
            # Progress update
            if (i - window) % progress_interval == 0:
                progress = (i - window) / (total_bars - window) * 100
                console.print(f"  Progress: {progress:.1f}% ({i - window}/{total_bars - window} bars)")
        
        # Calculate stats
        self.stats.avg_decision_time = self.stats.total_decision_time / max(self.stats.total_bars, 1)
        self.stats.total_trades = self.stats.buy_trades + self.stats.sell_trades
        
        # Calculate metrics
        console.print("\n[bold yellow]Calculating metrics...[/bold yellow]")
        trades = self._extract_trades_from_portfolio()
        metrics = calculate_metrics(trades, self.initial_cash)
        
        # Build result
        result_dict = {
            "metrics": metrics,
            "stats": self.stats.to_dict(),
            "portfolio": self.portfolio.to_dict(),
            "results": results,
        }
        
        # Display results
        self._display_results(result_dict)
        
        return result_dict
    
    def _extract_trades_from_portfolio(self) -> list[dict]:
        """Extract trades from portfolio closed_trades."""
        trades = []
        for trade in self.portfolio.closed_trades:
            trades.append({
                "pnl": trade.get("pnl", 0),
                "pnl_pct": trade.get("pnl_pct", 0),
                "entry_price": trade.get("entry_price", 0),
                "exit_price": trade.get("exit_price", 0),
                "amount": trade.get("amount", 0),
                "symbol": trade.get("symbol", ""),
                "side": trade.get("side", ""),
                "entry_time": trade.get("entry_time", ""),
                "exit_time": trade.get("exit_time", ""),
            })
        return trades
    
    def _display_results(self, result_dict: dict[str, Any]) -> None:
        """Display backtest results."""
        metrics = result_dict["metrics"]
        stats = result_dict["stats"]
        
        console.print("\n" + "=" * 60)
        console.print("[bold green]LLM BACKTEST RESULTS[/bold green]")
        console.print("=" * 60)
        
        # Stats table
        table = Table(title="LLM Statistics", border_style="cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        
        for key, value in stats.items():
            table.add_row(key.replace("_", " ").title(), str(value))
        
        console.print(table)
        
        # Metrics table
        table = Table(title="Trading Performance", border_style="green")
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        
        table.add_row("Total Return", f"{metrics.total_return:.2%}")
        table.add_row("Sharpe Ratio", f"{metrics.sharpe_ratio:.4f}")
        table.add_row("Max Drawdown", f"{metrics.max_drawdown:.2%}")
        table.add_row("Win Rate", f"{metrics.win_rate:.2%}")
        table.add_row("Total Trades", str(metrics.total_trades))
        table.add_row("Profitable Trades", str(metrics.profitable_trades))
        table.add_row("Losing Trades", str(metrics.losing_trades))
        table.add_row("Avg Win", f"${metrics.avg_win:.2f}")
        table.add_row("Avg Loss", f"${metrics.avg_loss:.2f}")
        table.add_row("Profit Factor", f"{metrics.profit_factor:.2f}")
        
        console.print(table)
        
        # Portfolio summary
        console.print("\n[bold]Portfolio Summary:[/bold]")
        console.print(f"  Initial Cash: ${self.initial_cash:,.2f}")
        console.print(f"  Final Equity: ${self.portfolio.equity:,.2f}")
        console.print(f"  Total P&L: ${self.portfolio.total_pnl:,.2f}")
        console.print(f"  Max Drawdown: {self.portfolio.current_drawdown:.2%}")
        console.print(f"  Open Positions: {self.portfolio.open_position_count}")

    def _prepare_results_for_json(self, result_dict: dict[str, Any]) -> dict[str, Any]:
        """Convert results to JSON-serializable format."""
        
        def json_serial(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        # Create a deep copy or rebuild to avoid mutating the original
        serializable_results = []
        for res in result_dict.get("results", []):
            if hasattr(res, "__dict__"):
                item = asdict(res)
                # Ensure datetime is string
                if isinstance(item.get("timestamp"), datetime):
                    item["timestamp"] = item["timestamp"].isoformat()
                serializable_results.append(item)
            else:
                serializable_results.append(res)

        # Build clean dict
        report = {
            "metadata": {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "initial_cash": self.initial_cash,
                "provider": self.provider
            },
            "metrics": asdict(result_dict["metrics"]) if hasattr(result_dict["metrics"], "__dict__") else result_dict["metrics"],
            "stats": result_dict["stats"],
            "portfolio": result_dict["portfolio"],
            "trades": self._extract_trades_from_portfolio(),
            "bar_results": serializable_results
        }
        return report

    def save_results(self, result_dict: dict[str, Any], filename: str | None = None) -> str:
        """Save results to a JSON file."""
        if "error" in result_dict:
            report = {
                "metadata": {
                    "symbol": self.symbol,
                    "timeframe": self.timeframe,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": result_dict["error"]
                }
            }
        else:
            report = self._prepare_results_for_json(result_dict)
        
        results_dir = Path("data/backtest_results")
        results_dir.mkdir(parents=True, exist_ok=True)
        
        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_symbol = self.symbol.replace("/", "_")
            filename = f"backtest_{safe_symbol}_{ts}.json"
            
        file_path = results_dir / filename
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        return str(file_path)


async def run_llm_backtest(
    symbol: str,
    days: int = 90,
    timeframe: str = "1h",
    initial_cash: float = 10000,
    cache_enabled: bool = True,
    provider: str = "deepseek",
    clear_cache: bool = False,
) -> dict[str, Any]:
    """
    Convenience function to run LLM backtest.
    
    Args:
        symbol: Trading symbol
        days: Days to backtest
        timeframe: Candle timeframe
        initial_cash: Initial cash
        cache_enabled: Enable caching
        provider: LLM provider
        clear_cache: Clear cache before running
    
    Returns:
        Backtest results dict
    """
    # Clear cache if requested
    if clear_cache:
        cache = BacktestCache()
        count = cache.clear(symbol)
        logger.info(f"Cleared {count} cache entries for {symbol}")
    
    # Fetch data
    console.print(f"\n[bold yellow]Fetching data for {symbol}...[/bold yellow]")
    market_client = MarketDataClient()
    df = market_client.fetch_ohlcv(symbol, timeframe=timeframe, days=days)
    
    if df.empty or len(df) < 10:
        console.print(f"[red]Insufficient data ({len(df)} bars) - minimum 10 bars required[/red]")
        return {"error": "Insufficient data"}
    
    console.print(f"Loaded {len(df)} bars ({timeframe})")
    
    # Run backtest
    engine = LLMBacktestEngine(
        symbol=symbol,
        initial_cash=initial_cash,
        cache_enabled=cache_enabled,
        provider=provider,
        timeframe=timeframe,
    )
    
    result = await engine.run_full_backtest(df, days=days)
    
    return result
