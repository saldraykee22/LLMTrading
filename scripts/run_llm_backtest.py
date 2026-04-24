"""
LLM Trading System — LLM-Agentic Backtest Script
==================================================
Runs the full multi-agent LLM pipeline on historical data.
This script bridges historical OHLCV and news with the agentic graph.

Usage:
    python scripts/run_llm_backtest.py --symbol BTC/USDT --days 7 --timeframe 1h
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows console encoding fix
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from config.settings import get_trading_params
from data.market_data import MarketDataClient
from data.news_data import NewsClient
from data.symbol_resolver import resolve_symbol
from models.technical_analyzer import TechnicalAnalyzer
from agents.graph import run_analysis
from backtest.walk_forward import calculate_metrics, BacktestResult
from risk.portfolio import PortfolioState

console = Console()
logger = logging.getLogger(__name__)

def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )

def run_llm_backtest(
    symbol: str,
    days: int = 7,
    timeframe: str = "1h",
    provider: str | None = None,
    model: str | None = None,
) -> BacktestResult:
    """
    Runs a backtest using the full LLM agent graph.
    """
    params = get_trading_params()
    resolved = resolve_symbol(symbol)
    
    # Override model if specified
    if model:
        params.agents.analyst_model = model
        params.agents.risk_model = model
        params.agents.trader_model = model
        params.agents.coordinator_model = model

    console.print(
        Panel(
            f"[bold cyan]LLM-Agentic Backtest[/bold cyan]\n"
            f"Symbol: {resolved.symbol}\n"
            f"Timeframe: {timeframe}\n"
            f"Duration: {days} days\n"
            f"Model: {model or params.agents.analyst_model}\n"
            f"Capital: {params.backtest.initial_cash} USDT",
            title="LLM Backtest",
            border_style="cyan",
        )
    )

    # -- 1. Data Fetching (OHLCV) ----------------------------
    console.print("\n[bold yellow]1. Loading Market Data...[/bold yellow]")
    market = MarketDataClient()
    df = market.fetch_ohlcv(symbol, timeframe=timeframe, days=days + 30) # extra buffer for technicals
    
    if df.empty or len(df) < 50:
        console.print("[red]Insufficient market data - aborted[/red]")
        return calculate_metrics([], params.backtest.initial_cash)

    # Convert to datetime if not already and set as index for easier slicing
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    
    # Filter for the actual test period
    end_date = df.index[-1]
    start_date = end_date - timedelta(days=days)
    test_df = df[df.index >= start_date]
    
    console.print(f"  {len(test_df)} candles for test period")

    # -- 2. Data Fetching (News) ------------------------------
    console.print("\n[bold yellow]2. Loading Historical News...[/bold yellow]")
    news_client = NewsClient()
    all_historical_news = []
    try:
        # Fetch news for the entire range once
        all_historical_news = news_client.fetch_all_news(
            symbol=symbol,
            from_date=start_date - timedelta(days=2), # small buffer
            to_date=end_date
        )
        console.print(f"  {len(all_historical_news)} historical news items found")
    except Exception as e:
        console.print(f"  [dim]Could not fetch historical news: {e}. Falling back to technical-only.[/dim]")

    # -- 3. Simulation Prep -----------------------------------
    tech_analyzer = TechnicalAnalyzer()
    portfolio = PortfolioState(
        initial_cash=params.backtest.initial_cash,
        cash=params.backtest.initial_cash,
    )
    
    trades = []
    lookback_window = params.limits.backtest_lookback_window

    console.print("\n[bold yellow]3. Starting Agentic Simulation...[/bold yellow]")
    
    # Progress bar style loop
    for i in range(len(test_df)):
        current_ts = test_df.index[i]
        # Get data up to current_ts
        sub_df = df[df.index <= current_ts].tail(lookback_window + 1)
        
        if len(sub_df) < lookback_window:
            continue
            
        current_price = float(test_df["close"].iloc[i])
        
        # Filter relevant news for this specific timestamp
        # News published in the last 24h of this timestamp
        news_lookback = current_ts - timedelta(hours=params.data.news_lookback_hours)
        relevant_news = [
            n for n in all_historical_news 
            if news_lookback <= n.published_at <= current_ts
        ]
        
        news_serialized = []
        for n in relevant_news[:params.limits.max_news_items]:
            news_serialized.append({
                "title": n.title,
                "summary": n.summary[:300],
                "source": n.source,
                "published_at": n.published_at.isoformat(),
                "symbols": n.symbols,
                "category": n.category,
            })

        # Technical signals
        tech_signals = tech_analyzer.analyze(sub_df, symbol)
        tech_dict = tech_signals.to_dict()
        
        market_summary = {
            "current_price": current_price,
            "high_24h": float(sub_df["high"].tail(24).max()),
            "low_24h": float(sub_df["low"].tail(24).min()),
            "volume_24h": float(sub_df["volume"].tail(24).sum()),
        }

        # -- Invoke LLM Graph --
        console.print(f"  [dim]Step {i+1}/{len(test_df)}: {current_ts} Price: {current_price:.2f} News: {len(relevant_news)}[/dim]")
        
        try:
            result = run_analysis(
                symbol=resolved.symbol,
                market_data=market_summary,
                news_data=news_serialized,
                technical_signals=tech_dict,
                portfolio_state=portfolio.to_dict(),
                provider=provider,
            )
            
            trade_decision = result.get("trade_decision", {})
            action = trade_decision.get("action", "hold")
            
            # Simple Portfolio Simulation (similar to paper_engine but inline)
            # 1. Check existing positions for SL/TP
            for pos in list(portfolio.positions):
                if pos.symbol == resolved.symbol:
                    if pos.should_stop_loss(current_price):
                        effective_sl = pos.stop_loss * 0.9985 # %0.1 commission + %0.05 slippage
                        t = portfolio.close_position(pos.symbol, effective_sl)
                        if t:
                            t["exit_reason"] = "stop_loss"
                            trades.append(t)
                            console.print(f"    [red]SL at {pos.stop_loss}[/red]")
                    elif pos.should_take_profit(current_price):
                        effective_tp = pos.take_profit * 0.9985
                        t = portfolio.close_position(pos.symbol, effective_tp)
                        if t:
                            t["exit_reason"] = "take_profit"
                            trades.append(t)
                            console.print(f"    [green]TP at {pos.take_profit}[/green]")
            
            # 2. Open new position if recommended
            if action == "buy" and portfolio.open_position_count == 0:
                effective_entry = current_price * 1.0015 # %0.1 commission + %0.05 slippage
                amount = portfolio.calculate_position_size(effective_entry)
                if amount > 0:
                    sl = trade_decision.get("stop_loss", current_price * 0.95)
                    tp = trade_decision.get("take_profit", current_price * 1.10)
                    portfolio.open_position(
                        symbol=resolved.symbol,
                        side="long",
                        price=effective_entry,
                        amount=amount,
                        stop_loss=sl,
                        take_profit=tp
                    )
                    console.print(f"    [cyan]BUY at {effective_entry:.2f} (SL: {sl:.2f}, TP: {tp:.2f})[/cyan]")
            elif action == "sell" and portfolio.open_position_count > 0:
                effective_exit = current_price * 0.9985
                t = portfolio.close_position(resolved.symbol, effective_exit)
                if t:
                    t["exit_reason"] = "signal"
                    trades.append(t)
                    console.print(f"    [magenta]SELL at {effective_exit:.2f}[/magenta]")
                    
        except Exception as e:
            console.print(f"    [red]Error in analysis at {current_ts}: {e}[/red]")

    # Close remaining positions
    last_price = float(test_df["close"].iloc[-1])
    effective_last = last_price * 0.9985
    for pos in list(portfolio.positions):
        t = portfolio.close_position(pos.symbol, effective_last)
        if t:
            t["exit_reason"] = "backtest_end"
            trades.append(t)

    # -- 4. Results -------------------------------------------
    metrics = calculate_metrics(trades, params.backtest.initial_cash)
    
    table = Table(title=f"LLM Backtest Results: {symbol}", border_style="green")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    
    table.add_row("Total Return", f"{metrics.total_return:.2%}")
    table.add_row("Sharpe Ratio", f"{metrics.sharpe_ratio:.4f}")
    table.add_row("Max Drawdown", f"{metrics.max_drawdown:.2%}")
    table.add_row("Total Trades", str(metrics.total_trades))
    table.add_row("Win Rate", f"{metrics.win_rate:.2%}")
    
    console.print("\n", table)
    
    return metrics

def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-Agentic Backtest")
    parser.add_argument("--symbol", "-s", required=True, help="Varlık sembolü")
    parser.add_argument("--days", "-d", type=int, default=7, help="Geçmiş gün sayısı")
    parser.add_argument("--timeframe", "-t", default="1h", help="Mum periyodu")
    parser.add_argument("--provider", "-p", default="openrouter", help="LLM sağlayıcı")
    parser.add_argument("--model", "-m", default=None, help="LLM model (qwen/qwen-2.5-72b-instruct vb.)")
    parser.add_argument("--log-level", "-l", default="INFO")

    args = parser.parse_args()
    setup_logging(args.log_level)

    run_llm_backtest(
        symbol=args.symbol,
        days=args.days,
        timeframe=args.timeframe,
        provider=args.provider,
        model=args.model
    )

if __name__ == "__main__":
    main()
